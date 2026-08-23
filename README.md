# Ikigai Masala

Constraint-based weekly menu planner for corporate meal providers. Generates
Indian menus that respect cuisine themes, item cooldowns, color variety,
per-client customizations, and history.

Each client has one or more **counters** — separate serving lines, each
with its own categories, per-slot counts, and day themes — plus
client-level settings for city, weekend service, item-cooldown window,
and which item source pools it may draw from. The planner works one
counter at a time; a day's saved menu holds every counter's picks.

The planner has two modes, switched in the sidebar:

- **Cost Estimator For New Clients** (the default) — price a
  *prospective* client by describing a counter inline (name, categories,
  frequency, day themes), generating a menu from it, and reading the
  costing panel. It always costs one full service week starting next
  Monday, so there are no dates to pick, and nothing is written to the
  database.
- **Existing Client** — plan for a client configured in the database over
  a date range you choose, replaying saved menus for dates that already
  have them, and save back.

- **Frontend:** Streamlit — Pulse / OP Lens light theme (`ui/theme.py`)
- **Backend:** Flask API (auto-started by Streamlit on port 5000)
- **Solver:** Google OR-Tools CP-SAT
- **Database:** Supabase (PostgreSQL) — clients, history, config

---

## Quick start (Docker — recommended)

```bash
cp .env.example .env       # edit and fill in SUPABASE_URL / SUPABASE_KEY / API_SECRET_KEY
docker compose up --build
```

Open `http://localhost:8501`, log in, pick a client, generate a plan.

> First-time setup: run `scripts/create_tables.sql` then
> `scripts/create_history_tables.sql` once in the Supabase SQL editor.
> Upgrading a database that predates the counters schema? Follow those
> two with `scripts/migrate_to_counters.sql` — see
> [docs/setup.md](docs/setup.md).

## Quick start (local Python)

```bash
cd ikigai_masala-main
pip install -r requirements-dev.txt

# one-time in the Supabase SQL editor:
#   scripts/create_tables.sql, create_history_tables.sql

cat > .streamlit/secrets.toml <<EOF
SUPABASE_URL   = "https://<your-project>.supabase.co"
SUPABASE_KEY   = "<service_role key>"
API_SECRET_KEY = "$(python -c 'import secrets; print(secrets.token_hex(32))')"
EOF

streamlit run app.py
```

> `scripts/seed_admin.py` / `create_users_table.sql` are only needed if
> the authentication layer is wired back into `api/app.py` — the current
> build has no login path.

---

## Documentation

- [docs/setup.md](docs/setup.md) — prerequisites, install, secrets, seed,
  every env var the app reads.
- [docs/architecture.md](docs/architecture.md) — system diagram, layer
  overview, design choices, login / plan / save / regenerate sequence
  diagrams.
- [docs/api.md](docs/api.md) — endpoint table, response shapes (plan,
  health, metrics), concurrency semantics, rules reference, data model,
  output formats.
- [docs/operations.md](docs/operations.md) — testing, CI, structured
  logs + metrics, legacy-hash kill-switch playbook, troubleshooting table,
  project layout.

For a file-level symbol map optimised for Claude Code sessions, see
[`../CLAUDE.md`](../CLAUDE.md).

---

## Tests

```bash
pytest                # default (skips @slow)
pytest -m slow        # real-Excel full-pipeline tests
```

CI runs pytest + `ruff check --select=F,E9` + `bandit -ll` on every PR;
the slow suite runs on push-to-main and manual dispatch. See
[docs/operations.md](docs/operations.md#ci).
