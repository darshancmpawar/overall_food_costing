"""Tests for HistoryManager."""

import datetime as dt
import pandas as pd
import pytest

from src.constants import DEFAULT_COUNTER_NAME
from src.history.history_manager import (
    HistoryManager,
    counter_signature_prefix,
    expand_menu_rows,
    split_signature_counter,
)
from tests.fake_supabase import FakeSupabase


def _make_long_df():
    """Create synthetic long history."""
    return pd.DataFrame([
        {'service_date': '2026-03-01', 'slot': 'rice', 'item_base': 'jeera rice', 'client_name': 'Rippling'},
        {'service_date': '2026-03-02', 'slot': 'rice', 'item_base': 'lemon rice', 'client_name': 'Rippling'},
        {'service_date': '2026-03-03', 'slot': 'bread', 'item_base': 'rice roti', 'client_name': 'Rippling'},
        {'service_date': '2026-03-10', 'slot': 'rice', 'item_base': 'pulao', 'client_name': 'Stripe'},
        {'service_date': '2026-03-15', 'slot': 'white_rice', 'item_base': 'steamed rice', 'client_name': 'Rippling'},
    ])


def _make_weeks_df():
    return pd.DataFrame([
        {'week_start': '2026-03-02', 'week_signature': 'sig1', 'client_name': 'Rippling'},
        {'week_start': '2026-02-15', 'week_signature': 'sig2', 'client_name': 'Rippling'},
    ])


class TestHistoryManager:
    def test_load_from_dataframes(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df(), _make_weeks_df())
        assert hm._long is not None
        assert hm._weeks is not None

    def test_empty_history(self):
        hm = HistoryManager()
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(dates)
        assert bans[dates[0]] == set()

    def test_banned_items(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(dates, cooldown_days=20)
        # Items from March 1-19 within 20 day window of March 20
        assert 'jeera rice' in bans[dates[0]]
        assert 'lemon rice' in bans[dates[0]]

    def test_banned_items_excludes_const_slots(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(dates, cooldown_days=20, const_slots=['white_rice'])
        assert 'steamed rice' not in bans[dates[0]]

    def test_banned_items_excludes_repeatable(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        bans = hm.banned_items_by_date(
            dates, cooldown_days=20, repeatable_items={'jeera rice'}
        )
        assert 'jeera rice' not in bans[dates[0]]

    def test_filter_by_client(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df(), _make_weeks_df())
        filtered = hm.filter_by_client('Rippling')
        dates = [dt.date(2026, 3, 20)]
        bans = filtered.banned_items_by_date(dates, cooldown_days=20)
        assert 'pulao' not in bans[dates[0]]  # Stripe item

    def test_recent_week_signatures(self):
        hm = HistoryManager().load_from_dataframes(weeks_df=_make_weeks_df())
        sigs = hm.recent_week_signatures(dt.date(2026, 3, 16), cooldown_days=30)
        assert 'sig1' in sigs
        assert 'sig2' in sigs

    def test_ricebread_ban(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 10)]
        result = hm.ricebread_ban_by_date(dates, ricebread_items={'rice roti'}, gap_days=10)
        assert result[dates[0]] is True

    def test_ricebread_no_ban(self):
        hm = HistoryManager().load_from_dataframes(_make_long_df())
        dates = [dt.date(2026, 3, 20)]
        result = hm.ricebread_ban_by_date(dates, ricebread_items={'rice roti'}, gap_days=10)
        assert result[dates[0]] is False

    def test_compute_week_signature(self):
        plan = {
            dt.date(2026, 3, 16): {'rice': 'jeera rice', 'bread': 'naan'},
            dt.date(2026, 3, 17): {'rice': 'lemon rice', 'bread': 'roti'},
        }
        dates = [dt.date(2026, 3, 16), dt.date(2026, 3, 17)]
        sig = HistoryManager.compute_week_signature(plan, dates)
        assert '2026-03-16' in sig
        assert 'rice=jeera rice' in sig

    def test_parse_signature(self):
        sig = '2026-03-16|rice=jeera rice|bread=naan|2026-03-17|rice=lemon rice'
        result = HistoryManager.parse_signature_to_expected_map(sig)
        assert result[('2026-03-16', 'rice')] == 'jeera rice'
        assert result[('2026-03-17', 'rice')] == 'lemon rice'

    def test_save_writes_one_row_per_day_with_counter_menu(self):
        """save() writes a single (client, day) row whose ``menu`` jsonb
        nests the counter's picks, plus a counter-prefixed week
        signature."""
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        plan = {
            dt.date(2026, 3, 16): {'rice': 'jeera rice', 'bread': 'naan'},
        }
        dates = [dt.date(2026, 3, 16)]

        hm = HistoryManager()
        hm.save(plan, dates, 'Rippling', dt.date(2026, 3, 16), 'test_sig',
                supabase_client=fake, counter_name='Counter 1')

        rows = fake.rows('menu_history')
        assert len(rows) == 1
        assert rows[0]['client_name'] == 'Rippling'
        assert rows[0]['menu']['counters']['Counter 1'] == {
            'rice': 'jeera rice', 'bread': 'naan',
        }
        sigs = fake.rows('week_signatures')
        assert len(sigs) == 1
        assert sigs[0]['week_signature'] == 'counter=counter 1|test_sig'

    def test_save_overwrites_the_same_counter_and_day(self):
        """A second save for the same (client, counter, day) replaces the
        first save's menu rather than accumulating rows."""
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        dates = [dt.date(2026, 3, 16)]
        hm = HistoryManager()

        hm.save({dt.date(2026, 3, 16): {'rice': 'jeera rice'}},
                dates, 'Rippling', dt.date(2026, 3, 16),
                'sig_a', supabase_client=fake)
        hm.save({dt.date(2026, 3, 16): {'rice': 'biryani'}},
                dates, 'Rippling', dt.date(2026, 3, 16),
                'sig_b', supabase_client=fake)

        rows = fake.rows('menu_history')
        assert len(rows) == 1
        assert rows[0]['menu']['counters'][DEFAULT_COUNTER_NAME] == {
            'rice': 'biryani',
        }
        # Signature row also overwrites, not appends.
        sigs = fake.rows('week_signatures')
        assert len(sigs) == 1
        assert sigs[0]['week_signature'].endswith('sig_b')

    def test_save_merges_alongside_other_counters(self):
        """Saving one counter must not drop another counter's picks for
        the same day — they share a single menu_history row."""
        fake = FakeSupabase(seed={'menu_history': [], 'week_signatures': []})
        dates = [dt.date(2026, 3, 16)]
        hm = HistoryManager()

        hm.save({dt.date(2026, 3, 16): {'rice': 'jeera rice'}},
                dates, 'Amadeus', dt.date(2026, 3, 16), 'sig_south',
                supabase_client=fake, counter_name='South')
        hm.save({dt.date(2026, 3, 16): {'rice': 'kashmiri pulao'}},
                dates, 'Amadeus', dt.date(2026, 3, 16), 'sig_north',
                supabase_client=fake, counter_name='North')

        rows = fake.rows('menu_history')
        assert len(rows) == 1
        counters = rows[0]['menu']['counters']
        assert counters['South'] == {'rice': 'jeera rice'}
        assert counters['North'] == {'rice': 'kashmiri pulao'}
        # One signature per counter for the week.
        sigs = sorted(r['week_signature'] for r in fake.rows('week_signatures'))
        assert sigs == ['counter=north|sig_north', 'counter=south|sig_south']

    def test_save_promotes_a_legacy_flat_menu_before_merging(self):
        """A hand-written / pre-migration ``{slot: item}`` row is moved
        under the default counter rather than silently discarded."""
        fake = FakeSupabase(seed={
            'menu_history': [{
                'client_name': 'Amadeus',
                'service_date': '2026-03-16',
                'menu': {'rice': 'legacy rice'},
            }],
            'week_signatures': [],
        })
        HistoryManager().save(
            {dt.date(2026, 3, 16): {'rice': 'new rice'}},
            [dt.date(2026, 3, 16)], 'Amadeus', dt.date(2026, 3, 16),
            'sig', supabase_client=fake, counter_name='South',
        )
        counters = fake.rows('menu_history')[0]['menu']['counters']
        assert counters[DEFAULT_COUNTER_NAME] == {'rice': 'legacy rice'}
        assert counters['South'] == {'rice': 'new rice'}

    def test_save_only_overwrites_for_matching_client(self):
        """Re-saving for Rippling must not touch Stripe's history row
        for the same date — writes are keyed on (client, date).
        """
        fake = FakeSupabase(seed={
            'menu_history': [
                {'client_name': 'Stripe', 'service_date': '2026-03-16',
                 'menu': {'counters': {'Counter 1': {'rice': 'stripe rice'}}}},
            ],
            'week_signatures': [],
        })

        hm = HistoryManager()
        hm.save({dt.date(2026, 3, 16): {'rice': 'jeera rice'}},
                [dt.date(2026, 3, 16)], 'Rippling', dt.date(2026, 3, 16),
                'sig_a', supabase_client=fake)
        clients = {r['client_name'] for r in fake.rows('menu_history')}
        assert clients == {'Stripe', 'Rippling'}

    def test_save_requires_supabase_client(self):
        hm = HistoryManager()
        with pytest.raises(ValueError):
            hm.save({}, [], 'Rippling', dt.date(2026, 3, 16), 'sig',
                    supabase_client=None)


class TestExpandMenuRows:
    def test_expands_counters_envelope(self):
        out = expand_menu_rows([{
            'client_name': 'Amadeus',
            'service_date': '2026-03-16',
            'menu': {'version': 2, 'counters': {
                'South': {'rice': 'bisi bele bhat'},
                'North': {'rice': 'kashmiri pulao'},
            }},
        }])
        assert {(r['counter_name'], r['item_base']) for r in out} == {
            ('South', 'bisi bele bhat'), ('North', 'kashmiri pulao'),
        }

    def test_bare_map_is_read_as_the_default_counter(self):
        out = expand_menu_rows([{
            'client_name': 'Cargil',
            'service_date': '2026-03-16',
            'menu': {'rice': 'jeera rice'},
        }])
        assert out == [{
            'client_name': 'Cargil',
            'service_date': '2026-03-16',
            'counter_name': DEFAULT_COUNTER_NAME,
            'slot': 'rice',
            'item_base': 'jeera rice',
        }]

    def test_json_string_menu_is_parsed(self):
        out = expand_menu_rows([{
            'client_name': 'Cargil',
            'service_date': '2026-03-16',
            'menu': '{"counters": {"Counter 1": {"rice": "pulao"}}}',
        }])
        assert out[0]['item_base'] == 'pulao'

    def test_unusable_menu_is_skipped(self):
        assert expand_menu_rows([
            {'client_name': 'X', 'service_date': '2026-03-16', 'menu': None},
            {'client_name': 'X', 'service_date': '2026-03-16', 'menu': 'oops'},
        ]) == []


class TestCounterScoping:
    def _hm(self):
        return HistoryManager().load_from_menu_rows(
            menu_rows=[{
                'client_name': 'Amadeus',
                'service_date': '2026-03-16',
                'menu': {'counters': {
                    'South': {'rice': 'bisi bele bhat'},
                    'North': {'rice': 'kashmiri pulao'},
                }},
            }],
            weeks_rows=[
                {'week_start': '2026-03-16',
                 'week_signature': 'counter=south|sig_south'},
                {'week_start': '2026-03-16',
                 'week_signature': 'counter=north|sig_north'},
                {'week_start': '2026-03-16', 'week_signature': 'legacy_sig'},
            ],
        )

    def test_cooldowns_are_scoped_to_one_serving_line(self):
        """A dish served on the North line must not block the South line
        — otherwise a multi-counter client burns its pools N times over
        and the week goes infeasible."""
        bans = self._hm().filter_by_counter('South').banned_items_by_date(
            [dt.date(2026, 3, 20)], cooldown_days=20,
        )
        assert 'bisi bele bhat' in bans[dt.date(2026, 3, 20)]
        assert 'kashmiri pulao' not in bans[dt.date(2026, 3, 20)]

    def test_signatures_are_scoped_to_one_serving_line(self):
        sigs = self._hm().filter_by_counter('South').recent_week_signatures(
            dt.date(2026, 3, 23), cooldown_days=30,
        )
        assert 'counter=south|sig_south' in sigs
        assert 'counter=north|sig_north' not in sigs

    def test_legacy_signatures_apply_to_every_counter(self):
        """Prefix-less rows predate counters, so there's no evidence they
        belong to a different line."""
        sigs = self._hm().filter_by_counter('North').recent_week_signatures(
            dt.date(2026, 3, 23), cooldown_days=30,
        )
        assert 'legacy_sig' in sigs

    def test_signature_prefix_survives_the_signature_parser(self):
        """The week-signature cooldown rule parses stored signatures, so
        the prefix must not shift the (date, slot) map."""
        body = '2026-03-16|rice=jeera rice'
        prefixed = counter_signature_prefix('South') + body
        assert (
            HistoryManager.parse_signature_to_expected_map(prefixed)
            == HistoryManager.parse_signature_to_expected_map(body)
        )

    def test_split_signature_counter(self):
        assert split_signature_counter('counter=south|2026-03-16|rice=x') == (
            'south', '2026-03-16|rice=x',
        )
        assert split_signature_counter('2026-03-16|rice=x') == (
            None, '2026-03-16|rice=x',
        )


class TestLoadSavedPlan:
    """Verify the readback path used by /api/v1/saved-plan."""

    def _seed(self, rows):
        return FakeSupabase(seed={'menu_history': rows})

    @staticmethod
    def _row(client, iso, counters):
        return {
            'client_name': client,
            'service_date': iso,
            'menu': {'version': 2, 'counters': counters},
        }

    def test_returns_empty_when_no_rows(self):
        fake = self._seed([])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling', [dt.date(2026, 3, 16)],
        )
        assert out == {}

    def test_returns_saved_items_grouped_by_date(self):
        fake = self._seed([
            self._row('Rippling', '2026-03-16', {
                DEFAULT_COUNTER_NAME: {'rice': 'jeera_rice', 'bread': 'naan'},
            }),
            self._row('Rippling', '2026-03-17', {
                DEFAULT_COUNTER_NAME: {'rice': 'lemon_rice'},
            }),
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling',
            [dt.date(2026, 3, 16), dt.date(2026, 3, 17)],
        )
        assert out[dt.date(2026, 3, 16)] == {
            'rice': 'jeera_rice', 'bread': 'naan',
        }
        assert out[dt.date(2026, 3, 17)] == {'rice': 'lemon_rice'}

    def test_returns_only_the_requested_counter(self):
        fake = self._seed([
            self._row('Amadeus', '2026-03-16', {
                'South': {'rice': 'bisi_bele_bhat'},
                'North': {'rice': 'kashmiri_pulao'},
            }),
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Amadeus', [dt.date(2026, 3, 16)], counter_name='North',
        )
        assert out[dt.date(2026, 3, 16)] == {'rice': 'kashmiri_pulao'}

    def test_counter_match_is_case_insensitive(self):
        fake = self._seed([
            self._row('Amadeus', '2026-03-16', {'South': {'rice': 'x'}}),
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Amadeus', [dt.date(2026, 3, 16)], counter_name='south',
        )
        assert out[dt.date(2026, 3, 16)] == {'rice': 'x'}

    def test_unsaved_counter_reads_as_not_saved(self):
        """A day another line already covered must not read as saved for
        this line, or Generate would show an empty plan as "from
        history"."""
        fake = self._seed([
            self._row('Amadeus', '2026-03-16', {'South': {'rice': 'x'}}),
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Amadeus', [dt.date(2026, 3, 16)], counter_name='North',
        )
        assert out == {}

    def test_legacy_flat_menu_reads_as_the_default_counter(self):
        fake = self._seed([{
            'client_name': 'Cargil', 'service_date': '2026-03-16',
            'menu': {'rice': 'jeera_rice'},
        }])
        out = HistoryManager.load_saved_plan(
            fake, 'Cargil', [dt.date(2026, 3, 16)],
            counter_name=DEFAULT_COUNTER_NAME,
        )
        assert out[dt.date(2026, 3, 16)] == {'rice': 'jeera_rice'}

    def test_filters_other_clients(self):
        fake = self._seed([
            self._row('Stripe', '2026-03-16', {
                DEFAULT_COUNTER_NAME: {'rice': 'stripe_rice'},
            }),
            self._row('Rippling', '2026-03-16', {
                DEFAULT_COUNTER_NAME: {'rice': 'rippling_rice'},
            }),
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling', [dt.date(2026, 3, 16)],
        )
        assert out[dt.date(2026, 3, 16)] == {'rice': 'rippling_rice'}

    def test_only_returns_dates_with_rows(self):
        """Caller distinguishes 'fully saved' from 'partial' by checking
        len(out) vs len(requested_dates). Don't pad missing dates with
        empty dicts."""
        fake = self._seed([
            self._row('Rippling', '2026-03-16', {
                DEFAULT_COUNTER_NAME: {'rice': 'jeera_rice'},
            }),
        ])
        out = HistoryManager.load_saved_plan(
            fake, 'Rippling',
            [dt.date(2026, 3, 16), dt.date(2026, 3, 17)],
        )
        assert list(out.keys()) == [dt.date(2026, 3, 16)]

    def test_empty_dates_is_noop(self):
        fake = self._seed([
            self._row('Rippling', '2026-03-16', {
                DEFAULT_COUNTER_NAME: {'rice': 'jeera_rice'},
            }),
        ])
        assert HistoryManager.load_saved_plan(fake, 'Rippling', []) == {}

    def test_requires_supabase_client(self):
        with pytest.raises(ValueError):
            HistoryManager.load_saved_plan(None, 'Rippling', [dt.date(2026, 3, 16)])
