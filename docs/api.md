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

The planner's Cost Estimator always sends **one full service week
starting next Monday** — 5 days, or 7 when `serve_weekends` is set — and
offers no date picker: an estimate has no history, so the calendar dates
decide nothing except which day theme lands on which day, and one week
prices every configured theme exactly once. The endpoint itself accepts
any `start_date` / `num_days` within the usual limits.

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

### pax_per_day

The setup panel also collects an expected head count. It is sent with the
rest of the setup and **ignored by the endpoint** — a plan is one plate,
and the head count changes no menu decision. It exists for the costing
panel, which multiplies every per-plate figure by it. Being part of the
same config keeps one estimate's assumptions together instead of splitting
them between the setup and the costing tab.

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
| `plate_weight` | hard | Total serving weight of one day's plate ≤ `max_kg` — see [Plate weight](#plate-weight) |
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

### Plate weight

`plate_weight` governs what one person is served in one day. The cap is
per day, resolved by `src.constants.plate_cap_grams(day_type, slot_count)`
as a **theme base plus a width allowance** — every plate is capped, no day
is unlimited:

| Slots on the plate | Ordinary day | Biryani day |
|---|---|---|
| Up to 15 | **1000 g** | **1200 g** |
| 16 – 17 | 1050 g | 1250 g |
| 18 or more | 1100 g | 1300 g |

The base comes from `PLATE_CAP_GRAMS` (1000 g) and
`PLATE_CAP_GRAMS_BY_THEME` (`biryani: 1200` — a 300 g biryani rice plus a
300 g non-veg biryani is genuinely a heavier meal). The extra comes from
`plate_wide_allowance_grams(slot_count)`, which is 0 up to
`PLATE_CAP_SLOT_EXEMPTION` (15) slots and then follows
`PLATE_WIDE_ALLOWANCE_GRAMS` — a counter serving eighteen lines cannot fit
the same total as one serving eleven, but it does not get a blank cheque
either. The two are **additive**: a wide biryani day gets both.

The rule config takes no `max_kg` normally; setting one overrides the
whole policy with a single ceiling on every day:

```json
{ "name": "plate_weight_cap", "type": "plate_weight" }
```

The cap counts every item served that day **including the constant
accompaniments** (papad, pickle), which reach the solver as
`SolverConfig.const_slot_grams` / `const_slot_count`. Counting them keeps
the cap and the "Qty / Plate" figure the UI shows measuring the same
plate.

#### Fit first, trim second

The two halves are deliberately split, and nothing is ever blocked:

1. **The solver fits the plate where it can.** `apply()` compares each
   day's cap against the lightest plate its cells could build — the
   minimum candidate in every cell, which is exact, post-filter. Where
   that fits, a hard constraint goes on the day and the solver builds a
   plate within the cap while obeying every other rule.
2. **Portions are trimmed where it can't.** A day whose lightest plate
   already exceeds its cap is left *unconstrained* — forcing it would
   fail the whole plan — and
   `src.cost.plate_adjust.trim_portions()` brings it down instead, during
   cost enrichment so the money reflects the food actually served.

Trimming is shaped by the rules in `src.constants`:

- `PLATE_TRIM_STEP_GRAMS` (5 g) — kitchens serve round numbers.
- Off the heaviest portion each time, which is what makes the result
  balanced: two 300 g items shed weight together and stay level.
- `PLATE_TRIM_MAX_CUT_FRACTION` (25%) — no portion loses more than a
  quarter of itself, which forces a large trim to spread across several
  items and guarantees none reaches zero.

A day that can't reach its cap within those limits is trimmed as far as
they allow and left slightly heavy, rather than having a portion pushed
below its floor.

`diagnose()` reports which *themes* will be trimmed and by how much, as a
**warning** — never an error, since there is always a way forward. It
measures after projecting the other rules' pre-filters, because those are
what make a themed day heavy: unfiltered a rice pool starts at 80 g, but
the theme filter narrows a Biryani Wednesday to biryanis starting at
300 g.

Per-day results carry `day_qty_cap_g` and `day_qty_trimmed_g`; a trimmed
item carries `portion_trimmed_g`.

With the current ontology and a standard 11-category counter (15 items on
the plate): mix, chinese, south and north days come in at 920–980 g by
item choice alone, and a biryani day — whose lightest possible plate is
1280 g — is trimmed ~100 g to land on its 1200 g cap.

## Cost model (costing panel)

"Overall Estimated Cost" opens two independent tabs off one shared number:
the average plate food cost of the generated plan. Every figure on both
tabs is shown to **one decimal place**.

Both tabs are laid out the same way, results first: a **KPI band** across
the top, then bordered section cards holding the inputs
(`ui.cards.card_header` + `st.container(border=True)`, shared with the
customisation and estimator panels).

The KPI cards are `ui.kpi.kpi_grid()`, which reuses the planner's
`.metrics-grid` / `.metric-card` look so the costing screens read as part
of the same app. What it adds is **tone** — colour that means something,
or isn't used:

| Tone | Accent | Used for |
|---|---|---|
| `neutral` | grey | facts and inputs (avg food cost, overall cost, wage bill) |
| `cost` | blue | money out (buying price, buying amount, SmartQ cost) |
| `revenue` | purple | money in (selling price, selling amount) |
| `info` | blue note | a figure the other tab produced (Buying Price / plate) |
| `good` / `bad` | green / red | **profit** — and the only case where the number itself is coloured |

`tone_for_amount()` picks good/bad by sign, so a negative profit is the
one figure on these screens that cannot read like every other one: at a
115% buying price the SmartQ Profit KPI, the Result row and the Total
SmartQ Profit all turn red together (−₹37.1 per plate, −₹182,075.2 over
the period). A negative always carries its minus sign as well as its
colour, so the meaning survives for anyone who can't tell the two apart.
The `from roster` pill on the Manpower row is `status-pill info` (blue) —
"computed, not typed" is information, not success.

Streamlit's metric widget is not used in the band: every annotation there
is a share, a divisor or a multiplier rather than a change over time, and
the widget draws an up-arrow next to any delta. `_PANEL_CSS` in
`ui.overall_cost` suppresses that arrow for the metrics that remain.

### Vendor Cost — `src.cost.vendor_cost`

The average plate food cost is only a share of what the operation costs to
run, so it is scaled up to a fully-loaded **overall cost per plate**:

```
overall_per_plate = avg_food_cost / (food_cost_pct / 100)
```

The plate is then split into what the vendor is paid and what SmartQ
keeps:

| Line | Default | Set by | In the total? |
|---|---|---|---|
| Food cost | 45% | input (the scaling anchor) | yes |
| **Manpower** | **25%** at the default roster and 150 pax | **computed** — `src.cost.manpower` | yes |
| Operating lines (electricity & water, consumables, transport, admin, depreciation) | 20% total | inputs, `VENDOR_COST_LINES` | yes |
| **Vendor profit** | **8%** (`DEFAULT_VENDOR_PROFIT_PCT`) | input | yes |
| **Total — Buying Price / plate** | **98%** (₹242.1 of ₹247.0) | `buying_share_pct()` | — |
| **SmartQ Profit** (extra margin) | 2% | `smartq_margin_pct()`, the remainder | **no** |
| Overall Cost / plate | 100% | reference only | — |

#### Manpower — `src.cost.manpower`

Manpower is the one line nobody types a share for. A wage bill is not a
percentage of anything: it is a headcount on salaries, and the share it
comes to depends on how many plates that team serves. The Manpower row is
therefore read-only, with a roster expander under it:

```
monthly wage bill = sum(units x monthly salary)   per role
per day           = monthly wage bill / 30        the whole site
per plate         = per day / pax per day         what the row shows
share             = per plate / overall cost
```

Four roles (`MANPOWER_ROLES`): Service Boy, Supervisor, Cafeteria Manager,
Chef — each with a unit count and a monthly salary. The two divisions are
different and both are shown in the expander: **30** is the salary month
(staff are paid for the month, not for the days the cafeteria opens — it is
deliberately *not* the SmartQ tab's 22 working days), and **pax** turns the
site's daily bill into a per-plate cost. `pax` is resolved once for the
whole panel by `ui.overall_cost._panel_pax()` — the live SmartQ widget
first, then the estimator setup, then the default — because the vendor tab
needs it before the SmartQ tab renders.

The defaults (6 service boys at ₹22,000, 1 supervisor at ₹30,000, 1
cafeteria manager at ₹40,000, 2 chefs at ₹38,000 = ₹2,78,000 a month) were
chosen to land on the 25% manpower was assumed to be before it was costed,
so adopting the roster doesn't silently move every other figure.

Two consequences worth knowing. Manpower's **share floats**: raising the
food-cost share moves the overall cost, so manpower's rupee amount holds
and its percentage falls (the reverse of the typed lines, whose percentage
holds and rupees move). And a **bigger client is cheaper per plate** — the
same team at 400 pax is ₹23.2 a plate (9.4%) instead of ₹61.8 (25.0%),
which pushes the buying price down to ₹203.5 and SmartQ's margin up to
17.6%.

The total **stops at the vendor's profit**. Everything above it is money
the vendor is paid, so that sum is the **buying price**, and it is what
the SmartQ tab buys at. SmartQ's own profit sits below the total, outside
it: it is a margin, not something bought.

Vendor profit is an *input*, not what happens to be left over: a vendor
negotiates a margin rather than accepting a residue.

Because the default plate leaves only 2% of slack, a manpower increase at
a small site over-allocates it quickly — one extra chef at 150 pax takes
the buying price to 101.4% and trips the error. That is the model working:
it means the assumption that food is 45% of the loaded cost cannot support
that team at that head count, and either the price or the roster has to
move.

`margin_status()` reads the remainder: negative means the buying price has
passed the overall cost (an error, with the real total named so the fix is
obvious), exactly zero is a warning, anything positive is fine.
`profit_status()` separately judges the vendor-profit *input* against a
5–10% band — a different kind of problem, so it is only shown when it has
something to say.

Every line is edited as a percentage or as rupees; the percentage is the
source of truth and `on_change` callbacks keep the partner field in step.

### SmartQ Costing — `src.cost.smartq_cost`

```
selling_price  = overall_per_plate * (1 + markup_pct / 100)   # markup defaults to 30%
buying_amount  = buying_price      * pax * days
selling_amount = selling_price     * pax * days
extra_margin   = smartq_margin_per_plate * pax * days
smartq_profit  = selling_amount - buying_amount - smartq_cost + extra_margin
```

The plate is **priced off the overall cost but bought at the buying
price** (`vc_buying_price`, published by the vendor tab and shown here as
its own "Buying Price / plate" metric).

The selling price is set **either way round** — as `markup_pct` or as the
price per plate — because a deal is usually discussed as a round number
per head. `markup_pct_from_price()` inverts the markup, and the two inputs
are kept in step by the same callback pattern. A price below cost is
allowed (bids happen): the markup goes negative, floored at
`MIN_MARKUP_PCT` (-100%, a free plate). Two thresholds are flagged
differently — under the *buying price* is an error (the plate loses money
outright), between that and the *overall cost* is a warning (the vendor is
covered, the loaded cost isn't).

Each operating line is a share of the selling amount; the yearly Food
Licenses line is divided by `MONTHS_PER_YEAR` so its monthly equivalent
sits alongside the rest when they are summed into the SmartQ cost.

**Extra Margin** is SmartQ's per-plate profit from the vendor tab
(`vc_smartq_margin_pct`) scaled over the period by
`extra_margin_amount()`. The per-plate figure is rounded to the paisa
*before* scaling, so it reconciles against the buying price the same tab
displays rather than drifting by a rounding on every plate.

It is **revenue, not a cost reduction**, so it is added to profit. Note
what that assumes: `buying_amount` is already priced at the buying price,
which excludes the margin, so the margin is treated as a revenue stream of
its own — the client's effective bill is `selling_amount + extra_margin`.
If instead the client only ever pays the selling price, the margin is
already inside `selling_amount - buying_amount` and adding it counts it
twice; `smartq_profit()` takes `extra_margin=0.0` for that model.

**Working days and pax/day come from the estimator setup** when there is
one. The Cost Estimator asks for the expected head count (`pax_per_day`,
default 150) and whether the client is served on weekends; `/estimate-plan`
ignores the head count, and the SmartQ tab reads it from `estimate_setup`
along with `working_days_for(serve_weekends)` — 22 days Mon–Fri, 30 for
seven-day service. Both stay editable in the tab, and an edit survives
until the setup itself changes. With no setup (existing-client mode) the
defaults are 150 pax and 22 days.

The result trio — **Total SmartQ Profit**, **Extra Margin**, **SmartQ
Cost** — sits at the *top* of the tab, directly under the inputs, with the
supporting per-plate and period amounts and the editable cost lines below
it. The figures depend on those lines, so the space is claimed with a
`st.container()` before they render and written into afterwards.

The two tabs render in one script run (vendor first), so the buying price
and margin the SmartQ tab reads are always fresh.

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

### Serving weights and costs

`cost_per_kg` and `grammage_per_serving` come from the Menu List workbook,
`data/raw/menu_prices.xlsx` (sheet "Menu List": one row per item, cost in
₹/kg and serving weight in kg). They reach the app two ways, and both are
in play:

1. **Baked into the dataset.** `scripts/bake_price_list.py` writes the
   list's numbers into those two columns of `data/raw/menu_items.xlsx`.
   The columns used to hold **XLOOKUP formulas** against an external Menu
   List workbook that only resolves on the author's machine, so what the
   app read was whatever Excel last cached — and the cache was wrong in
   places (dosa at ₹9/kg where the list says ₹80/kg). Baking put 253 cost
   and 78 grammage values right; the ontology on its own now averages
   ₹10.27 per serving against ₹8.71 before, matching the list exactly.
   Re-run the script (`--dry-run` first) after dropping in a new Menu
   List; `TestPriceList` fails with that instruction if the two files
   drift apart.
2. **Overlaid at load time.** `src.preprocessor.price_list.apply_price_list()`
   re-applies the same list on every read, before cleansing, so a price
   refresh takes effect as a file drop even without re-baking. Only cells
   the list has a number for are overwritten; a missing file logs a
   warning and leaves the baked values standing, which is what a
   deployment without the Menu List should fall back to.

Matching is by normalised item name — the key the XLOOKUP used. One
ontology item carries a name the list spells differently, mapped in
`_ITEM_NAME_ALIASES` (`white_rice` → *steamed_rice - Sona Masoori*, the
default variant rather than Bullet), so all 529 items are priced from the
list and none fall back to a cached value.

Two rows were retired: `steamed_rice` is now **`white_rice`** — one dish,
one name, and `CONSTANT_ITEMS['white_rice']` shows it as *White Rice* —
and **`myos`** was withdrawn, taking its single-item `myos` category with
it.

#### Constant slots are only half-costed

`api.app._const_slot_grams` matches `CONSTANT_ITEMS` against the
ontology's `item` column to feed the plate-weight cap, and
`build_cost_lookup` prices by the same key. Papad and Pickle match rows
(₹3.0 and ₹2.0, 10 g each). **White Rice and chutney do not** — the
ontology calls them `white_rice` and `coconut_chutney` /
`garlic_chutney` / … — so neither is counted in the cap nor costed, on
any plate.

This is known and deliberately left alone: connecting white rice alone
adds 150 g to every plate, which takes an ordinary day from 940 g to over
its 1000 g cap and makes the trimmer cut 140–300 g from courses the
solver chose, dropping the average plate from ₹99.4 to ₹90.7. Fixing it
is a pricing decision (and, for chutney, a choice of which chutney), not
a rename.

The workbook also carries a second sheet, "Food cost sheet" — a
category-level *revised price* list keyed by free-text descriptions
("Dosa Varieties (mini masala/set/khali/uttappam)") in mixed units
(KG / NOS / LTR). It cannot be joined to individual items without a human
mapping, so nothing reads it.

#### Grammage corrections in code

The list's serving *weights* are still mixed for bread — chapattis at
350 g, one dosa at 800 g — so one correction stays in code, in
`src.constants.COURSE_SERVING_GRAMMAGE_KG`, applied by
`DataCleanser._apply_course_grammage()` so it survives any re-import:
**bread → 60 g**, the whole course rather than the outliers patched
individually. Upstream carried three conventions in the same column —
30–70 g for one piece (correct), 1000 g on 18 chapatti rows (a unit slip
that alone outweighed the other fourteen categories and made the plate
read 2.03 kg), and 0 g on 2 continental loaves.

After both steps the heaviest serving in the dataset is 300 g (biryani)
and the mean is 99 g.

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
