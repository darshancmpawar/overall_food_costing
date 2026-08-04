-- =============================================================================
-- One-off migration: pre-counters schema  ->  counters schema
--
-- Converts
--   menu_categories(name, slots)             \
--   clients.menu_category                     >  clients.counters (jsonb)
--   slot_count_overrides(client_name, slot, count)
--   theme_overrides(client_name, day, theme) /
--
--   menu_history(id, client_name, service_date, slot, item_base)
--     -> menu_history(client_name, service_date, menu jsonb)
--
-- Safe to run more than once: every step is guarded, and clients that
-- already have a non-empty ``counters`` array are left alone.
--
-- Order:
--   1. scripts/create_tables.sql          (adds the new columns)
--   2. scripts/create_history_tables.sql  (adds menu_history.menu)
--   3. this file
--
-- The old tables are NOT dropped — verify the app works first, then run
-- the DROP block at the bottom by hand.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. clients.counters — fold the three side tables into one counter each.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'clients' AND column_name = 'menu_category'
  ) THEN
    RAISE NOTICE 'clients.menu_category not present — counters migration already applied, skipping step 1.';
    RETURN;
  END IF;

  UPDATE clients c
  SET counters = jsonb_build_array(
        jsonb_build_object(
          'name', 'Counter 1',
          'categories', COALESCE(
            (SELECT to_jsonb(mc.slots) FROM menu_categories mc
             WHERE mc.name = c.menu_category),
            '[]'::jsonb
          ),
          'slot_counts', COALESCE(
            (SELECT jsonb_object_agg(sco.slot, sco.count)
             FROM slot_count_overrides sco
             WHERE sco.client_name = c.name),
            '{}'::jsonb
          ),
          'theme_map', COALESCE(
            (SELECT jsonb_object_agg(lower(t.day), t.theme)
             FROM theme_overrides t
             WHERE t.client_name = c.name),
            '{}'::jsonb
          )
        )
      )
  WHERE c.counters IS NULL
     OR jsonb_array_length(c.counters) = 0;
END
$$;

-- A client whose menu_category had no slots ends up with an empty
-- categories array, which the app reports as a configuration error. Flag
-- them here so the operator can fix them in the editor straight away.
DO $$
DECLARE
  broken TEXT;
BEGIN
  SELECT string_agg(name, ', ') INTO broken
  FROM clients
  WHERE jsonb_array_length(COALESCE(counters, '[]'::jsonb)) = 0
     OR jsonb_array_length(COALESCE(counters -> 0 -> 'categories', '[]'::jsonb)) = 0;
  IF broken IS NOT NULL THEN
    RAISE WARNING 'These clients have no usable counter after migration (assign categories in the editor): %', broken;
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. menu_history — collapse the long rows into one jsonb per client-day.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'menu_history' AND column_name = 'item_base'
  ) THEN
    RAISE NOTICE 'menu_history.item_base not present — history migration already applied, skipping step 2.';
    RETURN;
  END IF;

  CREATE TEMP TABLE _mh_rollup AS
  SELECT client_name,
         service_date,
         jsonb_build_object(
           'version', 2,
           'counters', jsonb_build_object(
             'Counter 1',
             -- Highest id wins per (day, slot): pre-overwrite-semantics
             -- data can hold several rows for one slot, and the newest
             -- save is the one that was actually served.
             (SELECT jsonb_object_agg(slot, item_base)
              FROM (
                SELECT DISTINCT ON (slot) slot, item_base
                FROM menu_history inner_mh
                WHERE inner_mh.client_name  = outer_mh.client_name
                  AND inner_mh.service_date = outer_mh.service_date
                ORDER BY slot, id DESC
              ) newest)
           )
         ) AS menu
  FROM menu_history outer_mh
  GROUP BY client_name, service_date;

  DELETE FROM menu_history;

  ALTER TABLE menu_history DROP COLUMN IF EXISTS slot;
  ALTER TABLE menu_history DROP COLUMN IF EXISTS item_base;
  ALTER TABLE menu_history DROP COLUMN IF EXISTS id;
  DROP INDEX IF EXISTS idx_menu_history_unique;

  ALTER TABLE menu_history
    ADD COLUMN IF NOT EXISTS menu JSONB NOT NULL DEFAULT '{}'::jsonb;

  INSERT INTO menu_history (client_name, service_date, menu)
  SELECT client_name, service_date, menu FROM _mh_rollup;

  BEGIN
    ALTER TABLE menu_history
      ADD CONSTRAINT menu_history_pkey PRIMARY KEY (client_name, service_date);
  EXCEPTION WHEN duplicate_table OR invalid_table_definition THEN
    RAISE NOTICE 'menu_history primary key already present.';
  END;

  DROP TABLE _mh_rollup;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. week_signatures — stamp legacy rows with the default counter prefix.
--    Rows are matched by the leading ISO date so a re-run is a no-op.
-- ---------------------------------------------------------------------------
UPDATE week_signatures
SET week_signature = 'counter=counter 1|' || week_signature
WHERE week_signature !~ '^counter=';

-- ---------------------------------------------------------------------------
-- 4. app_settings — fallback_menu_category no longer means anything now
--    that slot sets live on the counter itself.
-- ---------------------------------------------------------------------------
DELETE FROM app_settings WHERE key = 'fallback_menu_category';

COMMIT;

-- =============================================================================
-- Verify, then drop the old tables BY HAND:
--
--   SELECT name, jsonb_array_length(counters) AS counters FROM clients ORDER BY name;
--   SELECT client_name, service_date, menu FROM menu_history LIMIT 5;
--
--   ALTER TABLE clients DROP COLUMN IF EXISTS menu_category;
--   DROP TABLE IF EXISTS slot_count_overrides;
--   DROP TABLE IF EXISTS theme_overrides;
--   DROP TABLE IF EXISTS menu_categories;
-- =============================================================================
