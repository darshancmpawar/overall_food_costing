"""
History manager for menu planning.

Loads history from Supabase dataframes, filters by client and counter,
computes bans and signatures, and persists completed weeks back to
Supabase.

Storage shape (counters revision)::

    menu_history (
        client_name  TEXT,
        service_date DATE,
        menu         JSONB,
        created_at   TIMESTAMPTZ,
        PRIMARY KEY (client_name, service_date)
    )

One row per client-day, with every counter's picks inside ``menu``::

    {"version": 2, "counters": {"South Indian": {"bread": "akki_roti", …}}}

That keeps a day's full service in a single row (so re-saving one counter
can't orphan another's picks) while the in-memory representation stays
the long ``(service_date, slot, item_base, counter_name)`` frame the
cooldown rules were written against — :meth:`expand_menu_rows` converts
between them.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from src.constants import DEFAULT_COUNTER_NAME
from ..preprocessor.column_mapper import _norm_str

# Envelope version stored alongside the per-counter menus. Bumped only if
# the shape changes again; readers accept anything they recognise.
MENU_SCHEMA_VERSION = 2

# Week signatures are one flat text column shared by every counter, so we
# prefix each with its counter to keep one counter's history from
# constraining another's. Rows without the prefix predate counters and
# are treated as belonging to every counter.
_SIG_COUNTER_PREFIX = 'counter='


def counter_signature_prefix(counter_name: str) -> str:
    """Return the ``counter=<name>|`` prefix stamped onto a week signature.

    ``HistoryManager.parse_signature_to_expected_map`` skips any leading
    token that isn't a date, so prefixed signatures stay readable by the
    week-signature cooldown rule without a schema change. ``|`` is the
    signature's field separator, so it's stripped from the counter name.
    """
    return f'{_SIG_COUNTER_PREFIX}{_norm_str(counter_name).replace("|", "/")}|'


def split_signature_counter(signature: str) -> tuple:
    """Split a stored signature into ``(counter_name, signature_body)``.

    Returns ``(None, signature)`` for legacy rows with no counter prefix.
    """
    sig = signature or ''
    if not sig.startswith(_SIG_COUNTER_PREFIX):
        return None, sig
    head, _, rest = sig.partition('|')
    return head[len(_SIG_COUNTER_PREFIX):], rest


def expand_menu_rows(
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Flatten ``menu_history`` rows into long per-slot records.

    Accepts both shapes:

    * counters envelope — ``{"version": 2, "counters": {name: {slot: item}}}``
    * a bare ``{slot: item}`` map, which is read as the default counter
      (hand-written rows, and anything written before counters existed)

    Returns dicts with ``client_name``, ``service_date``, ``counter_name``,
    ``slot``, and ``item_base`` keys — the long format
    :meth:`HistoryManager._ensure_long` validates.
    """
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        menu = row.get('menu')
        if isinstance(menu, str):
            import json
            try:
                menu = json.loads(menu)
            except (ValueError, TypeError):
                menu = None
        if not isinstance(menu, dict):
            continue
        if isinstance(menu.get('counters'), dict):
            per_counter = menu['counters']
        else:
            # Bare {slot: item} map — only take scalar values so a stray
            # metadata key can't masquerade as a counter.
            per_counter = {
                DEFAULT_COUNTER_NAME: {
                    k: v for k, v in menu.items()
                    if not isinstance(v, (dict, list))
                }
            }
        for counter_name, slots in per_counter.items():
            if not isinstance(slots, dict):
                continue
            for slot, item in slots.items():
                out.append({
                    'client_name': row.get('client_name'),
                    'service_date': row.get('service_date'),
                    'counter_name': counter_name,
                    'slot': slot,
                    'item_base': item,
                })
    return out


def _merge_counter_menu(
    prior: Any, counter_name: str, slots: Dict[str, str],
) -> Dict[str, Any]:
    """Return the ``menu`` jsonb for a day with *counter_name* replaced.

    Other counters' picks in *prior* are carried through untouched; a
    bare legacy ``{slot: item}`` map is promoted into the counters
    envelope under :data:`~src.constants.DEFAULT_COUNTER_NAME` first so
    nothing is lost on the first save after the migration.
    """
    counters: Dict[str, Any] = {}
    if isinstance(prior, str):
        import json
        try:
            prior = json.loads(prior)
        except (ValueError, TypeError):
            prior = None
    if isinstance(prior, dict):
        if isinstance(prior.get('counters'), dict):
            counters = {
                k: v for k, v in prior['counters'].items()
                if isinstance(v, dict)
            }
        else:
            legacy = {
                k: v for k, v in prior.items()
                if not isinstance(v, (dict, list))
            }
            if legacy:
                counters[DEFAULT_COUNTER_NAME] = legacy
    counters[counter_name] = dict(slots)
    return {'version': MENU_SCHEMA_VERSION, 'counters': counters}


def _upsert_menu_rows(supabase_client, rows: List[Dict[str, Any]]) -> None:
    """Write ``menu_history`` rows, replacing any existing (client, day).

    Prefers a real UPSERT on the ``(client_name, service_date)`` primary
    key so a day is never momentarily without a menu. Older supabase-py
    builds (and test doubles) that don't take ``on_conflict`` fall back to
    DELETE + INSERT, which has the same end state.
    """
    # Build the query and execute it in separate steps: the fallback is
    # only for clients that don't *offer* upsert(on_conflict=...), so a
    # TypeError raised from inside execute() must still propagate rather
    # than trigger a second write path.
    try:
        query = supabase_client.table('menu_history').upsert(
            rows, on_conflict='client_name,service_date',
        )
    except (AttributeError, TypeError):
        query = None
    if query is not None:
        query.execute()
        return
    for row in rows:
        (
            supabase_client.table('menu_history')
            .delete()
            .eq('client_name', row['client_name'])
            .eq('service_date', row['service_date'])
            .execute()
        )
    supabase_client.table('menu_history').insert(rows).execute()


class HistoryManager:
    """Encapsulates menu history for cooldown and signature operations."""

    def __init__(self):
        self._long: Optional[pd.DataFrame] = None
        self._weeks: Optional[pd.DataFrame] = None

    # ----- Loading -----

    def load_from_dataframes(
        self,
        long_df: Optional[pd.DataFrame] = None,
        weeks_df: Optional[pd.DataFrame] = None,
    ) -> 'HistoryManager':
        """Load history from existing DataFrames. Returns self for chaining."""
        self._long = self._ensure_long(long_df)
        self._weeks = self._ensure_weeks(weeks_df)
        return self

    def load_from_menu_rows(
        self,
        menu_rows: Optional[List[Dict[str, Any]]] = None,
        weeks_rows: Optional[List[Dict[str, Any]]] = None,
    ) -> 'HistoryManager':
        """Load history straight from ``menu_history`` / ``week_signatures``.

        Convenience over :meth:`load_from_dataframes` for the common case
        of feeding raw Supabase rows: the jsonb ``menu`` column is
        expanded to long records first.
        """
        long_records = expand_menu_rows(menu_rows or [])
        long_df = pd.DataFrame(long_records) if long_records else None
        weeks_df = pd.DataFrame(weeks_rows) if weeks_rows else None
        return self.load_from_dataframes(long_df, weeks_df)

    # ----- Schema validation -----

    @staticmethod
    def _ensure_long(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None or len(df) == 0:
            return None
        h = df.copy()
        if 'service_date' not in h.columns or 'item_base' not in h.columns:
            return None
        h['service_date'] = pd.to_datetime(h['service_date'], errors='coerce').dt.date
        h['item_base'] = h['item_base'].map(_norm_str)
        if 'slot' in h.columns:
            h['slot'] = h['slot'].map(_norm_str)
        if 'client_name' in h.columns:
            h['client_name'] = h['client_name'].map(_norm_str)
        if 'counter_name' in h.columns:
            h['counter_name'] = h['counter_name'].map(_norm_str)
        h = h[h['service_date'].notna() & (h['item_base'] != '')]
        return h

    @staticmethod
    def _ensure_weeks(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None or len(df) == 0:
            return None
        h = df.copy()
        if 'week_start' not in h.columns or 'week_signature' not in h.columns:
            return None
        h['week_start'] = pd.to_datetime(h['week_start'], errors='coerce').dt.date
        h['week_signature'] = h['week_signature'].astype(str)
        if 'client_name' in h.columns:
            h['client_name'] = h['client_name'].map(_norm_str)
        h = h[h['week_start'].notna()]
        return h

    # ----- Filtering -----

    def filter_by_client(self, client_name: str) -> 'HistoryManager':
        """Return a new HistoryManager filtered to a single client."""
        c = _norm_str(client_name) if client_name else ''
        hm = HistoryManager()
        hm._long = self._long
        hm._weeks = self._weeks
        if not c:
            return hm
        if hm._long is not None and 'client_name' in hm._long.columns:
            hm._long = hm._long[hm._long['client_name'] == c]
        if hm._weeks is not None and 'client_name' in hm._weeks.columns:
            hm._weeks = hm._weeks[hm._weeks['client_name'] == c]
        return hm

    def filter_by_counter(self, counter_name: str) -> 'HistoryManager':
        """Return a new HistoryManager scoped to a single serving line.

        Cooldowns are per counter on purpose. A client like Continental
        runs South, North, and Pan-Asian lines that each serve bread every
        day; a shared 20-day ban across all three would burn through the
        bread pool three times as fast and make the week infeasible. What
        the planner needs is "this *line* hasn't served this dish
        recently", which is what this scoping gives it.

        Rows with no ``counter_name`` (legacy history) are kept — they
        predate counters, so there's no evidence they belong to a
        different line.
        """
        c = _norm_str(counter_name) if counter_name else ''
        hm = HistoryManager()
        hm._long = self._long
        hm._weeks = self._weeks
        if not c:
            return hm
        if hm._long is not None and 'counter_name' in hm._long.columns:
            col = hm._long['counter_name'].fillna('')
            hm._long = hm._long[(col == c) | (col == '')]
        if hm._weeks is not None and 'week_signature' in hm._weeks.columns:
            # Signature prefixes have '|' (the field separator) swapped
            # for '/', so compare against the same transform.
            sig_counter = c.replace('|', '/')
            counters = hm._weeks['week_signature'].map(
                lambda s: split_signature_counter(s)[0]
            )
            hm._weeks = hm._weeks[counters.isna() | (counters == sig_counter)]
        return hm

    # ----- Ban computation -----

    def banned_items_by_date(
        self,
        dates: List[dt.date],
        cooldown_days: int = 20,
        const_slots: List[str] = (),
        repeatable_items: Set[str] = frozenset(),
    ) -> Dict[dt.date, Set[str]]:
        """Return banned items per date based on recent usage."""
        h = self._long
        if h is None:
            return {d: set() for d in dates}
        const_set = set(const_slots)
        out: Dict[dt.date, Set[str]] = {}
        for d in dates:
            start = d - dt.timedelta(days=cooldown_days)
            m = (h['service_date'] >= start) & (h['service_date'] < d)
            if 'slot' in h.columns:
                m &= ~h['slot'].isin(const_set)
            banned = set(h.loc[m, 'item_base'].tolist()) - set(repeatable_items)
            out[d] = banned
        return out

    def recent_week_signatures(
        self,
        week_start: dt.date,
        cooldown_days: int = 30,
    ) -> Set[str]:
        """Return week signatures within the cooldown window."""
        h = self._weeks
        if h is None:
            return set()
        start = week_start - dt.timedelta(days=cooldown_days)
        mask = (h['week_start'] >= start) & (h['week_start'] < week_start)
        return set(h.loc[mask, 'week_signature'].tolist())

    def ricebread_ban_by_date(
        self,
        dates: List[dt.date],
        ricebread_items: Set[str],
        gap_days: int = 10,
        base_slot_fn=None,
    ) -> Dict[dt.date, bool]:
        """Return per-date flag if rice-bread was used too recently."""
        h = self._long
        if h is None or gap_days <= 0 or not ricebread_items:
            return {d: False for d in dates}
        out: Dict[dt.date, bool] = {}
        for d in dates:
            start = d - dt.timedelta(days=gap_days)
            m = (h['service_date'] >= start) & (h['service_date'] < d)
            if 'slot' in h.columns:
                if base_slot_fn is None:
                    m &= h['slot'] == 'bread'
                else:
                    m &= h['slot'].map(base_slot_fn) == 'bread'
            m &= h['item_base'].isin(ricebread_items)
            out[d] = bool(m.any())
        return out

    # ----- Save -----

    def save(
        self,
        week_plan: Dict,
        dates: List[dt.date],
        client_name: str,
        week_start: dt.date,
        week_signature: str,
        supabase_client,
        strip_color_fn=None,
        counter_name: str = DEFAULT_COUNTER_NAME,
    ):
        """Persist a completed week plan to Supabase with **overwrite**
        semantics.

        Re-saving a plan for the same (client, counter, dates) replaces
        the previously saved menu instead of appending — so the UI's "Save
        again after regenerating" flow ends up with exactly one menu per
        (day, counter), and "Load saved plan" returns the freshest pick.

        ``menu_history`` holds one row per (client, day) with every
        counter's picks nested inside the ``menu`` jsonb, so saving one
        counter merges into whatever the other counters already stored
        for that day rather than replacing the row wholesale. That read →
        merge → upsert is not atomic; two admins saving different
        counters for the same day at the same moment can have one
        overwrite the other. The window is milliseconds and the loser
        just clicks Save again, which is a better trade than requiring a
        transactional RPC against Supabase.
        """
        if supabase_client is None:
            raise ValueError("supabase_client is required to save history.")

        counter = counter_name or DEFAULT_COUNTER_NAME
        date_isos = [d.isoformat() for d in dates]

        # Read the existing rows so other counters' picks survive.
        existing: Dict[str, Dict[str, Any]] = {}
        if date_isos:
            resp = (
                supabase_client.table('menu_history')
                .select('client_name, service_date, menu')
                .eq('client_name', client_name)
                .in_('service_date', date_isos)
                .execute()
            )
            for row in resp.data or []:
                iso = row.get('service_date')
                if iso:
                    existing[str(iso)] = row

        rows = []
        for d in dates:
            iso = d.isoformat()
            day_map = week_plan.get(d, {})
            slots = {}
            for slot_id, item_val in day_map.items():
                item_base = strip_color_fn(item_val) if strip_color_fn else item_val
                slots[slot_id] = _norm_str(item_base)

            prior = existing.get(iso, {}).get('menu')
            merged = _merge_counter_menu(prior, counter, slots)
            rows.append({
                'client_name': client_name,
                'service_date': iso,
                'menu': merged,
            })

        if rows:
            _upsert_menu_rows(supabase_client, rows)

        # Same overwrite rule for the per-week signature row, scoped to
        # this counter so a multi-counter client keeps one signature per
        # line. Legacy prefix-less rows for the week are cleared too:
        # they were written before counters existed, so leaving them
        # would constrain every counter with a single line's history.
        prefix = counter_signature_prefix(counter)
        stale = (
            supabase_client.table('week_signatures')
            .select('week_signature')
            .eq('client_name', client_name)
            .eq('week_start', week_start.isoformat())
            .execute()
        )
        own_counter = _norm_str(counter).replace('|', '/')
        # Match on the signature text rather than the row id: the id is
        # database-generated, so filtering on it would silently no-op
        # anywhere the column isn't echoed back.
        stale_sigs = [
            row['week_signature'] for row in (stale.data or [])
            if row.get('week_signature')
            and split_signature_counter(row['week_signature'])[0]
            in (None, own_counter)
        ]
        if stale_sigs:
            (
                supabase_client.table('week_signatures')
                .delete()
                .eq('client_name', client_name)
                .eq('week_start', week_start.isoformat())
                .in_('week_signature', stale_sigs)
                .execute()
            )
        supabase_client.table('week_signatures').insert({
            'week_start': week_start.isoformat(),
            'week_signature': f'{prefix}{week_signature}',
            'client_name': client_name,
        }).execute()

    # ----- Load saved plan -----

    @staticmethod
    def load_saved_plan(
        supabase_client,
        client_name: str,
        dates: List[dt.date],
        counter_name: str = DEFAULT_COUNTER_NAME,
    ) -> Dict[dt.date, Dict[str, str]]:
        """Return the saved menu for *client_name* / *counter_name* across *dates*.

        Result shape: ``{date: {slot_id: item_base}}``. Only dates that
        have a saved menu for this counter are present in the dict, so
        callers can distinguish "fully saved" (all requested dates
        present) from "partially saved" (some missing) or "not saved"
        (empty dict).

        ``item_base`` is the de-colorised normalised name we persisted
        in ``menu_history``. The caller is responsible for re-attaching
        a color suffix for display (see ``api.app._enrich_history_plan``).
        """
        if supabase_client is None:
            raise ValueError("supabase_client is required to load history.")
        if not dates:
            return {}

        date_isos = [d.isoformat() for d in dates]
        resp = (
            supabase_client.table('menu_history')
            .select('service_date, menu')
            .eq('client_name', client_name)
            .in_('service_date', date_isos)
            .execute()
        )
        rows = resp.data or []
        wanted = _norm_str(counter_name or DEFAULT_COUNTER_NAME)

        by_iso: Dict[str, Dict[str, str]] = {}
        for record in expand_menu_rows(rows):
            iso = record.get('service_date')
            slot = record.get('slot')
            if not iso or not slot:
                continue
            if _norm_str(record.get('counter_name', '')) != wanted:
                continue
            by_iso.setdefault(str(iso), {})[slot] = record.get('item_base') or ''

        # Translate ISO strings back to dt.date for the caller. We do
        # this last (rather than at row-iteration time) so an unexpected
        # date format from Supabase doesn't silently drop a row.
        out: Dict[dt.date, Dict[str, str]] = {}
        for iso, slots in by_iso.items():
            if not slots:
                continue
            try:
                out[dt.date.fromisoformat(iso)] = slots
            except (TypeError, ValueError):
                continue
        return out

    # ----- Signature computation -----

    @staticmethod
    def compute_week_signature(
        week_plan: Dict,
        dates: List[dt.date],
        const_slots: List[str] = (),
        strip_color_fn=None,
    ) -> str:
        """Compute a deterministic signature string for a week plan."""
        const_set = set(const_slots)

        # Infer slot order from the first non-empty day
        slot_order: List[str] = []
        for d in dates:
            day_map = week_plan.get(d, {})
            if day_map:
                slot_order = [k for k in day_map.keys() if k not in const_set]
                break

        parts: List[str] = []
        for d in dates:
            parts.append(d.isoformat())
            day_map = week_plan.get(d, {})
            for slot_id in slot_order:
                val = day_map.get(slot_id, '')
                if strip_color_fn:
                    val = strip_color_fn(val)
                parts.append(f'{slot_id}={_norm_str(val)}')
        return '|'.join(parts)

    # ----- Signature parsing -----

    @staticmethod
    def parse_signature_to_expected_map(sig: str) -> Dict:
        """Parse a week signature into {(date_iso, slot): item_base} map."""
        parts = sig.split('|')
        out: Dict = {}
        i = 0
        while i < len(parts):
            token = parts[i]
            if re.match(r'^\d{4}-\d{2}-\d{2}$', token):
                date_iso = token
                i += 1
                while i < len(parts) and not re.match(r'^\d{4}-\d{2}-\d{2}$', parts[i]):
                    kv = parts[i]
                    if '=' in kv:
                        slot, val = kv.split('=', 1)
                        out[(date_iso, _norm_str(slot))] = _norm_str(val)
                    i += 1
            else:
                i += 1
        return out
