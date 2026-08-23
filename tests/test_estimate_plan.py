"""Tests for the Cost Estimator path.

Covers :func:`src.client.client_config.build_adhoc_client_config` (the
pure config factory) and the ``/estimate-plan`` /
``/estimate-regenerate`` endpoints, whose defining property is that they
never touch the ``clients`` or ``menu_history`` tables — an estimate for
a prospective client must not create or read stored state.
"""

import datetime as dt

import pytest

from src.client.client_config import build_adhoc_client_config
from src.constants import DEFAULT_COUNTER_NAME, DEFAULT_ITEM_COOLDOWN_DAYS

flask = pytest.importorskip("flask", reason="Flask not installed")
from api.app import app  # noqa: E402


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


ESTIMATE_CATEGORIES = [
    'welcome_drink', 'starter', 'soup', 'salad', 'rice', 'dal',
    'veg_gravy', 'veg_dry', 'bread', 'curd_side', 'dessert',
]


def _body(**overrides):
    body = {
        'client_name': 'Acme Corp',
        'categories': list(ESTIMATE_CATEGORIES),
        'start_date': '2026-09-07',   # a Monday
        'num_days': 2,
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# build_adhoc_client_config
# ---------------------------------------------------------------------------

class TestBuildAdhocClientConfig:
    def test_expands_slot_counts_into_numbered_slots(self):
        cfg = build_adhoc_client_config(
            'Acme', ['rice', 'veg_dry', 'papad'], {'veg_dry': 2},
        )
        assert cfg.active_slots == ['rice', 'veg_dry__1', 'veg_dry__2', 'papad']
        assert cfg.slot_counts['veg_dry'] == 2
        assert cfg.slot_counts['rice'] == 1

    def test_unserved_slots_get_zero_count(self):
        cfg = build_adhoc_client_config('Acme', ['rice'])
        assert cfg.slot_counts['rice'] == 1
        # A slot the counter doesn't serve must be 0 so _expand drops it.
        assert cfg.slot_counts['nonveg_main'] == 0

    def test_theme_map_fills_missing_days_and_canonicalises(self):
        cfg = build_adhoc_client_config(
            'Acme', ['rice'],
            theme_map={'monday': 'south', 'tuesday': 'chinese_continental'},
        )
        assert cfg.theme_map['monday'] == 'south'
        # Extended names are canonicalised for the solver's filters.
        assert cfg.theme_map['tuesday'] == 'chinese'
        # Unspecified days fall back to the global default map.
        assert cfg.theme_map['wednesday'] == 'biryani'
        # Weekends are excluded unless the client serves them.
        assert 'saturday' not in cfg.theme_map

    def test_weekend_days_included_when_serving_weekends(self):
        cfg = build_adhoc_client_config(
            'Acme', ['rice'], serve_weekends=True,
        )
        assert 'saturday' in cfg.theme_map
        assert cfg.serve_weekends is True

    def test_unknown_categories_are_dropped(self):
        cfg = build_adhoc_client_config('Acme', ['rice', 'not_a_slot'])
        assert cfg.active_slots == ['rice']

    def test_blank_name_falls_back_to_a_label(self):
        assert build_adhoc_client_config('   ', ['rice']).name == 'New Client'

    def test_single_adhoc_counter(self):
        cfg = build_adhoc_client_config('Acme', ['rice'])
        assert cfg.counter_name == DEFAULT_COUNTER_NAME
        assert cfg.counter_names == [DEFAULT_COUNTER_NAME]

    def test_no_recognised_category_is_a_value_error(self):
        with pytest.raises(ValueError, match='at least one known menu slot'):
            build_adhoc_client_config('Acme', ['nonsense'])

    def test_empty_categories_is_a_value_error(self):
        with pytest.raises(ValueError):
            build_adhoc_client_config('Acme', [])

    def test_garbage_slot_count_falls_back_to_one(self):
        cfg = build_adhoc_client_config('Acme', ['rice'], {'rice': 'two'})
        assert cfg.slot_counts['rice'] == 1

    def test_defaults_match_the_stored_path(self):
        cfg = build_adhoc_client_config('Acme', ['rice'])
        assert cfg.item_cooldown_days == DEFAULT_ITEM_COOLDOWN_DAYS
        assert cfg.city == ''
        assert cfg.source_pools == []


# ---------------------------------------------------------------------------
# /estimate-plan
# ---------------------------------------------------------------------------

class TestEstimatePlanValidation:
    """Input validation happens before any solver or Supabase work, so
    these cases need no fixtures."""

    def test_missing_categories_returns_400(self, client):
        resp = client.post('/api/v1/estimate-plan',
                           json={'client_name': 'Acme'})
        assert resp.status_code == 400
        assert 'categories' in resp.get_json()['error']

    def test_unknown_categories_only_returns_400(self, client):
        resp = client.post('/api/v1/estimate-plan',
                           json=_body(categories=['nope']))
        assert resp.status_code == 400

    def test_unknown_client_name_is_not_rejected(self, client, monkeypatch):
        """The defining behaviour: the name is a label, not a lookup key.

        A name that exists in no ``clients`` row must still plan — that's
        the whole point of estimating for a prospect. Asserted by proving
        the request gets past validation into the solver pipeline (which
        we stub) rather than 400-ing on an unknown client.
        """
        import api.app as api_app

        captured = {}

        def _fake_pipeline(inputs, extra=None):
            captured['client_name'] = inputs.client_name
            captured['counter'] = inputs.counter_name
            captured['slots'] = inputs.cfg.active_base_slots
            return {'success': True, 'solution': {}, **(extra or {})}, 200

        monkeypatch.setattr(api_app, '_plan_pipeline', _fake_pipeline)
        resp = client.post('/api/v1/estimate-plan',
                           json=_body(client_name='Nobody Ltd'))
        assert resp.status_code == 200
        assert resp.get_json()['estimate'] is True
        assert captured['client_name'] == 'Nobody Ltd'
        assert 'rice' in captured['slots']


class TestEstimatePlanIsolation:
    """The estimator must not read stored client config or history."""

    def test_no_supabase_access(self, monkeypatch):
        import api.app as api_app

        def _boom(*_a, **_k):
            raise AssertionError(
                "the estimator path must not touch Supabase"
            )

        monkeypatch.setattr('src.db.get_supabase', _boom)
        monkeypatch.setattr(api_app, '_get_client_loader', _boom)
        monkeypatch.setattr(api_app, '_build_history_context', _boom)

        with app.test_request_context():
            inputs = api_app._prepare_estimate_inputs(_body())

        assert inputs.client_name == 'Acme Corp'

    def test_history_is_empty(self, monkeypatch):
        """No served history exists for a prospect, so nothing is banned."""
        import api.app as api_app

        monkeypatch.setattr(api_app, '_build_history_context', lambda *a, **k: (
            pytest.fail("history must not be loaded for an estimate")
        ))
        with app.test_request_context():
            inputs = api_app._prepare_estimate_inputs(_body())

        assert inputs.banned == {}
        assert inputs.rb_ban == {}
        assert not inputs.recent_sigs

    def test_per_client_rules_are_not_applied(self, monkeypatch):
        """A typed name must not pull in another client's bans.

        'Tekion' has per-client rules in ``client_rules.json`` (a mushroom
        ingredient ban, a nonveg weekday restriction). Estimating under
        that name must not inherit them.
        """
        import api.app as api_app

        with app.test_request_context():
            inputs = api_app._prepare_estimate_inputs(
                _body(client_name='Tekion', categories=[
                    *ESTIMATE_CATEGORIES, 'nonveg_main',
                ]),
            )

        rule_names = {getattr(r, 'name', '') for r in inputs.rules}
        assert 'tekion_no_mushroom' not in rule_names
        assert 'tekion_nonveg_mwf' not in rule_names
        # …and the generic rule set is still there.
        assert 'item_cooldown_20d' in rule_names
        assert inputs.skip_cells == set()

    def test_shared_rule_objects_are_not_mutated(self, monkeypatch):
        """The generic rules are process-wide singletons; the estimator
        passes them through without overriding cooldowns, so a concurrent
        request can't observe an edit."""
        import api.app as api_app

        generic = api_app._get_menu_rules()
        before = {
            id(r): getattr(r, 'cooldown_days', None) for r in generic
        }
        with app.test_request_context():
            api_app._prepare_estimate_inputs(_body())
        after = {id(r): getattr(r, 'cooldown_days', None) for r in generic}
        assert before == after


class TestEstimatePlanWindow:
    def test_weekends_skipped_unless_serving_them(self):
        import api.app as api_app

        # 2026-09-11 is a Friday; a 3-day plan skips Sat/Sun.
        with app.test_request_context():
            inputs = api_app._prepare_estimate_inputs(
                _body(start_date='2026-09-11', num_days=3),
            )
        assert inputs.weekday_dates == [
            dt.date(2026, 9, 11), dt.date(2026, 9, 14), dt.date(2026, 9, 15),
        ]

    def test_weekend_serving_uses_consecutive_days(self):
        import api.app as api_app

        with app.test_request_context():
            inputs = api_app._prepare_estimate_inputs(
                _body(start_date='2026-09-11', num_days=3,
                      serve_weekends=True),
            )
        assert inputs.weekday_dates == [
            dt.date(2026, 9, 11), dt.date(2026, 9, 12), dt.date(2026, 9, 13),
        ]

    def test_num_days_is_clamped(self):
        import api.app as api_app

        with app.test_request_context():
            inputs = api_app._prepare_estimate_inputs(_body(num_days=999))
        from api.config import MAX_NUM_DAYS
        assert inputs.num_days == MAX_NUM_DAYS


class TestEstimateRegenerate:
    def test_requires_base_plan(self, client):
        resp = client.post('/api/v1/estimate-regenerate', json=_body())
        assert resp.status_code == 400
        assert 'base_plan' in resp.get_json()['error']

    def test_requires_replace_slots(self, client):
        resp = client.post(
            '/api/v1/estimate-regenerate',
            json=_body(base_plan={'2026-09-07': {'rice': 'jeera_rice'}}),
        )
        assert resp.status_code == 400
        assert 'replace_slots' in resp.get_json()['error']

    def test_marks_the_response_as_an_estimate(self, client, monkeypatch):
        import api.app as api_app

        monkeypatch.setattr(
            api_app, '_regenerate_pipeline',
            lambda inputs, data, extra=None: (
                {'success': True, 'solution': {}, **(extra or {})}, 200
            ),
        )
        resp = client.post('/api/v1/estimate-regenerate', json=_body(
            base_plan={'2026-09-07': {'rice': 'jeera_rice'}},
            replace_slots={'2026-09-07': ['rice']},
        ))
        assert resp.status_code == 200
        assert resp.get_json()['estimate'] is True
