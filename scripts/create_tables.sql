-- =============================================================================
-- Supabase schema for Ikigai Masala client configuration (counters revision)
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New query).
-- Re-running is idempotent.
--
-- Order: this file, then create_history_tables.sql. If you are upgrading a
-- database that still has menu_categories / slot_count_overrides /
-- theme_overrides, run migrate_to_counters.sql after both.
-- =============================================================================

-- 1. Clients — one row per site, with its serving lines inline.
--
-- ``counters`` is an array of objects, one per serving line:
--   [{"name":        "South Indian",
--     "categories":  ["bread","rice","veg_dry", …],
--     "slot_counts": {"veg_dry": 2, …},
--     "theme_map":   {"monday":"south", …}}]
--
-- ``version`` is an optimistic-concurrency counter: GET /client-config
-- returns the current value; PUT must send the same value back and fails
-- with 409 Conflict if another writer bumped it in the meantime.
--
-- ``source_pools`` names extra item collections this client may draw from
-- on top of the shared ontology (matched against the ontology's
-- ``source_pool`` column). Empty array = shared items only.
CREATE TABLE IF NOT EXISTS clients (
    name               TEXT PRIMARY KEY,
    counters           JSONB   NOT NULL DEFAULT '[]'::jsonb,
    city               TEXT,
    serve_weekends     BOOLEAN NOT NULL DEFAULT false,
    item_cooldown_days INT     DEFAULT 20 CHECK (item_cooldown_days IS NULL OR item_cooldown_days >= 0),
    source_pools       JSONB   NOT NULL DEFAULT '[]'::jsonb,
    version            INT     NOT NULL DEFAULT 1,
    created_at         TIMESTAMPTZ DEFAULT now()
);

-- Migrations for deployments created before these columns existed. All
-- no-ops on a fresh install since CREATE TABLE above includes them.
ALTER TABLE clients ADD COLUMN IF NOT EXISTS counters           JSONB   NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS city               TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS serve_weekends     BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS item_cooldown_days INT     DEFAULT 20;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS source_pools       JSONB   NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS version            INT     NOT NULL DEFAULT 1;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS created_at         TIMESTAMPTZ DEFAULT now();

-- counters must be an array of objects — a bare object or a string here
-- would surface as "client has no counters" at plan time, which is a much
-- worse error message than a write-time rejection.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'clients_counters_is_array'
  ) THEN
    ALTER TABLE clients
      ADD CONSTRAINT clients_counters_is_array
      CHECK (jsonb_typeof(counters) = 'array');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'clients_source_pools_is_array'
  ) THEN
    ALTER TABLE clients
      ADD CONSTRAINT clients_source_pools_is_array
      CHECK (jsonb_typeof(source_pools) = 'array');
  END IF;
END
$$;

-- 2. App-level settings (core_min_one_slots, constant_slots, …)
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT  PRIMARY KEY,
    value JSONB NOT NULL
);

-- Note: menu_history and week_signatures are defined in
-- create_history_tables.sql (with FK + index safety nets).

-- =============================================================================
-- Enable Row Level Security (keep tables accessible via service/anon key)
-- =============================================================================
-- RLS for menu_history / week_signatures lives in create_history_tables.sql
-- so this script only needs to be run before that one (or in any order
-- once both have been applied).
ALTER TABLE clients      ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY;

-- Allow full access via the anon key (single-tenant app)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on clients') THEN
    CREATE POLICY "Allow all on clients"      ON clients      FOR ALL USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow all on app_settings') THEN
    CREATE POLICY "Allow all on app_settings" ON app_settings FOR ALL USING (true) WITH CHECK (true);
  END IF;
END
$$;

-- =============================================================================
-- Baseline settings. ON CONFLICT DO NOTHING so an existing tuned value is
-- never clobbered by a re-run.
-- =============================================================================
INSERT INTO app_settings (key, value) VALUES
    ('constant_slots',     '["white_rice","papad","pickle","chutney"]'::jsonb),
    ('core_min_one_slots', '["bread","rice","starter","veg_dry","welcome_drink","curd_side","nonveg_main","veg_gravy"]'::jsonb)
ON CONFLICT (key) DO NOTHING;
