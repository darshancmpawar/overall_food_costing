# API reference

All endpoints are under `/api/v1`. Every endpoint except `/health`, `/`, and
`/auth/login` requires an `Authorization: Bearer <token>` header.

Requests and responses are JSON. Responses carry an `X-Request-ID` header —
accept or supply it to correlate traces across logs.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST   | `/auth/login` | Exchange email + password for a bearer token |
| GET    | `/health` | Liveness + readiness — see [health response](#health-response) |
| GET    | `/metrics` | In-process counter snapshot (auth-gated) |
| GET    | `/clients` | List client names |
| GET    | `/client-counters/<name>` | List a client's counter (serving-line) names |
| POST   | `/plan` | Generate a plan |
| POST   | `/estimate-plan` | Generate a plan for a **prospective** client described inline — see [Cost Estimator](#cost-estimator-prospective-clients) |
| POST   | `/regenerate` | Regenerate selected cells |
| POST   | `/estimate-regenerate` | Regenerate selected cells of an estimate |
| POST   | `/save` | Persist plan to history (overwrites the prior menu for the same `(client, counter, dates)`) |
| GET    | `/saved-plan` | Return the saved plan for `(client_name, counter, start_date, num_days)` if one exists — used by Streamlit's Generate flow to replay saved menus deterministically |
| POST   | `/diagnose` | Run the pre-flight rule diagnostics without invoking the solver (replaces the old `/validate-pools` surface) |
| GET    | `/editor-metadata` | Slot / theme metadata for the editor UI and the Cost Estimator setup panel. Degrades to `clients: []` (never a 500) when the client list can't be read, so pricing a prospect doesn't depend on the stored-client table |
| GET    | `/client-config/<name>` | Read a client's config, all counters included (returns `ETag: "<version>"`) |
| PUT    | `/client-config/<name>` | Update a client's config or one of its counters (requires `version` body field or `If-Match` header) |
| POST   | `/client` | Create a client with its first counter |
| DELETE | `/client/<name>` | Delete a client |

### Counters

A client has one or more **counters** — separate serving lines, each with
its own slot list, per-slot counts, and day themes. `/plan`,
`/regenerate`, `/save`, `/diagnose`, and `/saved-plan` all accept an
optional `counter` (alias: `counter_name`) and default to the client's
first counter, so single-counter callers can ignore the concept
entirely. Naming a counter the client doesn't have is a 400 (404 on the
config read) listing the names that do exist — never a silent fallback,
which would quietly plan the wrong menu.

Everything downstream of the request — pools, rules, diagnostics,
cooldowns, saved history — is scoped to the one counter being planned.

---

## Health response

`GET /api/v1/health` — 200 when healthy, 503 when degraded. Either way the
body carries enough to diagnose.

```json
{
  "status": "healthy",
  "version": "abc1234",
  "uptime_seconds": 42,
  "supabase_reachable": true,
  "queue": {
    "active_solves": 0, "queued": 0,
    "max_running": 2, "max_queued": 8,
    "workers_per_solve": 9
  }
}
```

---

## Metrics response

`GET /api/v1/metrics` — counters are monotonic and never reset in-process.
Counter names follow Prometheus conventions so a future swap to
`prometheus_client` is a one-file change in `api/metrics.py`.

```json
{
  "success": true,
  "uptime_seconds": 3621,
  "counters": {
    "plan_requests_total{outcome=\"success\"}": 14,
    "plan_requests_total{outcome=\"solver_error\"}": 1,
    "regenerate_requests_total{outcome=\"success\"}": 3,
    "solver_failures_total": 1,
    "rule_failures_total{rule=\"theme_day\"}": 2,
    "legacy_sha256_verifications_total{result=\"success\"}": 0
  }
}
```

---

## Plan response

```json
{
  "success": true,
  "solution": {
    "2026-03-31": {
      "theme": "Mix of South + North",
      "day_type": "mix",
      "items": {
        "welcome_drink": { "display_name": "Welcome Drink", "item": "masala_chaas(Y)", "item_base": "masala_chaas" },
        "rice":          { "display_name": "Flavor Rice",   "item": "jeera_rice(W)",   "item_base": "jeera_rice" }
      }
    }
  },
  "pool_warnings": [
    "Chinese Tuesday 01 Apr: only 4 veg dry items available, need 3"
  ],
  "rule_warnings": [
    { "rule": "theme_starter_preference", "phase": "get_objective_terms",
      "error": "ValueError: ...", "attempt_seed": 1017 }
  ]
}
```

`rule_warnings` only appears when one or more soft rules failed during the
winning solve attempt. Each entry carries `attempt_seed` so the failure can
be reproduced.

---

## Saved-plan response

`GET /api/v1/saved-plan?client_name=<name>&start_date=YYYY-MM-DD&num_days=<n>`

Returns the same `solution` shape as `/plan`, sourced from `menu_history`
instead of the solver. Used by Streamlit's **Generate** button so a user
who has already saved a plan for the selected dates sees that exact plan
back, deterministically. Never invokes the solver.

```json
{
  "success": true,
  "exists": true,
  "covered_dates": ["2026-03-23", "2026-03-24"],
  "source": "history",
  "solution": {
    "2026-03-23": {
      "theme": "Mix of South + North",
      "day_type": "mix",
      "items": {
        "rice": { "display_name": "Flavor Rice",
                  "item": "jeera_rice(Y)", "item_base": "jeera_rice" }
      }
    }
  }
}
```

- `exists` is `true` iff **every** requested weekday has at least one
  saved row. `false` covers both "nothing saved" and "partially saved"
  cases — the Streamlit UI falls back to `POST /plan` when `exists` is
  false. `covered_dates` shows which dates did have rows, so a future
  UI revision can offer "load partial + generate the rest".
- Color suffixes (`(Y)`, `(R)`, …) on `item` are re-attached server-side
  by looking each `item_base` up in the loaded Excel ontology, so the
  UI's renderer doesn't need a code branch.
- The plan's `theme` / `day_type` come from the **current** client
  config — i.e. if the day-theme map was changed after the plan was
  saved, the loaded plan shows the new theme labels. The underlying
  items don't move.

---

## Pre-flight diagnostics

`POST /api/v1/diagnose` (and the same pass embedded in `POST /api/v1/plan`)
runs every registered rule's `diagnose()` method against the request's
client config + history + pool state, returning structured findings
**without running the CP-SAT solver**.

```json
{
  "success": true,
  "rule_diagnostics": [
    {
      "rule": "item_cooldown_20d",
      "rule_type": "item_cooldown",
      "severity": "error",
      "phase": "pre_filter",
      "message": "Item cooldown (20 days) banned all 8 starter candidates on 2026-05-13 (chinese). Pool is empty after cooldown.",
      "suggestion": "Lower cooldown_days for this rule, add more starter items to the ontology, or choose a later start date so recent history falls outside the cooldown window.",
      "affected": {
        "date": "2026-05-13", "slot": "starter", "day_type": "chinese",
        "banned_count": 8, "pool_size_before": 8, "pool_size_after": 0,
        "cooldown_days": 20
      }
    }
  ],
  "summary": {"errors": 1, "warnings": 3, "infos": 2, "would_succeed": false},
  "pool_warnings": ["Chinese Tuesday 13 May: only 0 starter items available, need 1"]
}
```

### Severity model

- `error` — solver would **fail**. `POST /api/v1/plan` short-circuits to **HTTP 422** before invoking CP-SAT.
- `warning` — solver may succeed but the configuration is risky (tight pools, silent fallback after a theme filter empties a pool, asymmetric coupling data).
- `info` — notable but expected (e.g. "cooldown banned 4/12 items, pool still healthy"; "ingredient ban removes 3 mushroom items").

`summary.would_succeed` is `false` iff any diagnostic carries `severity=error`.

### /plan pre-flight gate (HTTP 422)

When `/api/v1/plan` runs and pre-flight finds at least one `error`:

```json
HTTP/1.1 422 Unprocessable Entity
{
  "success": false,
  "error": "rule_diagnostics_blocked",
  "message": "Pre-flight diagnostics found 1 blocking issue for Rippling; solver skipped.",
  "rule_diagnostics": [...],
  "summary": {"errors": 1, ...},
  "pool_warnings": [...]
}
```

`MenuApiClient._parse_response` recognises this envelope and raises
`RuleDiagnosticsBlockedError(diagnostics, summary)` — a subclass of
`RuntimeError` — so the Streamlit UI can render the diagnostics
expander directly without a second round-trip.

### pool_warnings (back-compat)

`pool_warnings` is now a string-projection of the `rule_diagnostics`
entries with `rule_type == "pool_size"`. The key stays in the response
for one release so older Streamlit builds keep rendering something;
new code should consume `rule_diagnostics` directly.

The old `POST /api/v1/validate-pools` endpoint is **removed** — its
surface is fully subsumed by `/diagnose`.

---

## Cost Estimator (prospective clients)

`POST /estimate-plan` prices a client that **does not exist yet**. The
menu shape arrives in the request instead of being read from the
`clients` table:

```json
{
  "client_name":  "Acme Corp",
  "categories":   ["rice", "bread", "veg_gravy", "papad"],
  "slot_counts":  {"veg_dry": 2},
  "theme_map":    {"monday": "south", "tuesday": "chinese_continental"},
  "serve_weekends": false,
  "start_date":   "2026-09-07",
  "num_days":     5,
  "time_limit_seconds": 200
}
```

Only `categories` is required. Missing per-slot counts default to 1,
missing days fall back to the [default theme schedule](#default-theme-schedule),
extended theme names are canonicalised, and unknown slot names are
dropped. A body whose `categories` contains no recognised slot is a
**400** — there is no menu to cost.

**`client_name` is a label, not a lookup key.** It is echoed back in the
response message and never resolved against the `clients` table, so a
name that already exists is neither matched nor conflicted with.

The response mirrors [`/plan`](#plan-response) — same `solution` shape,
same per-item / per-day cost enrichment, same `rule_diagnostics` and
pre-flight 422 gate — plus `"estimate": true`.

### What the estimator deliberately does not do

| | Why |
|---|---|
| No Supabase read or write | An estimate for a deal that never closes must not leave a half-created client, or a history row, behind. The endpoint works against an empty database. |
| No history, so no cooldown bans | A prospect has served nothing. The cooldown / rice-bread-gap / week-signature rules stay in the pipeline as no-ops rather than being removed, so an estimate runs through exactly the same rule set a real plan does. |
| No per-client rules | `client_rules.json` is keyed by name. Matching a name an operator just typed would silently apply another client's ingredient bans to an unrelated estimate. |
| No `core_min_one_slots` floor | That setting lives in `app_settings`; reading it would mean a round trip, and an estimator asking for one item per line should get exactly one. |
| No save path | `/save` is unreachable from this flow — the UI hides the button. |

`/estimate-plan` shares the `plan` rate-limit bucket with `/plan`, and
`/estimate-regenerate` shares `regenerate`: both spend the same solver
budget, so they throttle together. Outcomes are counted separately as
`estimate_requests_total` / `estimate_regenerate_requests_total`.

`POST /estimate-regenerate` takes the same body plus `base_plan` and
`replace_slots` (as `/regenerate`). The estimator config has to be
re-sent because nothing about the prospective client is stored
server-side.

---

## Save semantics

`POST /api/v1/save` writes **overwrite** to `menu_history` and
`week_signatures`, scoped to the counter being saved:

* `menu_history` holds one row per `(client_name, service_date)` with
  every counter's picks nested under `menu.counters`. Saving one counter
  reads the day's row, replaces that counter's entry, and upserts — so
  re-saving replaces the prior plan for that line while the other lines'
  menus survive untouched.
* `week_signatures` rows are stamped with a `counter=<name>|` prefix.
  Saving deletes the week's rows for this counter (plus any prefix-less
  legacy row) before inserting, so a multi-counter client keeps exactly
  one signature per line per week.

This is what makes the Generate → load-from-history flow deterministic:
the latest save is always the canonical answer.

The read-merge-upsert is not transactional. Two admins saving *different
counters for the same day* at the same instant can have one overwrite the
other; the window is milliseconds and the loser just clicks Save again,
which beats requiring a transactional RPC against Supabase.

The single-shot retry policy in `MenuApiClient.save()` is unchanged —
even though server-side `/save` is now idempotent on retry, a popped
"Plan saved" toast on a silent second attempt is more confusing than
just bubbling the error and letting the user retry explicitly.

---

## Client-config concurrency

```
GET  /api/v1/client-config/<name>      -> {version: 3, ...}   ETag: "3"
PUT  /api/v1/client-config/<name>      body {"version": 3, "theme_map": {...}}
  → 200 {version: 4, ...}   ETag: "4"
  → 409 {"current_version": 5, "error": "modified by another request..."}
```

Either include `"version": N` in the body (preferred by the Streamlit UI)
or send `If-Match: "N"` as a header — standard HTTP conditional-update idiom.

The version is bumped *after* the body is validated, so a rejected
payload (say a negative `item_cooldown_days`) doesn't consume a version
and force a spurious 409 on the admin's next, valid save.

### PUT body keys

| Key | Effect |
|---|---|
| `counter` | Which serving line the slot/theme keys apply to (default: first) |
| `active_base_slots`, `slot_counts`, `theme_map` | That counter's menu shape |
| `new_counter_name` | Rename the selected counter |
| `create_counter: true` | Allow `counter` to name a line that doesn't exist yet |
| `delete_counter` | Remove the named counter (the last one can't be deleted) |
| `city`, `serve_weekends`, `item_cooldown_days`, `source_pools` | Client-level settings |

Only the keys present are touched, so a theme-only save can't reset a
client's city to empty.

---

## Error envelope

Failures return HTTP 4xx/5xx with:

```json
{ "success": false, "error": "<human-readable message>" }
```

- 400: validation failure (missing field, unknown client, malformed JSON)
- 401: missing / invalid token
- 403: insufficient role for an admin-only route
- 409: optimistic concurrency conflict (on `PUT /client-config`)
- 500: unexpected server error — a generic message, never exception details
- 429: per-principal rate limit tripped (`/plan`: 10/min burst 10; `/regenerate`: 20/min burst 20). Response includes `Retry-After` and `retry_after_seconds`. `MenuApiClient` retries once with jitter automatically.
- 503: server at capacity (solver queue full) or supabase unreachable (on `/health`)
- 504: request timed out waiting in the solver queue

---

## Menu rules

Defined in `src/menu_rules/`, wired up from `data/configs/indian_menu_rules.json`.
Per-client overrides live in `data/configs/client_rules.json`.

### Generic rules

| Rule | Kind | Role |
|---|---|---|
| `cuisine` | hard | Minimum cuisine variety per day |
| `color_variety` | hard | Minimum distinct colors per day |
| `color_pairing` | hard | Maximum same-color items per day |
| `unique_items` | hard | No repeats within the horizon |
| `coupling` | hard | Item dependencies (curry ↔ rice, etc.) |
| `curd_side` | hard | Fill the curd-side slot |
| `premium` | hard | Per-horizon min / max for premium items |
| `welcome_drink_color` | hard | Color variety for welcome drinks |
| `theme_day` | hard | Monday mix (≥1 south + ≥1 north) |
| `theme_slot_filter` | pre-filter | Narrow pools by day theme (chinese / biryani / south / north) |
| `item_cooldown` | pre-filter | Ban items used within N days |
| `ricebread_gap` | pre-filter | Enforce N-day gap between rice-breads |
| `nonveg_biryani_weekly` | pre-filter | ≤1 nonveg biryani per week |
| `nonveg_dry_preference` | pre-filter | Prefer dry nonveg on certain days |
| `theme_starter_preference` | soft | Bonus for theme-matching starters |
| `theme_fallback_penalty` | soft | Penalty when a non-theme fallback is used |
| `week_signature_cooldown` | soft | Avoid re-running a recent week verbatim |

### Per-client rules

Stored per client in `data/configs/client_rules.json`, loaded fresh on every request:

| Rule | Kind | Role |
|---|---|---|
| `ingredient_ban` | pre-filter | Case-insensitive ban by `key_ingredient` |
| `item_frequency` | hard | Weekly frequency cap by flag / sub-category / item / ingredient |
| `slot_day_restriction` | skip-cells | Skip a slot on specific weekdays (e.g. no nonveg on Tue/Thu) |

Rule configs are validated at load time. Invalid configs (for example
`min_per_week > max_per_week`) are logged with the specific field names
that failed and skipped — the solver never sees them.

---

## Data model

### Supabase tables

| Table | Columns | Purpose |
|---|---|---|
| `clients` | `name (pk)`, `counters (jsonb)`, `city`, `serve_weekends`, `item_cooldown_days`, `source_pools (jsonb)`, `version`, `created_at` | Client registry — serving lines and settings inline (version = optimistic-concurrency counter) |
| `app_settings` | `key`, `value` | Misc tunables (`constant_slots`, `core_min_one_slots`) |
| `menu_history` | `client_name`, `service_date` (composite pk), `menu (jsonb)`, `created_at` | One row per client-day; every counter's picks nested inside `menu` |
| `week_signatures` | `id (pk)`, `client_name`, `week_start`, `week_signature`, `created_at` | Week-level hash, one per counter (see prefix below) |

`clients.counters` is an array of serving lines:

```json
[{"name":        "South Indian",
  "categories":  ["bread", "rice", "veg_dry", "sambar", "papad"],
  "slot_counts": {"veg_dry": 2},
  "theme_map":   {"monday": "south", "tuesday": "south"}}]
```

`menu_history.menu` nests each counter's picks for the day:

```json
{"version": 2,
 "counters": {"South Indian": {"bread": "akki_roti", "rice": "bisi_bele_bhat"},
              "North Indian": {"bread": "butter_naan", "rice": "jeera_rice"}}}
```

A bare `{slot: item}` map is also accepted on read and treated as the
default counter (`Counter 1`), so hand-written and pre-migration rows
still load.

`week_signatures.week_signature` carries a `counter=<name>|` prefix ahead
of the signature body. The signature parser skips any leading non-date
token, so the prefix needs no schema change; prefix-less rows predate
counters and apply to every counter.

Deployments upgrading from the pre-counters schema (`menu_category`,
`menu_categories`, `slot_count_overrides`, `theme_overrides`, long-form
`menu_history`) run `scripts/migrate_to_counters.sql`. `/health` reports
`schema.status = "drift_detected"` with the missing columns named until
the migration lands.

> The `users` table and `scripts/create_users_table.sql` are only needed
> if the authentication layer is wired back into `api/app.py` — the
> current build has no login path, so a database without `users` is
> expected.

### Slot expansion

Base slot names (e.g. `veg_dry`) get expanded to indexed slot ids (`veg_dry__1`,
`veg_dry__2`) based on the counter's `slot_counts`. Rules operate on the
expanded ids; `_base_slot()` strips the suffix when needed. Slots a
counter doesn't serve are stored as count `0` and drop out of expansion.

### Combined and carved-out slots

| Slot | Backed by |
|---|---|
| `dal_sambar` | union of the `dal` and `sambar` pools |
| `sambar_rasam` | union of the `sambar` and `rasam` pools |
| `curd` | `curd_side` items flagged `is_plain_curd` |
| `curd_rice` | `rice` items flagged `is_curd_rice` |

These are opt-in per counter, so an ontology that can't fill one only
warns at pool-build time; a counter that *does* declare it gets a
pre-flight diagnostic instead.

### Source pools

`clients.source_pools` names extra item collections a client may draw
from, matched against the ontology's optional `source_pool` column. Items
with no value (or `common` / `shared` / `default` / `base` / `all` /
`core`) are the shared ontology and always in scope. An ontology with no
`source_pool` column is treated as entirely shared — filtering is skipped
rather than emptying every pool the moment someone sets the field.

### Default theme schedule

| Day | Theme |
|---|---|
| Monday | Mix (south + north) |
| Tuesday | Chinese |
| Wednesday | Biryani |
| Thursday | South Indian |
| Friday | North Indian |
| Saturday | South Indian |
| Sunday | North Indian |

Each counter's `theme_map` overrides this per day; days it omits fall back
to the table above. Saturday/Sunday only apply when the client has
`serve_weekends = true`, which also makes weekends count as service days
in `/plan`'s date walk.

`chinese_continental` is accepted as a theme name and canonicalised to
`chinese` before it reaches the pool filters — the filters only compare
against `mix` / `chinese` / `biryani` / `south` / `north`.

### Item cooldown

`clients.item_cooldown_days` (default 20 when NULL) drives the
`item_cooldown` rule, the ban set handed to the solver, and the history
lookback window. Cooldowns are computed **per counter**: a dish served on
one line doesn't block another, or a client running three lines that each
serve bread daily would burn through the bread pool three times as fast
and go infeasible.

---

## Output formats

### UI theme badges

Colour tokens live in `ui/theme.py` (the Pulse / OP Lens palette);
`ui/styles.py` mirrors them into CSS custom properties and every inline
style imports them, so the two can't drift.

| Theme | Family | Background | Text |
|---|---|---|---|
| Mix | Brand blue | `#EBF3FF` | `#0A58CA` |
| Chinese | Purple | `#F1EAFB` | `#5A34A3` |
| Biryani | Brand yellow | `#FFF6E3` | `#8A5A00` |
| South | Success green | `#E5FFF1` | `#0F7A42` |
| North | Warning orange | `#FFF5E8` | `#B35F00` |

### Plan-source badges

| Badge | Meaning |
|---|---|
| Loaded from history | These dates already had a saved plan; `/saved-plan` returned it |
| Freshly generated | `/plan` ran the solver |
| Modified — unsaved | At least one cell was regenerated since load |
| Pre-flight blocked | Diagnostics returned 422; the solver was skipped |
| Cost estimate — not saved | Produced by `/estimate-plan`; nothing was written to the database |

### Color suffixes

Items carry a single-letter color code from the ontology: `R`, `G`, `B`, `Y`,
`W`, `O`, `K`.

### CSV download

The **Download CSV** button exports a plain-text CSV, one slot per row, one
weekday per column. Color suffixes are stripped; slot names are display-
formatted (`veg_dry` → `Veg Dry`).
