"""Tests for the plate-weight cap and the bread serving-weight fix.

The two travel together: bread carried a 1000 g serving weight on 18
chapatti rows, which alone outweighed a whole plate, so a weight cap was
meaningless until the weights were trustworthy.
"""

import datetime as dt

import pandas as pd
import pytest

from src.constants import (
    COURSE_SERVING_GRAMMAGE_KG,
    PLATE_CAP_GRAMS,
    PLATE_CAP_SLOT_EXEMPTION,
)
from src.menu_rules.base_menu_rule import DiagnoseContext, MenuRuleType
from src.menu_rules.plate_weight_rule import PlateWeightMenuRule, _grams
from src.preprocessor.data_cleanser import DataCleanser
from src.solver.menu_solver import SolverConfig

pytest.importorskip("ortools", reason="OR-Tools not installed")
from ortools.sat.python import cp_model  # noqa: E402


# ---------------------------------------------------------------------------
# Serving-weight normalisation (DataCleanser)
# ---------------------------------------------------------------------------

def _ontology(rows):
    return pd.DataFrame(rows)


class TestCourseGrammageNormalisation:
    def test_bread_is_forced_to_60g(self):
        """The upstream unit slip: a kilogram of chapatti per serving."""
        df = DataCleanser(_ontology([
            {'item': 'plain_chapatti', 'course_type': 'bread',
             'cost_per_kg': 2.0, 'grammage_per_serving': 1.00},
            {'item': 'akki_roti', 'course_type': 'bread',
             'cost_per_kg': 4.5, 'grammage_per_serving': 0.06},
        ])).clean()
        assert list(df['grammage_per_serving']) == [0.06, 0.06]

    def test_missing_bread_weight_is_filled(self):
        df = DataCleanser(_ontology([
            {'item': 'tomato_thyme_loaf', 'course_type': 'bread',
             'cost_per_kg': 0.0, 'grammage_per_serving': 0.0},
        ])).clean()
        assert df.iloc[0]['grammage_per_serving'] == 0.06

    def test_other_courses_are_untouched(self):
        """Only courses named in the constant are normalised — a 300 g
        biryani is a real portion, not a data error."""
        df = DataCleanser(_ontology([
            {'item': 'dum_veg_biriyani', 'course_type': 'rice',
             'cost_per_kg': 65.0, 'grammage_per_serving': 0.30},
            {'item': 'curd', 'course_type': 'curd_side',
             'cost_per_kg': 54.0, 'grammage_per_serving': 0.05},
        ])).clean()
        assert list(df['grammage_per_serving']) == [0.30, 0.05]

    def test_no_grammage_column_is_a_noop(self):
        """An ontology with no cost data still cleans."""
        df = DataCleanser(_ontology([
            {'item': 'plain_chapatti', 'course_type': 'bread'},
        ])).clean()
        assert 'grammage_per_serving' not in df.columns

    def test_bread_is_the_only_normalised_course(self):
        assert set(COURSE_SERVING_GRAMMAGE_KG) == {'bread'}
        assert COURSE_SERVING_GRAMMAGE_KG['bread'] == 0.06


# ---------------------------------------------------------------------------
# Weight parsing
# ---------------------------------------------------------------------------

class TestGramsParsing:
    @pytest.mark.parametrize("value,expected", [
        (0.06, 60), (1.0, 1000), (0.045, 45), ("0.06", 60),
        (None, 0), ("", 0), ("n/a", 0), (float("nan"), 0), (-0.5, 0), (0, 0),
    ])
    def test_parses_or_degrades_to_zero(self, value, expected):
        assert _grams(value) == expected


# ---------------------------------------------------------------------------
# The CP-SAT constraint
# ---------------------------------------------------------------------------

class _Cell:
    """Minimal stand-in for the solver's private _Cell."""

    def __init__(self, d_idx, grams_options, model, tag):
        self.d_idx = d_idx
        self.x_vars = [
            model.NewBoolVar(f'x_{tag}_{i}') for i in range(len(grams_options))
        ]
        self.cand_rows = [
            {'grammage_per_serving': g / 1000.0} for g in grams_options
        ]
        model.Add(sum(self.x_vars) == 1)


def _solve(cells_spec, max_kg=1.0, const_grams=0, days=1):
    """Build a toy model, apply the rule, and return the chosen grams/day."""
    model = cp_model.CpModel()
    cells = [
        _Cell(d, options, model, f'{d}_{i}')
        for d in range(days)
        for i, options in enumerate(cells_spec)
    ]
    cfg = SolverConfig(const_slot_grams=const_grams)
    rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': max_kg})
    rule.apply(model, {}, None, {
        'cells': cells, 'dates': list(range(days)), 'cfg': cfg,
    })
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    totals = {}
    for cell in cells:
        for var, row in zip(cell.x_vars, cell.cand_rows):
            if solver.Value(var):
                totals[cell.d_idx] = totals.get(cell.d_idx, 0) + int(
                    round(row['grammage_per_serving'] * 1000)
                )
    return totals


class TestPlateWeightConstraint:
    def test_forces_the_light_option_when_the_heavy_one_would_bust(self):
        # 900 g fixed + a choice of 80 g or 300 g: only 80 g fits 1 kg.
        totals = _solve([[900], [80, 300]], max_kg=1.0)
        assert totals == {0: 980}

    def test_allows_the_heavy_option_under_a_looser_cap(self):
        totals = _solve([[900], [80, 300]], max_kg=1.3)
        assert totals is not None
        assert totals[0] <= 1300

    def test_unreachable_day_is_left_unconstrained(self):
        """The lightest plate here is 1200 g against a 1 kg cap. Blocking
        it would fail the whole plan, so the day is left alone and its
        portions are trimmed later instead — see test_plate_trim.py."""
        totals = _solve([[900], [300]], max_kg=1.0)
        assert totals == {0: 1200}

    def test_constant_accompaniments_count_against_the_cap(self):
        """Papad and pickle are on the plate even though the solver never
        picks them, so they eat into the budget."""
        assert _solve([[900], [80, 300]], max_kg=1.0, const_grams=0) == {0: 980}
        # With 40 g of accompaniments, 900 + 80 + 40 = 1020 > 1000, so no
        # choice fits and the day goes to the trimmer unconstrained.
        assert _solve([[900], [80, 300]], max_kg=1.0, const_grams=40) is not None

    def test_cap_applies_per_day_not_across_the_plan(self):
        totals = _solve([[900], [80, 300]], max_kg=1.0, days=3)
        assert totals == {0: 980, 1: 980, 2: 980}

    def test_items_without_a_weight_are_ignored(self):
        """A weightless row must not make the plan infeasible."""
        totals = _solve([[0], [80]], max_kg=1.0)
        assert totals == {0: 80}

    def test_cap_below_the_accompaniments_constrains_nothing(self):
        """A cap smaller than the fixed accompaniments is a
        misconfiguration, but it must not fail the solve — the day is
        left unconstrained and trimming takes it as far as it can."""
        totals = _solve([[80]], max_kg=0.01, const_grams=20)
        assert totals == {0: 80}

    def test_no_cells_is_a_noop(self):
        rule = PlateWeightMenuRule({'name': 'cap'})
        rule.apply(cp_model.CpModel(), {}, None, {'cells': [], 'dates': []})


class TestPlateWeightConfig:
    def test_no_max_kg_defers_to_the_per_day_policy(self):
        """Without an explicit override the cap varies by day: 1 kg
        normally, 1.1 kg on a biryani day, none past 15 slots."""
        rule = PlateWeightMenuRule({'name': 'cap'})
        assert rule.max_kg is None
        assert rule.max_grams is None
        assert rule.cap_for('mix', 15) == PLATE_CAP_GRAMS
        assert rule.cap_for('biryani', 15) == 1200
        assert rule.cap_for('mix', PLATE_CAP_SLOT_EXEMPTION + 1) == 1050
        assert rule.cap_for('biryani', 19) == 1300

    def test_explicit_max_kg_overrides_the_policy(self):
        """One ceiling on every day, whatever the theme or slot count."""
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 1.2})
        assert rule.max_grams == 1200
        assert rule.cap_for('mix', 15) == 1200
        assert rule.cap_for('biryani', 15) == 1200
        assert rule.cap_for('mix', PLATE_CAP_SLOT_EXEMPTION + 1) == 1200

    def test_rule_type(self):
        assert PlateWeightMenuRule({'name': 'c'}).rule_type is MenuRuleType.PLATE_WEIGHT

    @pytest.mark.parametrize("bad", [0, -1, -0.5])
    def test_non_positive_cap_is_invalid(self, bad):
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': bad})
        assert rule.validate_config() is False
        assert rule.validation_errors()

    def test_loader_registers_the_type(self):
        from src.menu_rules.menu_rule_loader import MenuRuleLoader

        rules = MenuRuleLoader().load_from_dict({'rules': [
            {'name': 'plate_max_1kg', 'type': 'plate_weight', 'max_kg': 1.0},
        ]})
        assert len(rules) == 1
        assert isinstance(rules[0], PlateWeightMenuRule)

    def test_shipped_config_carries_the_rule(self):
        """The live rule set must include the cap, or nothing enforces it."""
        import json

        from api.config import MENU_RULES_CONFIG_PATH

        with open(MENU_RULES_CONFIG_PATH) as fh:
            names = {r['type'] for r in json.load(fh)['rules']}
        assert 'plate_weight' in names


# ---------------------------------------------------------------------------
# Pre-flight diagnostics
# ---------------------------------------------------------------------------

def _pool(*grams):
    return pd.DataFrame([
        {'item': f'item_{i}', 'grammage_per_serving': g / 1000.0}
        for i, g in enumerate(grams)
    ])


def _ctx(pools, day_types, *, const_grams=0, slot_counts=None, rules=None):
    cfg = SolverConfig(const_slot_grams=const_grams)

    class _Cfg:
        slot_counts = {}

    client = _Cfg()
    client.slot_counts = slot_counts or {}
    return DiagnoseContext(
        pools=pools,
        dates=list(day_types),
        day_types=day_types,
        cfg=cfg,
        df=pd.DataFrame(),
        banned_by_date={},
        ricebread_ban_day={},
        skip_cells=set(),
        client_cfg=client,
        active_base_slots=list(pools),
        rules=list(rules or []),
    )


class TestPlateWeightDiagnostics:
    def test_warns_when_the_lightest_plate_busts_the_cap(self):
        """A warning, not an error: the day still plans, with trimmed
        portions. The operator needs to know which days and by how much,
        not to be stopped."""
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 1.0})
        day = dt.date(2026, 9, 9)
        diags = rule.diagnose(_ctx(
            {'rice': _pool(300, 400), 'veg_gravy': _pool(800)},
            {day: 'biryani'},
        ))
        assert len(diags) == 1
        assert diags[0].severity.value == 'warning'
        assert 'Biryani' in diags[0].message
        assert diags[0].affected['min_plate_grams'] == 1100
        assert diags[0].affected['over_by_grams'] == 100

    def test_never_blocks_a_plan(self):
        """No plate-weight diagnostic may be an error — the pre-flight
        gate turns errors into a 422 and this rule always has a way
        forward."""
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 0.1})
        diags = rule.diagnose(_ctx(
            {'rice': _pool(300), 'veg_gravy': _pool(800)},
            {dt.date(2026, 9, 9): 'biryani'},
        ))
        assert diags
        assert all(d.severity.value != 'error' for d in diags)

    def test_silent_when_the_plate_fits(self):
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 1.0})
        diags = rule.diagnose(_ctx(
            {'rice': _pool(120), 'veg_gravy': _pool(100)},
            {dt.date(2026, 9, 7): 'mix'},
        ))
        assert diags == []

    def test_accompaniments_count_towards_the_floor(self):
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 1.0})
        pools = {'rice': _pool(500), 'veg_gravy': _pool(490)}
        assert rule.diagnose(_ctx(pools, {dt.date(2026, 9, 7): 'mix'})) == []
        over = rule.diagnose(_ctx(
            pools, {dt.date(2026, 9, 7): 'mix'}, const_grams=20,
        ))
        assert len(over) == 1
        assert over[0].affected['min_plate_grams'] == 1010

    def test_slot_counts_multiply_the_floor(self):
        """A counter serving two veg dry carries two portions of it."""
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 1.0})
        pools = {'veg_dry': _pool(600)}
        assert rule.diagnose(_ctx(pools, {dt.date(2026, 9, 7): 'mix'})) == []
        diags = rule.diagnose(_ctx(
            pools, {dt.date(2026, 9, 7): 'mix'}, slot_counts={'veg_dry': 2},
        ))
        assert len(diags) == 1
        assert diags[0].affected['min_plate_grams'] == 1200

    def test_one_diagnostic_per_theme_not_per_date(self):
        """A 10-day plan has several biryani days that all fail alike."""
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 1.0})
        day_types = {
            dt.date(2026, 9, 9): 'biryani',
            dt.date(2026, 9, 16): 'biryani',
            dt.date(2026, 9, 23): 'biryani',
        }
        diags = rule.diagnose(_ctx({'rice': _pool(1200)}, day_types))
        assert len(diags) == 1

    def test_sibling_filters_are_projected(self):
        """The theme filter is what makes a biryani day heavy, so the
        floor has to be measured after it runs — otherwise the check
        passes and the solver fails instead."""
        from src.menu_rules.theme_rules import ThemeSlotFilterRule

        rice = pd.DataFrame([
            {'item': 'jeera_rice', 'grammage_per_serving': 0.08,
             'is_mixedveg_biryani': 0},
            {'item': 'dum_biryani', 'grammage_per_serving': 0.30,
             'is_mixedveg_biryani': 1},
        ])
        theme = ThemeSlotFilterRule({'name': 'themes', 'exempt_slots': []})
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 0.2})
        day = dt.date(2026, 9, 9)

        # Unfiltered the floor is 80 g and fits; the biryani filter leaves
        # only the 300 g option, which does not.
        assert rule.diagnose(_ctx({'rice': rice}, {day: 'mix'})) == []
        blocked = rule.diagnose(
            _ctx({'rice': rice}, {day: 'biryani'}, rules=[theme])
        )
        assert len(blocked) == 1
        assert blocked[0].affected['min_plate_grams'] == 300

    def test_pools_without_weights_produce_nothing(self):
        rule = PlateWeightMenuRule({'name': 'cap', 'max_kg': 0.001})
        pools = {'rice': pd.DataFrame([{'item': 'x'}])}
        assert rule.diagnose(_ctx(pools, {dt.date(2026, 9, 7): 'mix'})) == []
