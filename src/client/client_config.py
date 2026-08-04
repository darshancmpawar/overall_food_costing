"""
Client configuration loader — Supabase backend.

Every read queries Supabase directly so any change made via the UI,
API, or dashboard is immediately reflected on the next call.

Schema (counters revision)::

    clients (
        name               TEXT PRIMARY KEY,
        counters           JSONB NOT NULL DEFAULT '[]',
        city               TEXT,
        serve_weekends     BOOLEAN NOT NULL DEFAULT false,
        item_cooldown_days INT,
        source_pools       JSONB NOT NULL DEFAULT '[]',
        version            INT NOT NULL DEFAULT 1,
        created_at         TIMESTAMPTZ DEFAULT now()
    )
    app_settings (key TEXT PK, value JSONB)

A *counter* is one serving line. Each entry of ``clients.counters`` is::

    {
      "name": "South Indian",
      "categories":  ["bread", "rice", …],   # slots this line serves
      "slot_counts": {"veg_dry": 2, …},      # how many of each per day
      "theme_map":   {"monday": "south", …}  # cuisine theme per weekday
    }

This replaces the previous ``menu_categories`` / ``slot_count_overrides``
/ ``theme_overrides`` tables: a client's slot set, per-slot counts, and
theme map are now per-counter and stored inline, so one client can serve
several different menus on the same day.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.constants import (
    ALL_DAY_NAMES,
    AVAILABLE_THEMES,
    BASE_SLOT_NAMES as BASE_SLOTS,
    CONST_SLOTS,
    DEFAULT_COUNTER_NAME,
    DEFAULT_ITEM_COOLDOWN_DAYS,
    DEFAULT_THEME_MAP,
    WEEKDAY_NAMES,
    canonical_theme,
)
from src.db import get_supabase
from src.preprocessor.pool_builder import _expand_slots_in_order

logger = logging.getLogger(__name__)


# Postgres error code for "undefined_column"; raised by the Supabase REST
# layer when a SELECT / UPDATE references a column that doesn't exist —
# e.g. when a deployment is still on the pre-counters schema. Detecting it
# lets us degrade gracefully (the editor keeps working) while logging a
# loud, actionable hint so the operator knows to run the migration.
_PG_UNDEFINED_COLUMN = "42703"
_MIGRATION_HINT = (
    "Run scripts/create_tables.sql (and scripts/migrate_to_counters.sql "
    "if this deployment predates the counters schema) in the Supabase SQL "
    "editor to apply the latest migrations."
)

# Columns the loader selects from ``clients``. Kept in one place so the
# graceful-degradation path below knows exactly what it may lose.
_CLIENT_COLUMNS = (
    'name, counters, city, serve_weekends, item_cooldown_days, '
    'source_pools, version'
)


def _is_undefined_column(exc: BaseException) -> bool:
    """Return True if *exc* looks like a Postgres undefined-column error.

    Supabase-py wraps PostgREST errors in a class with ``code`` and
    ``message`` attributes, but the exact class name has shifted across
    versions, so check both the structured field and the stringified
    message as a fallback.
    """
    if getattr(exc, "code", None) == _PG_UNDEFINED_COLUMN:
        return True
    msg = str(exc).lower()
    return "does not exist" in msg and "column" in msg


__all__ = [
    # DEFAULT_THEME_MAP / AVAILABLE_THEMES live in src.constants but are
    # re-exported here: api.app surfaces both in /editor-metadata and has
    # imported them from this module since before the counters schema.
    'AVAILABLE_THEMES',
    'ClientConfig',
    'ClientConfigLoader',
    'ConcurrentEditError',
    'CounterConfig',
    'DEFAULT_THEME_MAP',
    'UnknownCounterError',
]


class ConcurrentEditError(ValueError):
    """Raised when an optimistic-concurrency version check fails.

    The ``current_version`` attribute carries the version that's actually
    in the database right now so callers can surface it (e.g. in a 409
    response body) and the client can refresh + retry.
    """

    def __init__(self, message: str, *, current_version: int | None = None):
        super().__init__(message)
        self.current_version = current_version


class UnknownCounterError(ValueError):
    """Raised when a caller names a counter the client doesn't have.

    ``available`` lists the counter names that do exist so the error
    message (and a 400 response built from it) can point somewhere
    useful.
    """

    def __init__(self, message: str, *, available: Optional[List[str]] = None):
        super().__init__(message)
        self.available = list(available or [])


@dataclass
class CounterConfig:
    """One serving line's menu shape.

    ``categories`` is the raw slot list as stored (may include constant
    slots like ``papad``); ``active_slots`` is that list expanded by
    ``slot_counts`` into the numbered slot ids the solver works with
    (``veg_dry`` x2 → ``veg_dry__1``, ``veg_dry__2``).
    """

    name: str
    categories: List[str] = field(default_factory=list)
    slot_counts: Dict[str, int] = field(default_factory=dict)
    theme_map: Dict[str, str] = field(default_factory=dict)
    active_slots: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON shape stored in ``clients.counters``."""
        return {
            'name': self.name,
            'categories': list(self.categories),
            'slot_counts': dict(self.slot_counts),
            'theme_map': dict(self.theme_map),
        }


@dataclass
class ClientConfig:
    """A client plus the one counter the current request is planning for.

    The solver, rules, and formatters only ever plan one serving line at
    a time, so ``active_slots`` / ``slot_counts`` / ``theme_map`` project
    the *selected* counter and keep the downstream contract unchanged.
    ``counters`` carries every line so callers can iterate (the UI's
    counter picker, the editor).
    """

    name: str
    active_slots: List[str] = field(default_factory=list)
    slot_counts: Dict[str, int] = field(default_factory=dict)
    theme_map: Dict[str, str] = field(default_factory=dict)
    counter_name: str = DEFAULT_COUNTER_NAME
    counters: List[CounterConfig] = field(default_factory=list)
    city: str = ''
    serve_weekends: bool = False
    item_cooldown_days: int = DEFAULT_ITEM_COOLDOWN_DAYS
    source_pools: List[str] = field(default_factory=list)

    @property
    def counter_names(self) -> List[str]:
        return [c.name for c in self.counters]


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for v in values:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _as_json(value, default):
    """Coerce a Supabase JSONB cell into Python.

    supabase-py normally hands back decoded JSON, but a column typed
    ``text`` (or a driver version that doesn't decode) yields a string.
    Accept both so a schema that stores counters as text still loads.
    """
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return value


def _normalise_theme_map(raw, *, serve_weekends: bool = False) -> Dict[str, str]:
    """Return a full day → solver-theme map from a stored theme map.

    Missing days fall back to :data:`DEFAULT_THEME_MAP`, extended theme
    names are canonicalised (``chinese_continental`` → ``chinese``), and
    unknown days are dropped. Weekend keys are only included when the
    client actually serves weekends, so a Mon–Fri client can't pick up a
    Saturday theme by accident.
    """
    days = list(ALL_DAY_NAMES) if serve_weekends else list(WEEKDAY_NAMES)
    stored = {}
    if isinstance(raw, dict):
        for day, theme in raw.items():
            key = str(day).strip().lower()
            if key in days:
                stored[key] = canonical_theme(str(theme))
    return {
        day: stored.get(day, canonical_theme(DEFAULT_THEME_MAP[day]))
        for day in days
    }


def _normalise_categories(raw) -> List[str]:
    """Return the stored slot list, keeping order and dropping unknowns."""
    if not isinstance(raw, (list, tuple)):
        return []
    known = set(BASE_SLOTS) | set(CONST_SLOTS)
    out = [
        str(s).strip().lower() for s in raw
        if str(s).strip().lower() in known
    ]
    return _dedupe_preserve_order(out)


class ClientConfigLoader:
    """
    Loads client configuration from Supabase.

    Every property and method issues a live query — there is no in-memory
    cache, so data is always consistent with the database.
    """

    def __init__(self, config_path: str = ''):
        self._sb = get_supabase()

    # ---- internal helpers --------------------------------------------------

    def _setting(self, key: str):
        """Read a single value from the app_settings table."""
        row = (
            self._sb.table('app_settings')
            .select('value')
            .eq('key', key)
            .maybe_single()
            .execute()
        )
        if row.data is None:
            return None
        val = row.data['value']
        # A jsonb cell normally decodes to a list/dict/scalar. Some
        # exports round-trip a JSON string as bare text ("menu_cat_3"
        # rather than "\"menu_cat_3\""), so fall back to the raw value
        # instead of dropping the setting.
        if isinstance(val, str):
            return _as_json(val, val)
        return val

    def _client_row(self, name: str) -> Dict[str, Any]:
        """Return the raw ``clients`` row for *name*.

        Falls back to a name-only select when the counters columns are
        missing (deployment still on the old schema) so the caller gets a
        clear "run the migration" log instead of a 500 from PostgREST.
        """
        try:
            row = (
                self._sb.table('clients')
                .select(_CLIENT_COLUMNS)
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_undefined_column(exc):
                logger.error(
                    "clients table is missing one or more counters-schema "
                    "columns (%s) — falling back to defaults for %r. %s",
                    _CLIENT_COLUMNS, name, _MIGRATION_HINT,
                )
                self._require_client_exists(name)
                return {'name': name}
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return row.data

    def _counters_from_row(self, row: Dict[str, Any]) -> List[CounterConfig]:
        """Parse ``clients.counters`` into :class:`CounterConfig` objects.

        A client with no counters (freshly inserted by hand, or a row that
        predates the migration) yields an empty list — callers surface
        that as a configuration error rather than silently planning an
        empty menu.
        """
        serve_weekends = bool(row.get('serve_weekends'))
        raw_counters = _as_json(row.get('counters'), []) or []
        if isinstance(raw_counters, dict):
            # Tolerate a single counter stored as an object rather than a
            # one-element array.
            raw_counters = [raw_counters]
        if not raw_counters:
            return []
        # Read the min-one list once per row rather than once per counter —
        # it's a Supabase round-trip and identical for every counter.
        core_min_one = self.core_min_one_slots
        out: List[CounterConfig] = []
        for idx, entry in enumerate(raw_counters, start=1):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get('name') or f'Counter {idx}').strip()
            categories = _normalise_categories(entry.get('categories'))
            slot_counts = self._normalise_slot_counts(
                entry.get('slot_counts'), categories, core_min_one,
            )
            theme_map = _normalise_theme_map(
                entry.get('theme_map'), serve_weekends=serve_weekends,
            )
            out.append(CounterConfig(
                name=name,
                categories=categories,
                slot_counts=slot_counts,
                theme_map=theme_map,
                active_slots=self._expand(categories, slot_counts),
            ))
        return out

    def _normalise_slot_counts(
        self,
        raw,
        categories: List[str],
        core_min_one: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Return per-slot counts for every base slot.

        Slots the counter doesn't serve get 0 so ``_expand`` drops them;
        slots it does serve default to 1. ``core_min_one_slots`` is
        applied only to slots the counter actually serves — forcing a
        minimum on a slot the client never offers would invent a serving
        line out of thin air.

        Pass *core_min_one* when normalising several counters in a row to
        avoid re-reading it from ``app_settings`` each time.
        """
        stored = raw if isinstance(raw, dict) else {}
        must_have = (
            core_min_one if core_min_one is not None
            else self.core_min_one_slots
        )
        active = set(categories)
        counts: Dict[str, int] = {}
        for slot in BASE_SLOTS:
            if slot not in active:
                counts[slot] = 0
                continue
            try:
                counts[slot] = max(0, int(stored.get(slot, 1)))
            except (TypeError, ValueError):
                counts[slot] = 1
        for must in must_have:
            if must in active:
                counts[must] = max(1, int(counts.get(must, 1)))
        return counts

    @staticmethod
    def _expand(categories: List[str], slot_counts: Dict[str, int]) -> List[str]:
        """Expand base slots into numbered slot ids, constants passed through."""
        expanded: List[str] = []
        for slot in categories:
            if slot in CONST_SLOTS:
                expanded.append(slot)
            else:
                expanded.extend(
                    _expand_slots_in_order(
                        [slot], {slot: slot_counts.get(slot, 1)},
                    )
                )
        return _dedupe_preserve_order(expanded)

    @staticmethod
    def _pick_counter(
        counters: List[CounterConfig],
        counter_name: Optional[str],
        client_name: str,
    ) -> CounterConfig:
        """Return the requested counter, or the first one by default."""
        if not counters:
            raise ValueError(
                f"Client {client_name!r} has no counters configured. Add at "
                f"least one counter (slots + themes) in the customisation "
                f"editor, or delete the client."
            )
        if not counter_name:
            return counters[0]
        wanted = str(counter_name).strip().lower()
        for counter in counters:
            if counter.name.strip().lower() == wanted:
                return counter
        raise UnknownCounterError(
            f"Unknown counter {counter_name!r} for client {client_name!r}.",
            available=[c.name for c in counters],
        )

    # ---- read properties ---------------------------------------------------

    @property
    def client_names(self) -> List[str]:
        rows = (
            self._sb.table('clients')
            .select('name')
            .order('name')
            .execute()
        )
        return [r['name'] for r in rows.data]

    @property
    def core_min_one_slots(self) -> List[str]:
        val = self._setting('core_min_one_slots')
        return val if val else []

    @property
    def constant_slots(self) -> List[str]:
        val = self._setting('constant_slots')
        return val if val else list(CONST_SLOTS)

    # ---- client read methods -----------------------------------------------

    def get_client(
        self, name: str, counter_name: Optional[str] = None,
    ) -> ClientConfig:
        """Return a fully-populated ClientConfig for one of the client's counters.

        *counter_name* selects the serving line to plan; omitted means the
        client's first counter, which is what single-counter clients (the
        large majority) always want.
        """
        row = self._client_row(name)
        counters = self._counters_from_row(row)
        selected = self._pick_counter(counters, counter_name, name)
        return ClientConfig(
            name=name,
            active_slots=list(selected.active_slots),
            slot_counts=dict(selected.slot_counts),
            theme_map=dict(selected.theme_map),
            counter_name=selected.name,
            counters=counters,
            city=str(row.get('city') or ''),
            serve_weekends=bool(row.get('serve_weekends')),
            item_cooldown_days=self._coerce_cooldown(
                row.get('item_cooldown_days'),
            ),
            source_pools=[
                str(p) for p in (_as_json(row.get('source_pools'), []) or [])
            ],
        )

    @staticmethod
    def _coerce_cooldown(value) -> int:
        """Return a usable cooldown from a possibly-NULL column."""
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return DEFAULT_ITEM_COOLDOWN_DAYS
        return coerced if coerced >= 0 else DEFAULT_ITEM_COOLDOWN_DAYS

    def get_counters(self, name: str) -> List[CounterConfig]:
        """Return every counter configured for a client, in stored order."""
        return self._counters_from_row(self._client_row(name))

    def get_counter_names(self, name: str) -> List[str]:
        return [c.name for c in self.get_counters(name)]

    def get_client_settings(self, name: str) -> Dict[str, Any]:
        """Return the client-level (not per-counter) settings."""
        row = self._client_row(name)
        return {
            'city': str(row.get('city') or ''),
            'serve_weekends': bool(row.get('serve_weekends')),
            'item_cooldown_days': self._coerce_cooldown(
                row.get('item_cooldown_days'),
            ),
            'source_pools': [
                str(p) for p in (_as_json(row.get('source_pools'), []) or [])
            ],
        }

    def get_active_slots_for_client(
        self, name: str, counter_name: Optional[str] = None,
    ) -> List[str]:
        """Return the base (unexpanded) slots for one of a client's counters."""
        counters = self.get_counters(name)
        return list(self._pick_counter(counters, counter_name, name).categories)

    def get_slot_counts_for_client(
        self, name: str, counter_name: Optional[str] = None,
    ) -> Dict[str, int]:
        counters = self.get_counters(name)
        return dict(
            self._pick_counter(counters, counter_name, name).slot_counts,
        )

    def get_theme_map_for_client(
        self, name: str, counter_name: Optional[str] = None,
    ) -> Dict[str, str]:
        counters = self.get_counters(name)
        return dict(self._pick_counter(counters, counter_name, name).theme_map)

    # ---- mutation methods --------------------------------------------------

    def _write_counters(
        self, name: str, counters: List[CounterConfig],
    ) -> None:
        self._sb.table('clients').update({
            'counters': [c.to_dict() for c in counters],
        }).eq('name', name).execute()

    def create_client(
        self,
        name: str,
        active_slots: List[str],
        *,
        counter_name: str = DEFAULT_COUNTER_NAME,
        slot_counts: Optional[Dict[str, int]] = None,
        theme_map: Optional[Dict[str, str]] = None,
        city: str = '',
        serve_weekends: bool = False,
        item_cooldown_days: int = DEFAULT_ITEM_COOLDOWN_DAYS,
        source_pools: Optional[List[str]] = None,
    ) -> None:
        """Create a client with a single starting counter."""
        categories = _normalise_categories(active_slots)
        if not categories:
            raise ValueError(
                "A client needs at least one valid category (slot). "
                f"Got: {active_slots!r}"
            )
        counter = CounterConfig(
            name=str(counter_name).strip() or DEFAULT_COUNTER_NAME,
            categories=categories,
            slot_counts=self._normalise_slot_counts(slot_counts, categories),
            theme_map=_normalise_theme_map(
                theme_map, serve_weekends=serve_weekends,
            ),
        )
        self._sb.table('clients').insert({
            'name': name,
            'counters': [counter.to_dict()],
            'city': city or None,
            'serve_weekends': bool(serve_weekends),
            'item_cooldown_days': int(item_cooldown_days),
            'source_pools': list(source_pools or []),
        }).execute()

    def delete_client(self, name: str) -> None:
        self._require_client_exists(name)
        # menu_history / week_signatures cascade on the FK.
        self._sb.table('clients').delete().eq('name', name).execute()

    def update_client_settings(
        self,
        name: str,
        *,
        city: Optional[str] = None,
        serve_weekends: Optional[bool] = None,
        item_cooldown_days: Optional[int] = None,
        source_pools: Optional[List[str]] = None,
    ) -> None:
        """Update client-level settings. Omitted fields are left alone."""
        payload: Dict[str, Any] = {}
        if city is not None:
            payload['city'] = city or None
        if serve_weekends is not None:
            payload['serve_weekends'] = bool(serve_weekends)
        if item_cooldown_days is not None:
            cooldown = int(item_cooldown_days)
            if cooldown < 0:
                raise ValueError("item_cooldown_days must be >= 0")
            payload['item_cooldown_days'] = cooldown
        if source_pools is not None:
            payload['source_pools'] = [
                str(p).strip() for p in source_pools if str(p).strip()
            ]
        if not payload:
            return
        self._sb.table('clients').update(payload).eq('name', name).execute()

    def upsert_counter(
        self,
        name: str,
        counter_name: str,
        *,
        categories: Optional[List[str]] = None,
        slot_counts: Optional[Dict[str, int]] = None,
        theme_map: Optional[Dict[str, str]] = None,
        new_name: Optional[str] = None,
    ) -> None:
        """Create or update one counter on a client.

        Only the fields passed are touched, so the editor can save the
        theme map without having to resend the slot list. A counter name
        that doesn't exist yet is appended.
        """
        row = self._client_row(name)
        serve_weekends = bool(row.get('serve_weekends'))
        counters = self._counters_from_row(row)
        wanted = str(counter_name).strip()
        idx = next(
            (
                i for i, c in enumerate(counters)
                if c.name.strip().lower() == wanted.lower()
            ),
            None,
        )
        if idx is None:
            base_categories = _normalise_categories(categories or [])
            if not base_categories:
                raise ValueError(
                    f"New counter {wanted!r} needs at least one category."
                )
            counters.append(CounterConfig(
                name=wanted,
                categories=base_categories,
                slot_counts=self._normalise_slot_counts(
                    slot_counts, base_categories,
                ),
                theme_map=_normalise_theme_map(
                    theme_map, serve_weekends=serve_weekends,
                ),
            ))
        else:
            current = counters[idx]
            new_categories = (
                _normalise_categories(categories)
                if categories is not None else current.categories
            )
            if not new_categories:
                raise ValueError(
                    f"Counter {wanted!r} needs at least one category."
                )
            # Recompute counts whenever the slot set moves, so a slot that
            # was just removed can't leave a stale count behind.
            new_counts = self._normalise_slot_counts(
                slot_counts if slot_counts is not None else current.slot_counts,
                new_categories,
            )
            new_themes = (
                _normalise_theme_map(theme_map, serve_weekends=serve_weekends)
                if theme_map is not None else current.theme_map
            )
            counters[idx] = CounterConfig(
                name=str(new_name).strip() if new_name else current.name,
                categories=new_categories,
                slot_counts=new_counts,
                theme_map=new_themes,
            )
        self._write_counters(name, counters)

    def delete_counter(self, name: str, counter_name: str) -> None:
        """Remove a counter. The last remaining counter can't be deleted."""
        counters = self.get_counters(name)
        wanted = str(counter_name).strip().lower()
        remaining = [
            c for c in counters if c.name.strip().lower() != wanted
        ]
        if len(remaining) == len(counters):
            raise UnknownCounterError(
                f"Unknown counter {counter_name!r} for client {name!r}.",
                available=[c.name for c in counters],
            )
        if not remaining:
            raise ValueError(
                "A client must keep at least one counter. Delete the client "
                "instead if it is no longer served."
            )
        self._write_counters(name, remaining)

    # ---- optimistic concurrency -------------------------------------------

    def get_client_version(self, name: str) -> int:
        """Return the current version counter for a client.

        Fresh rows default to 1; every successful PUT through the API
        bumps this by one. If the ``version`` column doesn't exist, log a
        clear ERROR and return 1 — the editor stays usable,
        optimistic-concurrency just no-ops until the migration runs.
        """
        try:
            row = (
                self._sb.table('clients')
                .select('version')
                .eq('name', name)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if _is_undefined_column(exc):
                logger.error(
                    "clients.version column missing — falling back to "
                    "version=1 for %r. %s",
                    name, _MIGRATION_HINT,
                )
                # Confirm the row exists at all so callers still get the
                # right ValueError for a typo'd client name.
                self._require_client_exists(name)
                return 1
            raise
        if not row.data:
            raise ValueError(f"Unknown client: {name}")
        return int(row.data.get('version', 1))

    def _require_client_exists(self, name: str) -> None:
        """Raise ValueError if no client row exists with this name.

        Used by version-related fallbacks so the loader still 404s on
        a typo even when the version column itself isn't queryable.
        """
        row = (
            self._sb.table('clients')
            .select('name')
            .eq('name', name)
            .maybe_single()
            .execute()
        )
        if not row.data:
            raise ValueError(f"Unknown client: {name}")

    def bump_version_if_matches(self, name: str, expected: int) -> int:
        """Atomically bump ``version`` from *expected* to *expected+1*.

        Implemented as a conditional update — the WHERE clause includes
        ``version = expected``, so concurrent writers race at the DB and
        only one succeeds. Zero rows affected means our version is stale
        (someone else wrote between our GET and PUT) or the client was
        deleted.

        If the ``version`` column doesn't exist (pre-migration
        deployment), the conditional filter blows up — we log an ERROR
        and skip the check so writes still go through. The hint in the
        log tells operators what to do.

        Raises:
            ConcurrentEditError: when the update matches no rows. The
                error carries the *current* version so callers can feed
                it back to the user.
        """
        new_version = int(expected) + 1
        try:
            result = (
                self._sb.table('clients')
                .update({'version': new_version})
                .eq('name', name)
                .eq('version', int(expected))
                .execute()
            )
        except Exception as exc:
            if _is_undefined_column(exc):
                logger.error(
                    "clients.version column missing — bumping without "
                    "concurrency check for %r. %s",
                    name, _MIGRATION_HINT,
                )
                self._require_client_exists(name)
                # No concurrency guard available; just confirm the row
                # exists and return 1 so the response surface stays
                # consistent.
                return 1
            raise
        if not result.data:
            # Distinguish "client missing" from "version stale" so the
            # 409 response body can include the live value.
            current = self.get_client_version(name)  # raises ValueError if gone
            raise ConcurrentEditError(
                f"Client {name!r} has been modified by another request "
                f"(expected version {expected}, currently {current}). "
                "Refresh and retry.",
                current_version=current,
            )
        return new_version

    # ---- validation --------------------------------------------------------

    def validate(self):
        """Validate configuration consistency. Raises ValueError on problems."""
        all_slots_set = set(BASE_SLOTS) | set(CONST_SLOTS)
        rows = (
            self._sb.table('clients')
            .select(_CLIENT_COLUMNS)
            .execute()
        )
        for row in rows.data or []:
            client_name = row.get('name', '<unnamed>')
            raw_counters = _as_json(row.get('counters'), []) or []
            if isinstance(raw_counters, dict):
                raw_counters = [raw_counters]
            if not raw_counters:
                raise ValueError(
                    f"Client '{client_name}' has no counters configured."
                )
            seen_names: Set[str] = set()
            for idx, entry in enumerate(raw_counters, start=1):
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"Client '{client_name}' counter #{idx} is not an "
                        f"object: {entry!r}"
                    )
                cname = str(entry.get('name') or f'Counter {idx}').strip()
                key = cname.lower()
                if key in seen_names:
                    raise ValueError(
                        f"Client '{client_name}' has duplicate counter name: "
                        f"{cname!r}"
                    )
                seen_names.add(key)

                categories = entry.get('categories') or []
                if not isinstance(categories, (list, tuple)) or not categories:
                    raise ValueError(
                        f"Client '{client_name}' counter '{cname}' has no "
                        f"categories."
                    )
                bad = [
                    s for s in categories
                    if str(s).strip().lower() not in all_slots_set
                ]
                if bad:
                    raise ValueError(
                        f"Client '{client_name}' counter '{cname}' has unknown "
                        f"slot(s): {bad}"
                    )

                counts = entry.get('slot_counts') or {}
                if not isinstance(counts, dict):
                    raise ValueError(
                        f"Client '{client_name}' counter '{cname}' has a "
                        f"non-object slot_counts."
                    )
                for slot, count in counts.items():
                    if str(slot).strip().lower() not in all_slots_set:
                        raise ValueError(
                            f"Client '{client_name}' counter '{cname}' has a "
                            f"count for unknown slot: {slot}"
                        )
                    try:
                        if int(count) < 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"Client '{client_name}' counter '{cname}' has an "
                            f"invalid count for {slot}: {count!r}"
                        ) from None

                themes = entry.get('theme_map') or {}
                if not isinstance(themes, dict):
                    raise ValueError(
                        f"Client '{client_name}' counter '{cname}' has a "
                        f"non-object theme_map."
                    )
                for day, theme in themes.items():
                    if str(day).strip().lower() not in ALL_DAY_NAMES:
                        raise ValueError(
                            f"Client '{client_name}' counter '{cname}' has an "
                            f"invalid day: {day}"
                        )
                    if str(theme).strip().lower() not in AVAILABLE_THEMES:
                        raise ValueError(
                            f"Client '{client_name}' counter '{cname}' has an "
                            f"invalid theme: {theme}"
                        )
