"""
Flask API Application for Menu Planning System.

Endpoints:
  POST /api/v1/plan — Generate a menu plan for a client
  POST /api/v1/estimate-plan — Generate a plan for a prospective client
        described inline (Cost Estimator); never touches the database
  POST /api/v1/regenerate — Regenerate selected cells
  POST /api/v1/estimate-regenerate — Regenerate cells of an estimate
  POST /api/v1/save — Save plan to history
  GET  /api/v1/clients — List available clients
  GET  /api/v1/health — Health check
"""

import datetime as dt
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from flask import Flask, request, jsonify, g, has_request_context
from flask_cors import CORS

from api.concurrency import solver_slot, get_stats as _solver_stats
from api.rate_limit import rate_limit
from api import metrics

from api.config import (
    DEFAULT_EXCEL_PATH, DEFAULT_PRICE_LIST_PATH, MENU_RULES_CONFIG_PATH,
    API_HOST, API_PORT, DEBUG, APP_VERSION,
    MIN_NUM_DAYS, MAX_NUM_DAYS, MIN_TIME_LIMIT_SECONDS, MAX_TIME_LIMIT_SECONDS,
    validate_required_env, today_in_app_tz,
)
from api.logging_config import (
    configure_logging,
    new_request_id,
    request_id_var,
)

# Install the logging config before anything else logs. Idempotent, so
# callers that also import us (Streamlit entry, tests) don't double-up.
configure_logging()

# Fail fast if required secrets / URLs are unset. The alternative is an
# opaque KeyError or Supabase auth error on the first request — which
# happens in production long after the process looked healthy.
validate_required_env()
from src.preprocessor import apply_price_list, ExcelReader, DataCleanser
from src.preprocessor.pool_builder import PoolBuilder, _base_slot
import pandas as pd

from src.constants import (
    ALL_DAY_NAMES, BASE_SLOT_NAMES, CONST_SLOTS, CONSTANT_ITEMS,
    DEFAULT_COUNTER_NAME, DEFAULT_COUNTER_SLOTS, plate_cap_grams,
    DEFAULT_ITEM_COOLDOWN_DAYS, REPEATABLE_ITEM_BASES, REQUIRED_POOL_SLOTS,
    WEEKDAY_NAMES,
)
# UnknownCounterError is a ValueError subclass, so the existing 400/404
# handlers pick it up without a dedicated except branch.
from src.client import build_adhoc_client_config, ClientConfigLoader
from src.client.client_config import DEFAULT_THEME_MAP, AVAILABLE_THEMES  # noqa: F401 — surfaced in editor-metadata response
from src.history import HistoryManager
from src.menu_rules import MenuRuleLoader
from src.menu_rules import (
    DiagnoseContext,
    run_diagnostics,
    summarize as _summarize_diags,
    has_blocking_errors,
    pool_warnings_projection,
)
from src.solver.menu_solver import MenuSolver, SolverConfig
from src.solver._helpers import (
    weekday_type_for_config as _weekday_type_cfg,
    strip_color_suffix,
    items_from_day as _items_from_day,
)
from src.solver.solution_formatter import SolutionFormatter
from src.solver.regenerator import MenuRegenerator

logger = logging.getLogger(__name__)

# Generic message returned to clients when the server hits an unexpected
# error. The real exception is logged server-side with exc_info; we must not
# echo exception details back to the caller, since Supabase errors and
# similar can reveal connection strings, internal hostnames, or schema info.
_INTERNAL_ERROR_MSG = "Internal server error"


def _internal_error_response(status: int = 500):
    """Return a generic-error JSON response with the current request_id.

    The body never carries exception details (security), but it does
    surface the request_id so an admin debugging "Internal server error"
    in the UI can grep that id in the access log and find the real
    traceback. Fix for the recurring "I see Internal server error and
    have no way to triage" pain.
    """
    rid = getattr(g, 'request_id', None) if has_request_context() else None
    body = {'success': False, 'error': _INTERNAL_ERROR_MSG}
    if rid:
        body['request_id'] = rid
    return jsonify(body), status

# Record when the process started so /health can report uptime. Used
# for liveness / deploy-tracking rather than anything load-bearing.
_STARTED_AT = time.time()

app = Flask(__name__)

# CORS: default to loopback-only (the Streamlit frontend calls the API
# server-side via `requests`, so no browser origin needs access). Set
# CORS_ALLOWED_ORIGINS="https://prod.example.com,https://staging.example.com"
# to permit additional origins in production.
_cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
CORS(app, origins=_cors_origins)


# ---------------------------------------------------------------------------
# Request tracing — one access log line per request with timing + user.
# ---------------------------------------------------------------------------

@app.before_request
def _trace_request_start() -> None:
    # Prefer a caller-supplied X-Request-ID so traces can be correlated
    # across services; otherwise mint our own.
    rid = request.headers.get("X-Request-ID", "").strip() or new_request_id()
    g.request_id = rid
    # Every request's before_request overwrites the ContextVar, so
    # thread-pool reuse can't leak an id from the previous request.
    request_id_var.set(rid)
    g._t0 = time.perf_counter()


@app.after_request
def _trace_request_end(response):
    t0 = getattr(g, "_t0", None)
    duration_ms = (
        int((time.perf_counter() - t0) * 1000) if t0 is not None else None
    )
    rid = getattr(g, "request_id", "-")
    response.headers["X-Request-ID"] = rid

    user_email = None

    # /health gets spammy fast — skip its access log unless it errored.
    if request.path == "/api/v1/health" and response.status_code < 400:
        return response

    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "user": user_email,
            "remote_addr": request.remote_addr,
        },
    )
    return response


@app.teardown_request
def _trace_request_teardown(_exc):
    # Return the ContextVar to its sentinel so log records emitted
    # after this request finishes (e.g. background cleanup, the next
    # test in a pytest session) don't inherit a stale request id.
    # Using set() rather than reset() because tokens are single-use
    # and the after_request path may have already released it.
    request_id_var.set("-")


# Thread-safe lazy singletons
_init_lock = threading.Lock()
_client_loader = None
_pools = None
_df = None
_menu_rules = None
_cost_lookup = None


def _get_client_loader():
    global _client_loader
    if _client_loader is None:
        with _init_lock:
            if _client_loader is None:
                _client_loader = ClientConfigLoader()
    return _client_loader


def _get_menu_data(source_pools=None):
    """Return ``(df, pools)`` for the ontology, scoped to *source_pools*.

    The cleansed DataFrame is process-wide (it's the whole ontology), but
    pools are built per distinct ``clients.source_pools`` set because
    scoping happens before slot mapping. Clients that declare no source
    pools — the common case — all share the ``()`` entry, so this stays a
    single build for most deployments.
    """
    global _pools, _df
    key = tuple(sorted({str(p).strip().lower() for p in (source_pools or []) if str(p).strip()}))
    if _pools is None or key not in _pools:
        with _init_lock:
            if _df is None:
                reader = ExcelReader(DEFAULT_EXCEL_PATH)
                raw_df = reader.read()
                # Costs come from the Menu List workbook, not the
                # ontology's cached formula results. Applied before the
                # cleanser so its per-course serving-weight corrections
                # have the final say.
                priced_df = apply_price_list(raw_df, DEFAULT_PRICE_LIST_PATH)
                cleanser = DataCleanser(priced_df)
                _df = cleanser.clean()
            if _pools is None:
                _pools = {}
            if key not in _pools:
                _pools[key] = PoolBuilder.build_pools(_df, source_pools=key)
    return _df, _pools[key]


def _get_menu_rules():
    global _menu_rules
    if _menu_rules is None:
        with _init_lock:
            if _menu_rules is None:
                loader = MenuRuleLoader(MENU_RULES_CONFIG_PATH)
                _menu_rules = loader.load_from_file()
    return _menu_rules


def _get_cost_lookup():
    global _cost_lookup
    if _cost_lookup is None:
        with _init_lock:
            if _cost_lookup is None:
                from src.cost.calculator import build_cost_lookup
                df, _ = _get_menu_data()
                _cost_lookup = build_cost_lookup(df)
    return _cost_lookup


def _rules_and_skip_for_client(client_name, dates, item_cooldown_days=None):
    """Return (rules, skip_cells) for a client, merging generic + per-client.

    *item_cooldown_days* comes from ``clients.item_cooldown_days`` and
    overrides whatever the generic rule config declares, so the number an
    admin set on the client is the number the diagnostics report and the
    history window is sized from. Passing ``None`` leaves the configured
    value alone.
    """
    generic = _get_menu_rules()
    loader = MenuRuleLoader()
    rules = loader.load_for_client(client_name, generic)
    if item_cooldown_days is not None:
        for rule in rules:
            if getattr(rule, 'rule_type', None) is not None and hasattr(
                rule, 'cooldown_days',
            ) and rule.rule_type.value == 'item_cooldown':
                rule.cooldown_days = int(item_cooldown_days)
    skip_cells = set()
    for rule in rules:
        if hasattr(rule, 'compute_skip_cells'):
            skip_cells |= rule.compute_skip_cells(dates)
    return rules, skip_cells


# Floor lookback. Must cover every history-consuming rule's cooldown.
# With the default rules (week-signature 30d, item cooldown 20d,
# rice-bread gap 10d), 45d gives 15d of slack. For per-client overrides
# that push cooldowns past this floor, _effective_history_window()
# widens the window at runtime instead of silently cutting off data.
_HISTORY_WINDOW_DAYS = 45
_HISTORY_WINDOW_SLACK_DAYS = 15


def _effective_history_window(rules) -> int:
    """Return a window that covers every rule's cooldown + slack.

    Rules expose their cooldown via either ``cooldown_days`` (item /
    week-signature cooldowns) or ``gap_days`` (rice-bread gap). We take
    the max across both attributes on all rules, add slack, and take the
    larger of that and the ``_HISTORY_WINDOW_DAYS`` floor. Widening is
    logged so operators notice a per-client rule is pushing queries
    further back than usual.

    Skipping this check is how "we quietly miss the last 10 days of
    history" bugs happen: ``_HISTORY_WINDOW_DAYS`` is a fixed constant,
    but cooldowns can be overridden per-client or in future rules.
    """
    max_cd = 0
    for r in rules or []:
        for attr in ('cooldown_days', 'gap_days'):
            value = getattr(r, attr, None)
            if isinstance(value, int) and value > max_cd:
                max_cd = value
    effective = max(_HISTORY_WINDOW_DAYS, max_cd + _HISTORY_WINDOW_SLACK_DAYS)
    if effective > _HISTORY_WINDOW_DAYS:
        logger.warning(
            "Widening history lookback from %d to %d days to cover "
            "max rule cooldown %d + %d slack",
            _HISTORY_WINDOW_DAYS, effective, max_cd, _HISTORY_WINDOW_SLACK_DAYS,
        )
    return effective


def _build_history_context(
    df, client_name, start_date, weekday_dates, window_days=None,
    counter_name=None, cooldown_days=DEFAULT_ITEM_COOLDOWN_DAYS,
):
    """Shared helper to build history-based solver inputs from Supabase.

    Pushes ``client_name`` and ``service_date >= cutoff`` filters down to
    Supabase so the query hits the ``(client_name, service_date DESC)``
    index on ``menu_history`` (and the analogous index on
    ``week_signatures``) instead of scanning every row for every tenant.

    *window_days* is the backward-lookback in days. Callers should pass
    ``_effective_history_window(rules)`` so per-client rule overrides
    don't silently truncate the window. Falling back to the floor
    keeps the function usable in tests / scripts that don't assemble
    rules upfront.

    *counter_name* scopes history to one serving line (see
    ``HistoryManager.filter_by_counter``); *cooldown_days* is the client's
    ``item_cooldown_days``.
    """
    from src.db import get_supabase

    if window_days is None:
        window_days = _HISTORY_WINDOW_DAYS
    earliest = start_date - dt.timedelta(days=window_days)
    earliest_iso = earliest.isoformat()

    hm = HistoryManager()
    sb = get_supabase()
    long_resp = (
        sb.table('menu_history')
        .select('client_name, service_date, menu')
        .eq('client_name', client_name)
        .gte('service_date', earliest_iso)
        .execute()
    )
    weeks_resp = (
        sb.table('week_signatures')
        .select('*')
        .eq('client_name', client_name)
        .gte('week_start', earliest_iso)
        .execute()
    )
    hm.load_from_menu_rows(long_resp.data or [], weeks_resp.data or [])
    # Rows are already scoped to this client at the DB layer, but leave
    # the in-memory filter in place as belt-and-suspenders for anyone
    # who seeds the manager from an unfiltered DataFrame.
    hm = hm.filter_by_client(client_name)
    if counter_name:
        hm = hm.filter_by_counter(counter_name)

    banned = hm.banned_items_by_date(
        weekday_dates,
        cooldown_days=int(cooldown_days),
        const_slots=CONST_SLOTS,
        repeatable_items=REPEATABLE_ITEM_BASES,
    )
    ricebread_items = set(
        df.loc[df.get('is_rice_bread', 0) == 1, 'item'].tolist()
    ) if 'is_rice_bread' in df.columns else set()
    rb_ban = hm.ricebread_ban_by_date(weekday_dates, ricebread_items)
    recent_sigs = hm.recent_week_signatures(start_date)
    return banned, rb_ban, recent_sigs


def _cached_on_g(key: str, compute):
    """Memoize ``compute()`` on Flask's ``g`` for the current request.

    ClientConfigLoader properties read Supabase on every access (no
    in-process cache, so admin edits are picked up immediately). Some of
    them — client_names, and a client's counters — end up fetched multiple
    times per request: once from _require_known_client, once for the
    solver config, once for the response's theme labels. Caching on ``g``
    keeps the "live reads across requests" guarantee while collapsing the
    intra-request round trips.

    Outside a request context (module-import paths, bare scripts) there
    is no ``g`` to hang on to, so we just call compute() uncached.
    """
    if not has_request_context():
        return compute()
    cache = getattr(g, '_clientcfg_cache', None)
    if cache is None:
        cache = {}
        g._clientcfg_cache = cache
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def _request_client_names():
    return _cached_on_g(
        'client_names',
        lambda: _get_client_loader().client_names,
    )


def _request_client_config(client_name, counter_name=None):
    """Load one client+counter config, memoized for this request.

    ``/plan`` reads the config for the solver, the diagnostics context,
    and the response's theme labels; without this the same client row is
    fetched three times per request.
    """
    return _cached_on_g(
        f'client_config::{client_name}::{counter_name or ""}',
        lambda: _get_client_loader().get_client(client_name, counter_name),
    )


def _count_rule_failures(failures) -> None:
    """Bump ``rule_failures_total{rule=<name>}`` for every failure the
    solver recorded on this request. Keeps the metrics surface aligned
    with the response's ``rule_warnings`` payload so a Prometheus alert
    on rule_failures_total doesn't disagree with what the client saw.
    """
    if not failures:
        return
    for entry in failures:
        rule_name = entry.get('rule', 'unknown') if isinstance(entry, dict) else 'unknown'
        metrics.incr('rule_failures_total', rule=rule_name)


def _require_known_client(client_name):
    """Validate ``client_name`` is non-empty and refers to a known client.

    Raises ``ValueError`` with a user-safe message so the caller's 400
    handler picks it up. Keeps invalid input from reaching solver setup
    or Supabase config reads, where it would surface as a less-clear
    error deep in the stack.
    """
    if not client_name or not isinstance(client_name, str):
        raise ValueError('client_name is required')
    if client_name not in _request_client_names():
        raise ValueError(f"Unknown client: {client_name}")


def _weekdays_from(start_date, num_days, serve_weekends=False):
    """Return up to num_days service dates starting from start_date.

    Sat/Sun are skipped unless the client has ``serve_weekends = true``,
    in which case every consecutive day counts — a 7-day request for a
    weekend-serving site covers a full calendar week rather than stretching
    across nine days to find five weekdays.
    """
    dates = []
    d = start_date
    while len(dates) < num_days:
        if serve_weekends or d.weekday() < 5:  # Mon-Fri unless weekends served
            dates.append(d)
        d += dt.timedelta(days=1)
    return dates


def _client_base_slots(client_cfg):
    """Return unique base slot names the client uses (excluding constants).

    Handles expanded slot IDs like veg_dry__1, veg_dry__2 by extracting
    the base name so the solver gets ['veg_dry'] not ['veg_dry__1', 'veg_dry__2'].
    """
    seen = set()
    result = []
    for s in client_cfg.active_slots:
        if s in CONST_SLOTS:
            continue
        base = _base_slot(s)
        if base not in seen:
            seen.add(base)
            result.append(base)
    return result


def _const_slot_count(client_cfg) -> int:
    """How many constant slots this counter serves."""
    return sum(1 for s in client_cfg.active_slots if s in CONST_SLOTS)


def _const_slot_grams(df, client_cfg) -> int:
    """Serving weight (grams) of the constant slots this counter serves.

    The solver never models them — papad, pickle and friends are stamped
    onto every day after the solve — but they are on the plate, so the
    plate-weight cap has to know about them. Items the ontology has no
    weight for contribute nothing.
    """
    if 'grammage_per_serving' not in df.columns or 'item' not in df.columns:
        return 0
    served = {s for s in client_cfg.active_slots if s in CONST_SLOTS}
    if not served:
        return 0
    wanted = {
        str(CONSTANT_ITEMS[slot]).strip().lower()
        for slot in served if slot in CONSTANT_ITEMS
    }
    if not wanted:
        return 0
    rows = df[df['item'].astype(str).str.strip().str.lower().isin(wanted)]
    grams = pd.to_numeric(rows['grammage_per_serving'], errors='coerce').fillna(0) * 1000
    return int(round(float(grams.sum())))


def _build_solver_config(df, client_cfg, start_date, num_days, time_limit, weekday_dates):
    """Shared helper to build SolverConfig."""
    active_base = _client_base_slots(client_cfg)
    return SolverConfig(
        days=num_days,
        start_date=start_date,
        time_limit_sec=time_limit,
        slot_counts=client_cfg.slot_counts,
        active_base_slots=active_base or None,
        explicit_dates=weekday_dates,
        premium_flag_col='is_premium_veg' if 'is_premium_veg' in df.columns and int(df['is_premium_veg'].sum()) > 0 else None,
        theme_map=client_cfg.theme_map or None,
        const_slot_grams=_const_slot_grams(df, client_cfg),
        const_slot_count=_const_slot_count(client_cfg),
    )


@dataclass
class SolverInputs:
    """Bundle of everything MenuSolver / MenuRegenerator need for one request."""
    client_name: str
    client_cfg: Any
    df: Any
    pools: Dict[str, Any]
    start_date: dt.date
    num_days: int
    time_limit: int
    weekday_dates: List[dt.date]
    rules: List[Any]
    skip_cells: Set[Any]
    banned: Dict[Any, Any]
    rb_ban: Dict[Any, Any]
    recent_sigs: List[Any]
    cfg: SolverConfig
    counter_name: str = ''


def _requested_counter(data: Dict[str, Any]) -> Optional[str]:
    """Return the ``counter`` the caller asked for, or None for the default.

    Accepts ``counter`` or ``counter_name`` so the query-string and JSON
    surfaces can use whichever reads better.
    """
    for key in ('counter', 'counter_name'):
        value = data.get(key)
        if value:
            return str(value).strip()
    return None


def _prepare_solver_inputs(data: Dict[str, Any]) -> SolverInputs:
    """Parse request body and assemble all inputs the solver/regenerator need.

    Raises ``ValueError`` with a user-facing message on missing/invalid input.
    """
    client_name = data.get('client_name')
    _require_known_client(client_name)

    client_cfg = _request_client_config(client_name, _requested_counter(data))
    df, pools = _get_menu_data(client_cfg.source_pools)
    start_date, num_days, time_limit = _parse_plan_window(data)
    weekday_dates = _weekdays_from(
        start_date, num_days, serve_weekends=client_cfg.serve_weekends,
    )
    rules, skip_cells = _rules_and_skip_for_client(
        client_name, weekday_dates,
        item_cooldown_days=client_cfg.item_cooldown_days,
    )
    window_days = _effective_history_window(rules)
    banned, rb_ban, recent_sigs = _build_history_context(
        df, client_name, start_date, weekday_dates, window_days=window_days,
        counter_name=client_cfg.counter_name,
        cooldown_days=client_cfg.item_cooldown_days,
    )
    cfg = _build_solver_config(df, client_cfg, start_date, num_days, time_limit, weekday_dates)

    return SolverInputs(
        client_name=client_name,
        client_cfg=client_cfg,
        df=df,
        pools=pools,
        start_date=start_date,
        num_days=num_days,
        time_limit=time_limit,
        weekday_dates=weekday_dates,
        rules=rules,
        skip_cells=skip_cells,
        banned=banned,
        rb_ban=rb_ban,
        recent_sigs=recent_sigs,
        cfg=cfg,
        counter_name=client_cfg.counter_name,
    )


def _parse_plan_window(data: Dict[str, Any]):
    """Return ``(start_date, num_days, time_limit)`` clamped to the API's
    limits. Shared by the stored-client and estimator request paths so both
    honour the same MIN/MAX bounds and the same timezone default."""
    num_days = max(MIN_NUM_DAYS, min(MAX_NUM_DAYS, int(data.get('num_days', 5))))
    time_limit = max(
        MIN_TIME_LIMIT_SECONDS,
        min(MAX_TIME_LIMIT_SECONDS, int(data.get('time_limit_seconds', 240))),
    )
    start_date_str = data.get('start_date')
    start_date = (
        dt.date.fromisoformat(start_date_str) if start_date_str
        else today_in_app_tz()
    )
    return start_date, num_days, time_limit


def _prepare_estimate_inputs(data: Dict[str, Any]) -> SolverInputs:
    """Assemble solver inputs for the **Cost Estimator** — a prospective
    client described inline, with no ``clients`` row and no history.

    Differences from :func:`_prepare_solver_inputs`, all deliberate:

    * The menu shape comes from the request body (``categories``,
      ``slot_counts``, ``theme_map``) via
      :func:`build_adhoc_client_config`, so nothing is read from — or
      written to — Supabase. An estimate for a client that doesn't exist
      yet must not leave a row behind.
    * History is empty: there is no served history for a prospective
      client, so the item-cooldown, rice-bread-gap and week-signature
      rules have nothing to ban. They stay in the rule list (harmless
      no-ops) rather than being filtered out, so the estimate runs through
      exactly the same rule pipeline a real plan does.
    * Per-client rules from ``client_rules.json`` are **not** applied: the
      name is free text an operator just typed, and matching it against
      the file would silently apply another client's bans to an unrelated
      estimate.

    Raises ``ValueError`` with a user-facing message on invalid input.
    """
    client_cfg = build_adhoc_client_config(
        data.get('client_name'),
        data.get('categories'),
        data.get('slot_counts'),
        data.get('theme_map'),
        serve_weekends=bool(data.get('serve_weekends')),
        source_pools=data.get('source_pools'),
    )
    df, pools = _get_menu_data(client_cfg.source_pools)
    start_date, num_days, time_limit = _parse_plan_window(data)
    weekday_dates = _weekdays_from(
        start_date, num_days, serve_weekends=client_cfg.serve_weekends,
    )
    # Generic rules only, and the shared list is passed through untouched
    # (no cooldown override) so concurrent requests can't see each other's
    # edits to these process-wide rule objects.
    rules = list(_get_menu_rules())
    skip_cells = set()
    for rule in rules:
        if hasattr(rule, 'compute_skip_cells'):
            skip_cells |= rule.compute_skip_cells(weekday_dates)
    cfg = _build_solver_config(
        df, client_cfg, start_date, num_days, time_limit, weekday_dates,
    )

    return SolverInputs(
        client_name=client_cfg.name,
        client_cfg=client_cfg,
        df=df,
        pools=pools,
        start_date=start_date,
        num_days=num_days,
        time_limit=time_limit,
        weekday_dates=weekday_dates,
        rules=rules,
        skip_cells=skip_cells,
        banned={},
        rb_ban={},
        recent_sigs=set(),
        cfg=cfg,
        counter_name=client_cfg.counter_name,
    )


def _build_diagnose_context(inputs: SolverInputs) -> DiagnoseContext:
    """Project the SolverInputs bundle into a DiagnoseContext the
    rule diagnose() methods can consume.

    Computes the per-date day_types map up front (the rules want
    O(1) lookup, not repeated weekday_type_for_config calls), and
    surfaces the client's active base slots so diagnose() iterates
    over the slots that will actually be solved (not the global
    BASE_SLOT_NAMES list).
    """
    day_types = {
        d: _weekday_type_cfg(d, inputs.cfg.theme_map)
        for d in inputs.weekday_dates
    }
    active_base = inputs.cfg.active_base_slots
    return DiagnoseContext(
        pools=inputs.pools,
        dates=inputs.weekday_dates,
        day_types=day_types,
        cfg=inputs.cfg,
        df=inputs.df,
        banned_by_date=inputs.banned,
        ricebread_ban_day=inputs.rb_ban,
        skip_cells=inputs.skip_cells,
        client_cfg=inputs.client_cfg,
        active_base_slots=active_base,
        rules=list(inputs.rules),
    )


def _run_preflight(inputs: SolverInputs):
    """Shared pre-flight pass used by both /plan and /diagnose.

    Returns ``(diagnostics, summary)`` where:
      - ``diagnostics`` is the full sorted list of Diagnostic objects
        produced by every rule + the synthetic pool_size pass.
      - ``summary`` is the ``{errors, warnings, infos, would_succeed}``
        dict produced by ``summarize()``.

    A single call site for both endpoints keeps the two surfaces in
    lockstep: /diagnose and /plan's gate emit identical diagnostics
    for identical inputs. ``test_diagnose_matches_plan_preflight``
    pins this invariant.
    """
    ctx = _build_diagnose_context(inputs)
    diags = run_diagnostics(inputs.rules, ctx)
    return diags, _summarize_diags(diags)


def _record_diag_metrics(diagnostics) -> None:
    """Bump ``rule_diagnostics_total{rule=<name>,severity=<sev>}`` once
    per emitted Diagnostic. Mirrors ``_count_rule_failures`` so a
    Prometheus alert can fire on either surface symmetrically.
    """
    for d in diagnostics:
        metrics.incr(
            'rule_diagnostics_total',
            rule=d.rule,
            severity=d.severity.value,
        )


@app.route('/api/v1/clients', methods=['GET'])
def list_clients():
    try:
        return jsonify({'success': True, 'clients': _request_client_names()})
    except (FileNotFoundError, ValueError, KeyError) as e:
        logger.error("Failed to list clients: %s", e, exc_info=True)
        return _internal_error_response(500)


def _plan_pipeline(inputs: SolverInputs, extra: Optional[Dict[str, Any]] = None):
    """Pre-flight gate → solver → cost enrichment → response body.

    Shared by ``/plan`` and ``/estimate-plan``: both run the identical
    diagnostics, admission control, solve and costing steps, and differ
    only in how their ``SolverInputs`` was assembled (stored client vs.
    inline estimator config) and in the ``extra`` keys merged into the
    response. Returns a ``(body, status)`` tuple, or raises for the
    caller's error handler.
    """
    # Pre-flight gate: run every rule's diagnose() against the
    # assembled inputs. If any diagnostic is severity=error, the
    # solver would (with overwhelming probability) fail — so we
    # short-circuit with 422 and the structured diagnostics
    # before spending solver budget.
    diagnostics, summary = _run_preflight(inputs)
    _record_diag_metrics(diagnostics)
    diag_dicts = [d.to_dict() for d in diagnostics]
    # Denormalised pool_warnings projection kept for one release so
    # older Streamlit builds that still read this key keep rendering
    # something. New code consumes ``rule_diagnostics``.
    pool_warnings = pool_warnings_projection(diagnostics)

    if has_blocking_errors(diagnostics):
        body = {
            'success': False,
            'error': 'rule_diagnostics_blocked',
            'message': (
                f"Pre-flight diagnostics found "
                f"{summary['errors']} blocking issue"
                f"{'s' if summary['errors'] != 1 else ''} for "
                f"{inputs.client_name}; solver skipped."
            ),
            'rule_diagnostics': diag_dicts,
            'summary': summary,
        }
        if pool_warnings:
            body['pool_warnings'] = pool_warnings
        return body, 422

    # Weighted admission control — sized by plan length so short plans
    # don't queue behind heavy ones.
    with solver_slot(inputs.cfg.days) as admitted:
        if not admitted:
            return {
                'success': False,
                'error': 'Solver busy — too many concurrent requests. Retry shortly.',
            }, 503

        solver = MenuSolver(
            pools=inputs.pools,
            solver_config=inputs.cfg,
            menu_rules=inputs.rules,
            banned_by_date=inputs.banned,
            ricebread_ban_day=inputs.rb_ban,
            recent_sigs=inputs.recent_sigs,
            skip_cells=inputs.skip_cells,
        )

        week_plan, plan_dates = solver.solve()

    response = {
        'success': True,
        'message': (
            f'Menu plan generated for {inputs.client_name} '
            f'({inputs.counter_name})'
        ),
        'solution': _format_and_cost(inputs, week_plan, plan_dates),
        'counter': inputs.counter_name,
        'counters': inputs.client_cfg.counter_names,
        'rule_diagnostics': diag_dicts,
        'summary': summary,
    }
    if pool_warnings:
        response['pool_warnings'] = pool_warnings
    if solver.rule_failures:
        response['rule_warnings'] = solver.rule_failures
        _count_rule_failures(solver.rule_failures)
    if extra:
        response.update(extra)
    return response, 200


def _format_and_cost(inputs: SolverInputs, week_plan, plan_dates) -> Dict[str, Any]:
    """Format a solved week, then cost it against the plate it will serve.

    The plate-weight cap is applied here as well as in the solver: days
    the solver could fit under the cap are already within it, and days it
    could not have their portions trimmed now — before costs are
    computed, so the money reflects the food actually served.
    """
    from src.cost.calculator import enrich_solution_with_costs

    formatter = SolutionFormatter(
        week_plan, plan_dates, theme_map=inputs.client_cfg.theme_map or None,
    )
    return enrich_solution_with_costs(
        formatter.to_dict(), _get_cost_lookup(), cap_fn=plate_cap_grams,
    )


def _plan_endpoint(prepare, *, metric: str,
                   extra: Optional[Dict[str, Any]] = None):
    """Run a plan request end to end with the shared error contract.

    *prepare* is a zero-arg callable returning ``SolverInputs`` — that's
    the only difference between the stored-client and estimator surfaces.
    *metric* names the ``…_requests_total`` counter to label with the
    outcome, so /plan and /estimate-plan stay separately observable.
    """
    try:
        inputs = prepare()
        body, status = _plan_pipeline(inputs, extra)
        if status == 422:
            metrics.incr(metric, outcome='preflight_blocked')
        elif status == 200:
            metrics.incr(metric, outcome='success')
        return jsonify(body), status
    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Solver failed: %s", e)
        # Counts infeasibility + exhausted-restarts from the CP-SAT path;
        # this is the SLO-relevant failure mode (vs 4xx, which is caller
        # input error).
        metrics.incr(metric, outcome='solver_error')
        metrics.incr('solver_failures_total')
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return _internal_error_response(500)
    except Exception as e:
        logger.error("Unexpected error in plan: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/plan', methods=['POST'])
@rate_limit("plan")
def plan_menu():
    return _plan_endpoint(
        lambda: _prepare_solver_inputs(request.get_json() or {}),
        metric='plan_requests_total',
    )


@app.route('/api/v1/estimate-plan', methods=['POST'])
@rate_limit("plan")
def estimate_plan():
    """Generate a plan for a **prospective** client described inline.

    Same body as /plan except the client's menu shape is supplied
    directly instead of being read from the ``clients`` table::

        {
          "client_name":  "Acme Corp",        # a label, not a lookup key
          "categories":   ["rice", "bread", …],
          "slot_counts":  {"veg_dry": 2},     # optional, default 1 each
          "theme_map":    {"monday": "south"},# optional, defaults per day
          "serve_weekends": false,            # optional
          "start_date": "2026-09-01", "num_days": 5
        }

    Nothing is read from or written to the ``clients`` / ``menu_history``
    tables, so an estimate can't create a half-configured client or
    consume another client's cooldown history. The response mirrors /plan
    (``solution`` carries the same cost enrichment the costing panel
    reads) plus ``"estimate": true``.

    Shares the ``plan`` rate-limit bucket with /plan on purpose: both
    spend the same solver budget, so they should throttle together.
    """
    return _plan_endpoint(
        lambda: _prepare_estimate_inputs(request.get_json() or {}),
        metric='estimate_requests_total',
        extra={'estimate': True},
    )


def _regenerate_pipeline(inputs: SolverInputs, data: Dict[str, Any],
                         extra: Optional[Dict[str, Any]] = None):
    """Lock every unselected cell and re-solve the selected ones.

    Shared by ``/regenerate`` and ``/estimate-regenerate``; see
    :func:`_plan_pipeline` for why the two surfaces only differ in how
    their inputs were assembled.
    """
    base_plan = {
        dt.date.fromisoformat(d_str): _items_from_day(slots)
        for d_str, slots in (data.get('base_plan') or {}).items()
    }
    replace_mask = {
        dt.date.fromisoformat(d_str): set(slot_list)
        for d_str, slot_list in (data.get('replace_slots') or {}).items()
    }

    with solver_slot(inputs.cfg.days) as admitted:
        if not admitted:
            return {
                'success': False,
                'error': 'Solver busy — too many concurrent requests. Retry shortly.',
            }, 503

        regen = MenuRegenerator(
            pools=inputs.pools,
            df=inputs.df,
            solver_config=inputs.cfg,
            menu_rules=inputs.rules,
            banned_by_date=inputs.banned,
            ricebread_ban_day=inputs.rb_ban,
            recent_sigs=inputs.recent_sigs,
            skip_cells=inputs.skip_cells,
        )

        week_plan, plan_dates = regen.regenerate(base_plan, replace_mask)

    response = {
        'success': True,
        'message': (
            f'Regenerated {sum(len(v) for v in replace_mask.values())} '
            f'cells for {inputs.client_name} ({inputs.counter_name})'
        ),
        'solution': _format_and_cost(inputs, week_plan, plan_dates),
        'counter': inputs.counter_name,
    }
    if regen.rule_failures:
        response['rule_warnings'] = regen.rule_failures
        _count_rule_failures(regen.rule_failures)
    if extra:
        response.update(extra)
    return response, 200


def _regenerate_endpoint(prepare, *, metric: str,
                         extra: Optional[Dict[str, Any]] = None):
    """Run a regenerate request end to end with the shared error contract."""
    try:
        data = request.get_json() or {}
        if not data.get('base_plan'):
            return jsonify({'success': False, 'error': 'base_plan is required'}), 400
        if not data.get('replace_slots'):
            return jsonify({'success': False, 'error': 'replace_slots is required'}), 400

        body, status = _regenerate_pipeline(prepare(data), data, extra)
        if status == 200:
            metrics.incr(metric, outcome='success')
        return jsonify(body), status
    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except RuntimeError as e:
        logger.warning("Regeneration failed: %s", e)
        metrics.incr(metric, outcome='solver_error')
        metrics.incr('solver_failures_total')
        return jsonify({'success': False, 'error': str(e)}), 500
    except (FileNotFoundError, OSError) as e:
        logger.error("Data loading error: %s", e, exc_info=True)
        return _internal_error_response(500)
    except Exception as e:
        logger.error("Unexpected error in regenerate: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/regenerate', methods=['POST'])
@rate_limit("regenerate")
def regenerate_cells():
    return _regenerate_endpoint(
        _prepare_solver_inputs,
        metric='regenerate_requests_total',
    )


@app.route('/api/v1/estimate-regenerate', methods=['POST'])
@rate_limit("regenerate")
def estimate_regenerate():
    """Regenerate selected cells of a Cost Estimator plan.

    Body is /estimate-plan's plus ``base_plan`` and ``replace_slots``:
    the estimator config has to be re-sent because nothing about the
    prospective client is persisted server-side.
    """
    return _regenerate_endpoint(
        _prepare_estimate_inputs,
        metric='estimate_regenerate_requests_total',
        extra={'estimate': True},
    )


@app.route('/api/v1/save', methods=['POST'])
def save_plan():
    try:
        data = request.get_json(silent=True) or {}
        client_name = data.get('client_name')
        week_plan_raw = data.get('week_plan', {})
        week_start_str = data.get('week_start')

        _require_known_client(client_name)
        if not week_plan_raw:
            return jsonify({'success': False, 'error': 'week_plan is required'}), 400
        if not week_start_str:
            return jsonify({'success': False, 'error': 'week_start is required'}), 400

        # Resolve the counter through the loader so an unknown name is a
        # 400 rather than history written under a counter that doesn't
        # exist (which would then never load back).
        client_cfg = _request_client_config(
            client_name, _requested_counter(data),
        )

        # Convert string date keys to date objects, extracting items from solution format
        week_plan = {
            dt.date.fromisoformat(d_str): _items_from_day(day_data)
            for d_str, day_data in week_plan_raw.items()
        }

        dates = sorted(week_plan.keys())
        week_start = dt.date.fromisoformat(week_start_str)

        sig = HistoryManager.compute_week_signature(
            week_plan, dates, const_slots=CONST_SLOTS,
            strip_color_fn=strip_color_suffix,
        )

        hm = HistoryManager()
        # Get Supabase client for persistent storage
        from src.db import get_supabase
        sb = get_supabase()
        # HistoryManager.save is overwrite-on-conflict: re-saving for the
        # same (client, counter, dates) replaces the prior menu instead of
        # appending, and other counters' picks for those days are merged
        # through untouched. See HistoryManager.save docstring.
        hm.save(week_plan, dates, client_name, week_start, sig,
                supabase_client=sb,
                strip_color_fn=strip_color_suffix,
                counter_name=client_cfg.counter_name)

        return jsonify({
            'success': True,
            'message': (
                f'Plan saved to history for {client_cfg.counter_name}'
            ),
            'counter': client_cfg.counter_name,
        })

    except (ValueError, KeyError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except (FileNotFoundError, OSError) as e:
        logger.error("Save failed: %s", e, exc_info=True)
        return _internal_error_response(500)
    except Exception as e:
        logger.error("Unexpected save error: %s", e, exc_info=True)
        return _internal_error_response(500)


def _build_item_color_lookup(df) -> Dict[str, str]:
    """Return ``{normalised_item_name: color_initial_letter}``.

    Used by ``saved_plan`` to re-attach a color suffix to history rows.
    ``menu_history.item_base`` is stored without color (the cooldown
    rules are color-agnostic), but the UI's table renderer expects
    ``item(C)``-shaped strings — without this lookup, loaded plans show
    no color pills.

    Falls back gracefully: items not in *df* (admin-renamed, removed,
    legacy entries) round-trip without a color suffix instead of
    crashing.
    """
    from src.preprocessor.column_mapper import _norm_str, _norm_color

    out: Dict[str, str] = {}
    if df is None or 'item' not in df.columns:
        return out
    color_col = 'item_color' if 'item_color' in df.columns else None
    for _, row in df[['item'] + ([color_col] if color_col else [])].iterrows():
        name = _norm_str(row.get('item', ''))
        if not name:
            continue
        if color_col is None:
            out.setdefault(name, '')
            continue
        col = _norm_color(row.get(color_col, 'unknown'))
        if col == 'unknown' or '_' not in col:
            out.setdefault(name, '')
            continue
        # _norm_color returns shapes like "light_red", "medium_green";
        # the UI's display logic uses the last token's first letter
        # (matches src.solver.menu_solver._color_initial).
        base = col.split('_')[-1]
        out.setdefault(name, base[:1].upper() if base else '')
    return out


def _enrich_history_plan(
    saved: Dict[dt.date, Dict[str, str]], df,
) -> Dict[dt.date, Dict[str, str]]:
    """Turn ``{date: {slot: item_base}}`` (history shape) into
    ``{date: {slot: item_with_color}}`` (UI shape) by looking up each
    item's color in the loaded Excel *df* and appending ``(C)``.

    Constant slots (white_rice, papad, pickle, chutney) round-trip as-is
    since they never carried a color suffix in the first place. Items
    that no longer exist in the ontology fall through without a suffix
    — the UI handles missing-color gracefully (no color pill).
    """
    color_lookup = _build_item_color_lookup(df)
    out: Dict[dt.date, Dict[str, str]] = {}
    for d, slots in saved.items():
        day_out: Dict[str, str] = {}
        for slot_id, item_base in slots.items():
            if not item_base:
                continue
            if slot_id in CONST_SLOTS:
                day_out[slot_id] = item_base
                continue
            initial = color_lookup.get(item_base, '')
            day_out[slot_id] = f'{item_base}({initial})' if initial else item_base
        out[d] = day_out
    return out


@app.route('/api/v1/saved-plan', methods=['GET'])
def saved_plan():
    """Return the saved plan for a client + date range, if one exists.

    Query params:
        client_name (required): the client to look up.
        counter     (optional): which serving line; defaults to the
            client's first counter, mirroring /plan.
        start_date  (optional): YYYY-MM-DD; defaults to today in
            APP_TZ.
        num_days    (optional): number of service days from start_date;
            defaults to 5. Sat/Sun are skipped unless the client serves
            weekends, mirroring /plan.

    Response shape mirrors /plan so the UI can use one code path:
        {
          "success": True,
          "exists": <bool>,           # True iff every requested date
                                      # has at least one saved row.
          "covered_dates": [...],     # ISO date strings that DID have
                                      # saved rows (could be a strict
                                      # subset of the requested range).
          "source": "history",
          "solution": <SolutionFormatter.to_dict() output>,
        }

    When ``exists`` is False the ``solution`` only contains the days
    that were partially saved; the caller decides whether to fall back
    to /plan. We never call the solver from this endpoint — it's a
    pure read path.
    """
    try:
        client_name = request.args.get('client_name', '').strip()
        _require_known_client(client_name)

        start_date_str = request.args.get('start_date')
        num_days = max(
            MIN_NUM_DAYS,
            min(MAX_NUM_DAYS, int(request.args.get('num_days', 5))),
        )
        start_date = (
            dt.date.fromisoformat(start_date_str)
            if start_date_str else today_in_app_tz()
        )

        client_cfg = _request_client_config(
            client_name, _requested_counter(request.args),
        )
        weekday_dates = _weekdays_from(
            start_date, num_days, serve_weekends=client_cfg.serve_weekends,
        )

        from src.db import get_supabase
        sb = get_supabase()
        raw_saved = HistoryManager.load_saved_plan(
            sb, client_name, weekday_dates,
            counter_name=client_cfg.counter_name,
        )

        # Enrich with color suffix so the UI's renderer matches /plan.
        df, _pools = _get_menu_data(client_cfg.source_pools)
        enriched = _enrich_history_plan(raw_saved, df)

        formatter = SolutionFormatter(
            enriched, weekday_dates,
            theme_map=client_cfg.theme_map or None,
        )
        from src.cost.calculator import enrich_solution_with_costs
        solution = enrich_solution_with_costs(formatter.to_dict(), _get_cost_lookup())
        covered = sorted(d.isoformat() for d in enriched.keys())
        exists = len(enriched) == len(weekday_dates) and len(enriched) > 0

        return jsonify({
            'success': True,
            'exists': exists,
            'covered_dates': covered,
            'source': 'history',
            'solution': solution,
            'counter': client_cfg.counter_name,
            'counters': client_cfg.counter_names,
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to load saved plan: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/editor-metadata', methods=['GET'])
def editor_metadata():
    """Return metadata needed by the customisation editor UI.

    Everything except ``clients`` is derived from ``src.constants``, so
    the slot vocabulary and theme list are served even when Supabase is
    unreachable — the Cost Estimator only needs those, and it would be
    perverse for pricing a *prospective* client to fail because the
    existing-client list couldn't be read. A failed lookup logs and
    yields an empty ``clients`` list rather than a 500.
    """
    try:
        try:
            clients = _request_client_names()
        except Exception as e:  # noqa: BLE001 — degrade, don't fail the page
            logger.warning(
                "Editor metadata: client list unavailable (%s); "
                "serving the slot/theme vocabulary only.", e,
            )
            clients = []
        return jsonify({
            'success': True,
            'base_slot_names': list(BASE_SLOT_NAMES),
            'const_slots': list(CONST_SLOTS),
            # Slots the ontology must be able to fill for any client.
            'required_pool_slots': list(REQUIRED_POOL_SLOTS),
            # What a new counter starts from — a realistic client shape
            # that fits under the plate-weight cap, which the union of
            # every fillable slot does not.
            'default_counter_slots': list(DEFAULT_COUNTER_SLOTS),
            'default_theme_map': DEFAULT_THEME_MAP,
            'available_themes': AVAILABLE_THEMES,
            'weekday_names': list(WEEKDAY_NAMES),
            'all_day_names': list(ALL_DAY_NAMES),
            'clients': clients,
        })
    except Exception as e:
        logger.error("Failed to load editor metadata: %s", e, exc_info=True)
        return _internal_error_response(500)


def _counter_payload(counter) -> Dict[str, Any]:
    """Project a CounterConfig into the editor's JSON shape."""
    return {
        'name': counter.name,
        'active_base_slots': [
            s for s in counter.categories if s not in CONST_SLOTS
        ],
        'const_slots': [s for s in counter.categories if s in CONST_SLOTS],
        # Slots the counter doesn't serve are stored as 0; only surface
        # the ones actually on the line so the editor's number inputs
        # match the categories it renders.
        'slot_counts': {
            slot: count for slot, count in counter.slot_counts.items()
            if count > 0
        },
        'theme_map': counter.theme_map,
    }


@app.route('/api/v1/client-config/<client_name>', methods=['GET'])
def get_client_config(client_name):
    """Return the full editable config for one client.

    Covers every counter plus the client-level settings (city, weekend
    service, item cooldown, source pools). The top-level
    ``active_base_slots`` / ``slot_counts`` / ``theme_map`` keys describe
    the counter named by ``?counter=`` (default: the first), so callers
    that only care about single-counter clients can ignore the
    ``counters`` array.

    Includes a ``version`` field + an ``ETag: "<version>"`` response
    header so callers can issue optimistic-concurrency-safe PUTs.
    """
    try:
        loader = _get_client_loader()
        cfg = loader.get_client(client_name, _requested_counter(request.args))
        version = loader.get_client_version(client_name)
        selected = next(
            (c for c in cfg.counters if c.name == cfg.counter_name), None,
        )
        response = jsonify({
            'success': True,
            'name': cfg.name,
            'counter': cfg.counter_name,
            'counters': [_counter_payload(c) for c in cfg.counters],
            'active_base_slots': (
                _counter_payload(selected)['active_base_slots']
                if selected else []
            ),
            'slot_counts': _counter_payload(selected)['slot_counts'] if selected else {},
            'theme_map': cfg.theme_map,
            'city': cfg.city,
            'serve_weekends': cfg.serve_weekends,
            'item_cooldown_days': cfg.item_cooldown_days,
            'source_pools': cfg.source_pools,
            'version': version,
        })
        response.headers['ETag'] = f'"{version}"'
        return response
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Failed to load client config: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/client-counters/<client_name>', methods=['GET'])
def get_client_counters(client_name):
    """Return just the counter names for a client.

    The planner sidebar needs the counter list on every Streamlit rerun to
    render its picker; this keeps that off the heavier /client-config
    payload.
    """
    try:
        counters = _get_client_loader().get_counters(client_name)
        return jsonify({
            'success': True,
            'client_name': client_name,
            'counters': [c.name for c in counters],
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Failed to load counters: %s", e, exc_info=True)
        return _internal_error_response(500)


def _parse_client_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate the client-level settings from a request body.

    Returns only the keys the caller actually sent, so a PUT that just
    edits a counter doesn't reset the client's city to empty.
    """
    out: Dict[str, Any] = {}
    if 'city' in data:
        out['city'] = str(data['city'] or '').strip()
    if 'serve_weekends' in data:
        out['serve_weekends'] = bool(data['serve_weekends'])
    if 'item_cooldown_days' in data:
        try:
            cooldown = int(data['item_cooldown_days'])
        except (TypeError, ValueError):
            raise ValueError('item_cooldown_days must be an integer') from None
        if cooldown < 0:
            raise ValueError('item_cooldown_days must be >= 0')
        out['item_cooldown_days'] = cooldown
    if 'source_pools' in data:
        pools = data['source_pools']
        if isinstance(pools, str):
            pools = [p.strip() for p in pools.split(',')]
        if not isinstance(pools, (list, tuple)):
            raise ValueError('source_pools must be a list of pool names')
        out['source_pools'] = [str(p).strip() for p in pools if str(p).strip()]
    return out


_ETAG_RE = re.compile(r'^\s*(?:W/)?"?(\d+)"?\s*$')


def _expected_version(data: Dict[str, Any]) -> Optional[int]:
    """Extract the expected version from the request.

    Accepts either ``{"version": N}`` in the JSON body (preferred by our
    own UI) or an ``If-Match: "N"`` / ``If-Match: N`` header for HTTP
    clients that want to speak the standard idiom.
    """
    if 'version' in data:
        try:
            return int(data['version'])
        except (TypeError, ValueError):
            raise ValueError("version must be an integer")
    header = request.headers.get('If-Match', '').strip()
    if header:
        m = _ETAG_RE.match(header)
        if not m:
            raise ValueError("If-Match header must be a quoted integer")
        return int(m.group(1))
    return None


@app.route('/api/v1/client-config/<client_name>', methods=['PUT'])
def update_client_config(client_name):
    """Update a client's configuration.

    Body keys, all optional:

    * ``counter`` — which serving line the slot/theme keys below apply to
      (default: the client's first counter). ``new_counter_name`` renames
      it; ``create_counter: true`` allows creating a line that doesn't
      exist yet.
    * ``active_base_slots``, ``slot_counts``, ``theme_map`` — the
      selected counter's menu shape.
    * ``delete_counter`` — remove the named counter instead of editing it.
    * ``city``, ``serve_weekends``, ``item_cooldown_days``,
      ``source_pools`` — client-level settings.

    Requires an optimistic-concurrency version from the caller to avoid
    last-write-wins when two admins edit the same client. Either:
      * ``{"version": N}`` in the JSON body (what our Streamlit UI sends), or
      * ``If-Match: "N"`` header for standard HTTP clients.

    Responds 409 Conflict with the current version when the check fails.
    """
    from src.client.client_config import ConcurrentEditError

    try:
        data = request.get_json(silent=True) or {}
        loader = _get_client_loader()

        expected = _expected_version(data)
        if expected is None:
            return jsonify({
                'success': False,
                'error': (
                    'version is required (include "version" in the JSON '
                    'body or send an If-Match header with the ETag from '
                    'GET /client-config). This prevents silently '
                    'overwriting another admin\'s changes.'
                ),
            }), 400

        # Settings are read before the version bump so an invalid payload
        # (e.g. a negative cooldown) is rejected without burning a version.
        settings = _parse_client_settings(data)

        # Bump first: the conditional update is the actual race gate.
        # If another writer snuck in between the caller's GET and this
        # PUT, the update matches zero rows and we 409 before doing any
        # partial sub-update.
        new_version = loader.bump_version_if_matches(client_name, expected)

        if settings:
            loader.update_client_settings(client_name, **settings)

        if data.get('delete_counter'):
            loader.delete_counter(client_name, str(data['delete_counter']))
        else:
            counter_keys = ('active_base_slots', 'slot_counts', 'theme_map')
            if any(k in data for k in counter_keys) or data.get('new_counter_name'):
                counter = _requested_counter(data)
                if counter and data.get('create_counter'):
                    target = counter
                else:
                    # Resolve through the loader so a typo'd counter name
                    # raises UnknownCounterError (400) rather than silently
                    # appending a new line.
                    target = loader.get_client(client_name, counter).counter_name
                loader.upsert_counter(
                    client_name, target,
                    categories=data.get('active_base_slots'),
                    slot_counts=data.get('slot_counts'),
                    theme_map=data.get('theme_map'),
                    new_name=data.get('new_counter_name'),
                )

        response = jsonify({
            'success': True,
            'message': f'Config updated for {client_name}',
            'version': new_version,
        })
        response.headers['ETag'] = f'"{new_version}"'
        return response
    except ConcurrentEditError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'current_version': e.current_version,
        }), 409
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Error updating client config: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/client', methods=['POST'])
def create_client():
    """Create a new client with a single starting counter.

    Body: ``name`` (required), ``active_slots``, ``counter``/``counter_name``,
    ``slot_counts``, ``theme_map``, plus the client-level settings
    (``city``, ``serve_weekends``, ``item_cooldown_days``,
    ``source_pools``). Extra counters are added afterwards via
    PUT /client-config with ``create_counter: true``.
    """
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name', '').strip()
        active_slots = data.get('active_slots', list(BASE_SLOT_NAMES))
        if not name:
            return jsonify({'success': False, 'error': 'name is required'}), 400

        settings = _parse_client_settings(data)
        loader = _get_client_loader()
        if name in _request_client_names():
            return jsonify({
                'success': False,
                'error': f"Client '{name}' already exists.",
            }), 409
        loader.create_client(
            name, active_slots,
            counter_name=_requested_counter(data) or DEFAULT_COUNTER_NAME,
            slot_counts=data.get('slot_counts'),
            theme_map=data.get('theme_map'),
            city=settings.get('city', ''),
            serve_weekends=settings.get('serve_weekends', False),
            item_cooldown_days=settings.get(
                'item_cooldown_days', DEFAULT_ITEM_COOLDOWN_DAYS,
            ),
            source_pools=settings.get('source_pools'),
        )

        return jsonify({'success': True, 'message': f'Client {name} created'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to create client: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/client/<client_name>', methods=['DELETE'])
def delete_client(client_name):
    """Delete a client."""
    try:
        loader = _get_client_loader()
        loader.delete_client(client_name)

        # No reload needed — Supabase reads are always live
        return jsonify({'success': True, 'message': f'Client {client_name} deleted'})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Failed to delete client: %s", e, exc_info=True)
        return _internal_error_response(500)


@app.route('/api/v1/diagnose', methods=['POST'])
def diagnose_plan():
    """Pre-flight rule diagnostic. Same body shape as /plan but never
    invokes the solver — returns structured ``rule_diagnostics`` so the
    UI can show *why* a plan would fail before the user spends solver
    budget.

    Replaces the old /validate-pools endpoint; pool-size warnings are
    folded into the same ``rule_diagnostics`` list (look for entries
    with ``rule_type == 'pool_size'``).

    Response::

        {
          "success": true,
          "rule_diagnostics": [{rule, rule_type, severity, phase,
                                message, suggestion, affected}, …],
          "summary": {errors, warnings, infos, would_succeed},
          "pool_warnings": [...]   # back-compat projection, one release
        }
    """
    try:
        inputs = _prepare_solver_inputs(request.get_json() or {})
        diagnostics, summary = _run_preflight(inputs)
        _record_diag_metrics(diagnostics)
        diag_dicts = [d.to_dict() for d in diagnostics]
        body = {
            'success': True,
            'rule_diagnostics': diag_dicts,
            'summary': summary,
        }
        pool_warnings = pool_warnings_projection(diagnostics)
        if pool_warnings:
            body['pool_warnings'] = pool_warnings
        return jsonify(body)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Failed to run diagnostics: %s", e, exc_info=True)
        return _internal_error_response(500)


# Set after the first /health call observes schema drift, cleared on
# the next non-drift result. Lets us log the loud "run the migration"
# ERROR once per occurrence rather than every 30s of uptime-monitor
# noise — a re-pageable signal needs to BE re-pageable.
_drift_logged = False


def _probe_supabase():
    """Cheap reachability + schema-drift check.

    Two ``limit(1)`` queries verify, in two round-trips:

      1. Supabase is reachable / authenticated / not blocked by RLS.
      2. The counters-schema columns exist on ``clients`` (``counters``,
         ``city``, ``serve_weekends``, ``item_cooldown_days``,
         ``source_pools``, ``version``).
      3. ``menu_history`` has the jsonb ``menu`` column rather than the
         old ``slot`` / ``item_base`` long form.

    Returns ``(reachable: bool, schema_info: dict)``. The dict carries
    ``status`` ∈ {"ok", "drift_detected", "unknown"} and a list of
    ``missing`` ``"table.column"`` strings. Operators read it from the
    /health response body — uptime monitors only see the HTTP status,
    which stays 200 when drift is present (the client-config code still
    serves via its runtime fallback).
    """
    global _drift_logged
    from src.client.client_config import _CLIENT_COLUMNS, _is_undefined_column

    missing = []
    reachable = True
    for table, columns, label in (
        ('clients', _CLIENT_COLUMNS, 'clients.counters'),
        ('menu_history', 'client_name, service_date, menu', 'menu_history.menu'),
    ):
        try:
            from src.db import get_supabase
            get_supabase().table(table).select(columns).limit(1).execute()
        except Exception as exc:  # noqa: BLE001 — converted to dict states below
            # Distinguish "this deployment hasn't run the migration"
            # (caller needs to apply SQL) from "Supabase is just
            # unreachable" (network / auth issue).
            if _is_undefined_column(exc):
                missing.append(label)
                continue
            logger.warning("Supabase health probe failed on %s: %s", table, exc)
            reachable = False
            break

    if not reachable:
        return False, {"status": "unknown", "missing": []}
    if missing:
        if not _drift_logged:
            logger.error(
                "Schema drift: %s missing. Run scripts/create_tables.sql, "
                "scripts/create_history_tables.sql, and (for deployments "
                "that predate the counters schema) "
                "scripts/migrate_to_counters.sql in the Supabase SQL "
                "editor — all three are idempotent. Planning will fail or "
                "silently lose history until the migration is applied.",
                ", ".join(missing),
            )
            _drift_logged = True
        return True, {"status": "drift_detected", "missing": missing}
    if _drift_logged:
        logger.info(
            "Schema drift cleared: the counters schema is now visible."
        )
        _drift_logged = False
    return True, {"status": "ok", "missing": []}


@app.route('/api/v1/metrics', methods=['GET'])
def metrics_snapshot():
    """Return a point-in-time snapshot of every in-process counter.

    Labels are collapsed into the key using Prometheus text-format
    conventions (``rule_failures_total{rule="cuisine"}``), so a future
    swap to the real prometheus_client stays a one-file change in
    ``api/metrics.py`` without the caller surface moving.

    Gated behind auth because request volume and rule-failure patterns
    leak information about traffic shape; operators should scrape via
    a token just like any other admin endpoint.
    """
    return jsonify({
        'success': True,
        'uptime_seconds': int(time.time() - _STARTED_AT),
        'counters': metrics.snapshot(),
    })


@app.route('/api/v1/health', methods=['GET'])
def health():
    """Liveness + readiness combined.

    Returns 200 with status=healthy when Supabase is reachable, 503
    with status=degraded when it isn't. Schema drift (e.g. the user
    deployed code that needs ``clients.version`` against an unmigrated
    database) is reported in the body's ``schema`` field but does NOT
    flip the HTTP status — the app keeps serving via the runtime
    fallback in client_config.py, and we don't want to wake operators
    at 3am for a "please run a migration" task. The error log written
    by ``_probe_supabase`` is the primary signal for that.
    """
    supabase_up, schema_info = _probe_supabase()
    body = {
        'status': 'healthy' if supabase_up else 'degraded',
        'version': APP_VERSION,
        'uptime_seconds': int(time.time() - _STARTED_AT),
        'supabase_reachable': supabase_up,
        'schema': schema_info,
        'queue': _solver_stats(),
    }
    return jsonify(body), (200 if supabase_up else 503)


@app.route('/')
def root():
    return jsonify({
        'name': 'Cost Estimator Menu Planning API',
        'version': APP_VERSION,
        'docs': '/api/v1/clients',
    })


if __name__ == '__main__':
    # Logging was already configured at module import.
    app.run(host=API_HOST, port=API_PORT, debug=DEBUG)
