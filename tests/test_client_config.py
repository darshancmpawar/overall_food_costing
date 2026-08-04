"""Tests for ClientConfigLoader (Supabase backend, counters schema)."""

import pytest
from unittest.mock import patch

from src.client.client_config import (
    ClientConfigLoader,
    UnknownCounterError,
    _dedupe_preserve_order,
    _normalise_theme_map,
)
from src.constants import DEFAULT_THEME_MAP, WEEKDAY_NAMES
from tests.fake_supabase import FakeSupabase


# ---------------------------------------------------------------------------
# Fixtures — a small but representative set of clients
# ---------------------------------------------------------------------------

_SOUTH_SLOTS = [
    'bread', 'rice', 'veg_dry', 'veg_gravy', 'sambar', 'rasam', 'dessert',
    'salad', 'curd', 'papad', 'pickle',
]
_NORTH_SLOTS = [
    'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'dessert', 'curd',
    'papad',
]

FAKE_CLIENTS = [
    {
        # Two counters, per-slot count override on one of them.
        'name': 'Rippling',
        'counters': [
            {
                'name': 'Counter 1',
                'categories': [
                    'welcome_drink', 'soup', 'bread', 'rice', 'dal', 'sambar',
                    'rasam', 'veg_gravy', 'veg_dry', 'nonveg_main',
                    'curd_side', 'dessert', 'white_rice', 'papad', 'pickle',
                ],
                'slot_counts': {'veg_dry': 2},
                'theme_map': {'monday': 'biryani', 'wednesday': 'mix'},
            },
            {
                'name': 'Express',
                'categories': ['bread', 'rice', 'veg_gravy', 'dessert'],
                'slot_counts': {},
                'theme_map': {},
            },
        ],
        'city': 'Bangalore',
        'serve_weekends': False,
        'item_cooldown_days': 20,
        'source_pools': [],
        'version': 4,
    },
    {
        'name': 'Stripe',
        'counters': [{
            'name': 'Counter 1',
            'categories': [
                'bread', 'rice', 'veg_dry', 'veg_gravy', 'dal', 'sambar',
                'rasam', 'nonveg_main', 'curd_side', 'dessert',
                'welcome_drink',
            ],
            'slot_counts': {'nonveg_main': 2},
            'theme_map': {},
        }],
        'city': None,
        'serve_weekends': False,
        # NULL in the DB — should fall back to the 20-day default.
        'item_cooldown_days': None,
        'source_pools': [],
        'version': 1,
    },
    {
        # Weekend-serving client with an extended theme name.
        'name': 'Amadeus',
        'counters': [
            {
                'name': 'South',
                'categories': list(_SOUTH_SLOTS),
                'slot_counts': {},
                'theme_map': {d: 'south' for d in WEEKDAY_NAMES},
            },
            {
                'name': 'North',
                'categories': list(_NORTH_SLOTS),
                'slot_counts': {},
                'theme_map': {d: 'north' for d in WEEKDAY_NAMES},
            },
            {
                'name': 'Chinese',
                'categories': ['rice', 'veg_gravy'],
                'slot_counts': {},
                'theme_map': {'monday': 'chinese_continental'},
            },
        ],
        'city': 'Bangalore',
        'serve_weekends': True,
        'item_cooldown_days': 30,
        'source_pools': ['amadeus', 'continental'],
        'version': 5,
    },
    {
        # Counters stored as a JSON string rather than decoded jsonb.
        'name': 'Vector',
        'counters': (
            '[{"name": "Counter 1", "categories": ["bread", "rice", '
            '"veg_dry", "veg_gravy", "dal", "dessert"], '
            '"slot_counts": {}, "theme_map": {}}]'
        ),
        'city': 'Bangalore',
        'serve_weekends': False,
        'item_cooldown_days': 20,
        'source_pools': [],
        'version': 2,
    },
]

FAKE_SETTINGS = [
    {
        'key': 'core_min_one_slots',
        'value': ['bread', 'rice', 'starter', 'veg_dry', 'welcome_drink',
                  'curd_side', 'nonveg_main', 'veg_gravy'],
    },
    {
        'key': 'constant_slots',
        'value': ['white_rice', 'papad', 'pickle', 'chutney'],
    },
]


@pytest.fixture
def fake_sb():
    return FakeSupabase(seed={
        'clients': FAKE_CLIENTS,
        'app_settings': FAKE_SETTINGS,
        'menu_history': [],
        'week_signatures': [],
    })


@pytest.fixture
def loader(fake_sb):
    """Return a ClientConfigLoader backed by the in-memory fake."""
    with patch('src.client.client_config.get_supabase', return_value=fake_sb):
        return ClientConfigLoader()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClientConfigLoader:
    def test_client_names_sorted(self, loader):
        assert loader.client_names == ['Amadeus', 'Rippling', 'Stripe', 'Vector']

    def test_slot_count_override_expands_slot(self, loader):
        cfg = loader.get_client('Rippling')
        assert cfg.name == 'Rippling'
        # Rippling's first counter has veg_dry: 2.
        assert 'veg_dry__1' in cfg.active_slots
        assert 'veg_dry__2' in cfg.active_slots
        assert 'veg_dry' not in cfg.active_slots

    def test_defaults_to_first_counter(self, loader):
        cfg = loader.get_client('Rippling')
        assert cfg.counter_name == 'Counter 1'
        assert cfg.counter_names == ['Counter 1', 'Express']

    def test_named_counter_scopes_slots_and_themes(self, loader):
        cfg = loader.get_client('Amadeus', 'North')
        assert cfg.counter_name == 'North'
        assert 'dal' in cfg.active_slots
        assert 'sambar' not in cfg.active_slots
        assert {cfg.theme_map[d] for d in WEEKDAY_NAMES} == {'north'}

    def test_counter_lookup_is_case_insensitive(self, loader):
        assert loader.get_client('Amadeus', 'north').counter_name == 'North'

    def test_unknown_counter_raises_with_available_names(self, loader):
        with pytest.raises(UnknownCounterError) as exc:
            loader.get_client('Amadeus', 'Rooftop')
        assert exc.value.available == ['South', 'North', 'Chinese']

    def test_const_slots_are_not_expanded(self, loader):
        cfg = loader.get_client('Rippling')
        assert cfg.active_slots.count('papad') == 1
        assert 'papad__1' not in cfg.active_slots

    def test_extended_theme_is_canonicalised_for_the_solver(self, loader):
        cfg = loader.get_client('Amadeus', 'Chinese')
        # chinese_continental is an operations-facing label; the solver's
        # pool filters only understand 'chinese'.
        assert cfg.theme_map['monday'] == 'chinese'

    def test_weekend_client_gets_weekend_themes(self, loader):
        cfg = loader.get_client('Amadeus', 'South')
        assert cfg.serve_weekends is True
        assert 'saturday' in cfg.theme_map
        assert 'sunday' in cfg.theme_map

    def test_weekday_client_has_no_weekend_themes(self, loader):
        cfg = loader.get_client('Rippling')
        assert 'saturday' not in cfg.theme_map

    def test_theme_map_falls_back_to_defaults_per_day(self, loader):
        cfg = loader.get_client('Rippling')
        assert cfg.theme_map['monday'] == 'biryani'   # stored override
        assert cfg.theme_map['tuesday'] == DEFAULT_THEME_MAP['tuesday']

    def test_client_settings_surface_on_the_config(self, loader):
        cfg = loader.get_client('Amadeus')
        assert cfg.city == 'Bangalore'
        assert cfg.item_cooldown_days == 30
        assert cfg.source_pools == ['amadeus', 'continental']

    def test_null_cooldown_falls_back_to_default(self, loader):
        assert loader.get_client('Stripe').item_cooldown_days == 20

    def test_counters_stored_as_json_string_are_parsed(self, loader):
        cfg = loader.get_client('Vector')
        assert 'veg_dry' in cfg.active_slots

    def test_unknown_client_raises(self, loader):
        with pytest.raises(ValueError, match="Unknown client"):
            loader.get_client('NonExistent')

    def test_slot_counts_zero_for_slots_not_on_the_counter(self, loader):
        counts = loader.get_slot_counts_for_client('Rippling', 'Express')
        assert counts['rice'] == 1
        # Express doesn't serve dal, so it must not be expanded into a slot.
        assert counts['dal'] == 0

    def test_core_min_one_only_applies_to_served_slots(self, loader):
        # 'nonveg_main' is a core-min-one slot but Express doesn't serve it.
        counts = loader.get_slot_counts_for_client('Rippling', 'Express')
        assert counts['nonveg_main'] == 0
        assert counts['veg_gravy'] == 1

    def test_active_slots_for_client_returns_base_slots(self, loader):
        slots = loader.get_active_slots_for_client('Rippling')
        assert 'bread' in slots
        assert 'veg_dry' in slots        # unexpanded
        assert 'veg_dry__1' not in slots

    def test_get_counter_names(self, loader):
        assert loader.get_counter_names('Amadeus') == ['South', 'North', 'Chinese']

    def test_get_client_settings(self, loader):
        assert loader.get_client_settings('Amadeus') == {
            'city': 'Bangalore',
            'serve_weekends': True,
            'item_cooldown_days': 30,
            'source_pools': ['amadeus', 'continental'],
        }

    def test_validate_accepts_the_seeded_fixtures(self, loader):
        loader.validate()

    def test_validate_rejects_a_client_with_no_counters(self, loader, fake_sb):
        fake_sb.seed('clients', [{'name': 'Empty', 'counters': []}])
        with pytest.raises(ValueError, match="no counters"):
            loader.validate()

    def test_validate_rejects_unknown_slot(self, loader, fake_sb):
        fake_sb.seed('clients', [{
            'name': 'Bogus',
            'counters': [{'name': 'C1', 'categories': ['bread', 'pizza']}],
        }])
        with pytest.raises(ValueError, match="unknown slot"):
            loader.validate()

    def test_validate_rejects_duplicate_counter_names(self, loader, fake_sb):
        fake_sb.seed('clients', [{
            'name': 'Dupe',
            'counters': [
                {'name': 'C1', 'categories': ['bread']},
                {'name': 'c1', 'categories': ['rice']},
            ],
        }])
        with pytest.raises(ValueError, match="duplicate counter name"):
            loader.validate()

    def test_core_min_one_slots(self, loader):
        slots = loader.core_min_one_slots
        assert 'bread' in slots
        assert 'rice' in slots


class TestMutations:
    def test_create_client_writes_one_counter(self, loader, fake_sb):
        loader.create_client(
            'NewCo', ['bread', 'rice', 'dessert'],
            city='Pune', serve_weekends=True, item_cooldown_days=15,
            source_pools=['newco'],
        )
        cfg = loader.get_client('NewCo')
        assert cfg.counter_names == ['Counter 1']
        assert cfg.city == 'Pune'
        assert cfg.serve_weekends is True
        assert cfg.item_cooldown_days == 15
        assert cfg.source_pools == ['newco']

    def test_create_client_rejects_empty_categories(self, loader):
        with pytest.raises(ValueError, match="at least one valid category"):
            loader.create_client('Nope', ['not_a_slot'])

    def test_upsert_counter_appends_a_new_line(self, loader):
        loader.upsert_counter(
            'Vector', 'Salad Bar', categories=['salad', 'dessert'],
        )
        assert loader.get_counter_names('Vector') == ['Counter 1', 'Salad Bar']

    def test_upsert_counter_leaves_other_counters_alone(self, loader):
        loader.upsert_counter('Amadeus', 'North', categories=['bread', 'rice'])
        south = loader.get_client('Amadeus', 'South')
        assert 'sambar' in south.active_slots
        north = loader.get_client('Amadeus', 'North')
        assert set(north.active_slots) == {'bread', 'rice'}

    def test_upsert_counter_only_touches_fields_passed(self, loader):
        loader.upsert_counter('Rippling', 'Counter 1', theme_map={'friday': 'south'})
        cfg = loader.get_client('Rippling')
        assert cfg.theme_map['friday'] == 'south'
        # Slot set and counts survive a theme-only save.
        assert 'veg_dry__2' in cfg.active_slots

    def test_removing_a_slot_drops_its_stale_count(self, loader):
        loader.upsert_counter(
            'Rippling', 'Counter 1',
            categories=['bread', 'rice', 'veg_gravy'],
        )
        counts = loader.get_slot_counts_for_client('Rippling')
        assert counts['veg_dry'] == 0

    def test_rename_counter(self, loader):
        loader.upsert_counter('Rippling', 'Express', new_name='Grab & Go')
        assert loader.get_counter_names('Rippling') == ['Counter 1', 'Grab & Go']

    def test_delete_counter(self, loader):
        loader.delete_counter('Amadeus', 'Chinese')
        assert loader.get_counter_names('Amadeus') == ['South', 'North']

    def test_delete_unknown_counter_raises(self, loader):
        with pytest.raises(UnknownCounterError):
            loader.delete_counter('Amadeus', 'Rooftop')

    def test_cannot_delete_the_last_counter(self, loader):
        with pytest.raises(ValueError, match="at least one counter"):
            loader.delete_counter('Vector', 'Counter 1')

    def test_update_client_settings_is_partial(self, loader):
        loader.update_client_settings('Amadeus', city='Chennai')
        cfg = loader.get_client('Amadeus')
        assert cfg.city == 'Chennai'
        # Untouched fields survive.
        assert cfg.item_cooldown_days == 30
        assert cfg.serve_weekends is True

    def test_update_client_settings_rejects_negative_cooldown(self, loader):
        with pytest.raises(ValueError, match="must be >= 0"):
            loader.update_client_settings('Amadeus', item_cooldown_days=-1)

    def test_delete_client(self, loader):
        loader.delete_client('Vector')
        assert 'Vector' not in loader.client_names


class TestHelpers:
    def test_dedupe_preserve_order(self):
        assert _dedupe_preserve_order(['a', 'b', 'a', 'c']) == ['a', 'b', 'c']

    def test_normalise_theme_map_drops_unknown_days(self):
        out = _normalise_theme_map({'someday': 'south', 'monday': 'north'})
        assert 'someday' not in out
        assert out['monday'] == 'north'

    def test_normalise_theme_map_excludes_weekends_by_default(self):
        out = _normalise_theme_map({'saturday': 'south'})
        assert 'saturday' not in out

    def test_normalise_theme_map_includes_weekends_when_served(self):
        out = _normalise_theme_map({'saturday': 'north'}, serve_weekends=True)
        assert out['saturday'] == 'north'
