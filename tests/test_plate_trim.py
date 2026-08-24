"""Tests for the plate cap policy, portion trimming, and the price list."""

import pandas as pd
import pytest

from src.constants import (
    PLATE_CAP_GRAMS,
    PLATE_CAP_GRAMS_BY_THEME,
    PLATE_CAP_SLOT_EXEMPTION,
    PLATE_TRIM_MAX_CUT_FRACTION,
    PLATE_TRIM_STEP_GRAMS,
    plate_cap_grams,
)
from src.cost.calculator import build_cost_lookup, enrich_solution_with_costs
from src.cost.plate_adjust import trim_portions
from src.preprocessor.price_list import apply_price_list, load_price_list


# ---------------------------------------------------------------------------
# Cap policy
# ---------------------------------------------------------------------------

class TestPlateCapPolicy:
    def test_ordinary_day_gets_the_base_cap(self):
        assert plate_cap_grams('mix', 15) == PLATE_CAP_GRAMS
        assert plate_cap_grams('south', 11) == PLATE_CAP_GRAMS

    def test_biryani_day_is_allowed_a_heavier_plate(self):
        assert plate_cap_grams('biryani', 15) == 1200
        assert plate_cap_grams('biryani', 15) > PLATE_CAP_GRAMS

    def test_extended_theme_names_resolve_to_their_solver_theme(self):
        # chinese_continental canonicalises to chinese, which has no
        # special cap, so it lands on the base one.
        assert plate_cap_grams('chinese_continental', 15) == PLATE_CAP_GRAMS

    def test_a_wider_plate_earns_graduated_headroom(self):
        """More lines legitimately means more food, but a 16-item plate
        shouldn't get the same allowance as a 20-item one."""
        assert plate_cap_grams('mix', 15) == 1000
        assert plate_cap_grams('mix', 16) == 1050
        assert plate_cap_grams('mix', 17) == 1050
        assert plate_cap_grams('mix', 18) == 1100
        assert plate_cap_grams('mix', 30) == 1100

    def test_theme_and_width_allowances_add(self):
        """A wide biryani counter has both reasons to weigh more. Adding
        them is also the only way that day comes within reach: its
        lightest plate is ~1660 g and max trim reaches ~1245 g."""
        assert plate_cap_grams('biryani', 16) == 1250
        assert plate_cap_grams('biryani', 19) == 1300

    def test_every_plate_has_a_cap(self):
        """No plate is exempt any more — width buys headroom, not amnesty."""
        for slots in (1, 15, 16, 18, 40):
            for theme in ('mix', 'biryani', 'chinese'):
                assert plate_cap_grams(theme, slots) is not None

    def test_unknown_theme_falls_back_to_the_base_cap(self):
        assert plate_cap_grams('', 10) == PLATE_CAP_GRAMS
        assert plate_cap_grams('holiday', 10) == PLATE_CAP_GRAMS

    def test_biryani_is_the_only_exception(self):
        assert set(PLATE_CAP_GRAMS_BY_THEME) == {'biryani'}


# ---------------------------------------------------------------------------
# Portion trimming
# ---------------------------------------------------------------------------

BIRYANI_PLATE = {
    'rice': 300, 'nonveg_main': 300, 'veg_gravy': 100, 'veg_dry': 100,
    'dal': 100, 'sambar': 100, 'rasam': 60, 'salad': 70, 'bread': 60,
    'curd_side': 50, 'dessert': 40, 'papad': 10, 'pickle': 10,
}


class TestTrimPortions:
    def test_untouched_when_already_within_the_cap(self):
        out, removed = trim_portions({'rice': 120, 'dal': 100}, 1000)
        assert out == {'rice': 120, 'dal': 100}
        assert removed == 0

    def test_untouched_when_uncapped(self):
        out, removed = trim_portions({'rice': 300, 'nonveg_main': 300}, None)
        assert out == {'rice': 300, 'nonveg_main': 300}
        assert removed == 0

    def test_reaches_the_cap_exactly(self):
        out, removed = trim_portions(BIRYANI_PLATE, 1100)
        assert sum(out.values()) == 1100
        assert removed == sum(BIRYANI_PLATE.values()) - 1100

    def test_every_portion_stays_a_multiple_of_the_step(self):
        out, _ = trim_portions(BIRYANI_PLATE, 1100)
        assert all(g % PLATE_TRIM_STEP_GRAMS == 0 for g in out.values())

    def test_no_portion_is_reduced_to_zero(self):
        out, _ = trim_portions(BIRYANI_PLATE, 300)
        assert all(g > 0 for g in out.values())

    def test_the_trim_is_spread_across_several_portions(self):
        """Not all from one slot — the whole point of "balanced"."""
        out, _ = trim_portions(BIRYANI_PLATE, 1100)
        cut = [s for s, g in BIRYANI_PLATE.items() if out[s] < g]
        assert len(cut) >= 2

    def test_the_per_slot_limit_is_what_forces_the_spread(self):
        """A trim small enough to come off the heaviest item alone does
        — that is still "reduce the bigger portion". Spreading is forced
        by the 25% ceiling once more than that is needed.
        """
        small, _ = trim_portions({'rice': 800, 'dal': 400}, 1000)
        assert small == {'rice': 600, 'dal': 400}      # 200 g = 25% of 800

        big, _ = trim_portions({'rice': 800, 'dal': 400}, 900)
        assert big['rice'] == 600                      # at its limit
        assert big['dal'] < 400                        # so the dal gives too
        assert sum(big.values()) == 900

    def test_it_takes_from_the_heaviest_first(self):
        out, _ = trim_portions(BIRYANI_PLATE, 1100)
        # The two 300 g items shed the most, and shed it equally.
        assert out['rice'] == out['nonveg_main'] < 300
        assert 300 - out['rice'] >= 100 - out['veg_gravy']

    def test_no_portion_loses_more_than_the_max_fraction(self):
        out, _ = trim_portions(BIRYANI_PLATE, 200)
        for slot, original in BIRYANI_PLATE.items():
            keep_at_least = original * (1 - PLATE_TRIM_MAX_CUT_FRACTION)
            assert out[slot] >= keep_at_least - PLATE_TRIM_STEP_GRAMS

    def test_small_portions_are_left_alone(self):
        """A 10 g pickle has no room to give and must not be touched."""
        out, _ = trim_portions({'rice': 300, 'pickle': 10, 'papad': 10}, 100)
        assert out['pickle'] == 10
        assert out['papad'] == 10
        assert out['rice'] < 300

    def test_stops_short_rather_than_breaking_a_rule(self):
        """When the cap can't be met within the limits, trim what's
        allowed and leave the rest visible."""
        out, removed = trim_portions({'rice': 300}, 100)
        assert removed == 75          # 25% of 300, and no more
        assert out == {'rice': 225}
        assert sum(out.values()) > 100

    def test_is_deterministic(self):
        first, _ = trim_portions(BIRYANI_PLATE, 1100)
        second, _ = trim_portions(BIRYANI_PLATE, 1100)
        assert first == second

    def test_zero_weight_slots_are_preserved_not_dropped(self):
        out, _ = trim_portions({'rice': 300, 'chutney': 0}, 250)
        assert 'chutney' in out and out['chutney'] == 0


# ---------------------------------------------------------------------------
# Trimming through the cost enrichment
# ---------------------------------------------------------------------------

def _solution(day_type, items):
    return {
        '2026-09-09': {
            'theme': day_type.title(), 'day_type': day_type,
            'items': {
                slot: {'item': name, 'item_base': name}
                for slot, name in items.items()
            },
        }
    }


def _lookup(**items):
    """items: name -> (cost_per_kg, grams)"""
    return {
        name: {'cost_per_kg': cpk, 'cost_per_person': round(cpk * g / 1000, 2),
               'grammage_kg': g / 1000}
        for name, (cpk, g) in items.items()
    }


class TestEnrichmentApplIesTheTrim:
    def test_no_cap_fn_means_no_trimming(self):
        out = enrich_solution_with_costs(
            _solution('biryani', {'rice': 'biryani'}),
            _lookup(biryani=(100.0, 300)),
        )
        day = out['2026-09-09']
        assert day['items']['rice']['grammage_kg'] == 0.3
        assert day['day_qty_trimmed_g'] == 0

    def test_trims_and_reprices_a_heavy_day(self):
        out = enrich_solution_with_costs(
            _solution('mix', {'rice': 'heavy_rice', 'dal': 'dal'}),
            _lookup(heavy_rice=(100.0, 800), dal=(50.0, 400)),
            cap_fn=lambda day_type, slots: 1000,
        )
        day = out['2026-09-09']
        assert round(day['day_qty_total_kg'] * 1000) == 1000
        assert day['day_qty_trimmed_g'] == 200
        assert day['day_qty_cap_g'] == 1000
        # The whole 200 g comes off the 800 g rice: that is exactly its
        # 25% limit, and even after losing it the rice is still the
        # heaviest portion, so nothing else needs to give.
        assert round(day['items']['rice']['grammage_kg'] * 1000) == 600
        assert round(day['items']['dal']['grammage_kg'] * 1000) == 400
        # Cost follows the portion actually served.
        assert day['items']['rice']['cost_per_person'] == 60.0
        assert day['items']['dal']['cost_per_person'] == 20.0
        assert day['day_cost_total'] == 80.0

    def test_marks_the_portions_it_trimmed(self):
        out = enrich_solution_with_costs(
            _solution('mix', {'rice': 'heavy_rice', 'dal': 'dal'}),
            _lookup(heavy_rice=(100.0, 800), dal=(50.0, 400)),
            cap_fn=lambda day_type, slots: 1000,
        )
        items = out['2026-09-09']['items']
        assert items['rice'].get('portion_trimmed_g') == 200
        assert 'portion_trimmed_g' not in items['dal']

    def test_a_day_within_its_cap_is_not_marked(self):
        out = enrich_solution_with_costs(
            _solution('mix', {'rice': 'light_rice'}),
            _lookup(light_rice=(100.0, 120)),
            cap_fn=lambda day_type, slots: 1000,
        )
        day = out['2026-09-09']
        assert day['day_qty_trimmed_g'] == 0
        assert 'portion_trimmed_g' not in day['items']['rice']

    def test_the_real_policy_lets_a_biryani_day_run_heavier(self):
        """A 1080 g plate passes on a biryani day and not on a mix day."""
        items = {f'slot_{i}': f'item_{i}' for i in range(12)}
        lookup = _lookup(**{f'item_{i}': (10.0, 90) for i in range(12)})


        mix = enrich_solution_with_costs(
            _solution('mix', items), lookup, cap_fn=plate_cap_grams,
        )['2026-09-09']
        biryani = enrich_solution_with_costs(
            _solution('biryani', items), lookup, cap_fn=plate_cap_grams,
        )['2026-09-09']

        assert mix['day_qty_cap_g'] == 1000
        assert mix['day_qty_trimmed_g'] == 80
        assert biryani['day_qty_cap_g'] == 1200
        assert biryani['day_qty_trimmed_g'] == 0

    def test_a_wide_plate_gets_headroom_but_is_still_capped(self):
        n = PLATE_CAP_SLOT_EXEMPTION + 1        # 16 items -> 1050 g
        items = {f'slot_{i}': f'item_{i}' for i in range(n)}
        lookup = _lookup(**{f'item_{i}': (10.0, 100) for i in range(n)})
        day = enrich_solution_with_costs(
            _solution('mix', items), lookup, cap_fn=plate_cap_grams,
        )['2026-09-09']
        assert day['day_qty_cap_g'] == 1050
        # 1600 g of food trimmed towards 1050, limited by the 25% floor.
        assert day['day_qty_trimmed_g'] > 0
        assert round(day['day_qty_total_kg'] * 1000) <= 1200


# ---------------------------------------------------------------------------
# Price list import
# ---------------------------------------------------------------------------

class TestPriceList:
    def test_reads_the_shipped_menu_list(self):
        from api.config import DEFAULT_PRICE_LIST_PATH

        prices = load_price_list(DEFAULT_PRICE_LIST_PATH)
        assert len(prices) > 400
        assert set(prices.columns) == {
            'key', 'cost_per_kg', 'grammage_per_serving',
        }
        assert prices['key'].is_unique
        assert prices['cost_per_kg'].notna().all()

    def test_overrides_the_ontologys_cached_values(self):
        df = pd.DataFrame([
            {'item': 'plain_chapatti', 'cost_per_kg': 2.0,
             'grammage_per_serving': 1.00},
        ])
        out = apply_price_list(df, 'data/raw/menu_prices.xlsx')
        assert out.iloc[0]['cost_per_kg'] == 58.0
        assert out.iloc[0]['grammage_per_serving'] == 0.35

    def test_unmatched_items_keep_their_cached_values(self):
        df = pd.DataFrame([
            {'item': 'not_in_the_price_list', 'cost_per_kg': 42.0,
             'grammage_per_serving': 0.07},
        ])
        out = apply_price_list(df, 'data/raw/menu_prices.xlsx')
        assert out.iloc[0]['cost_per_kg'] == 42.0
        assert out.iloc[0]['grammage_per_serving'] == 0.07

    def test_missing_file_degrades_to_the_cached_values(self):
        df = pd.DataFrame([
            {'item': 'x', 'cost_per_kg': 5.0, 'grammage_per_serving': 0.1},
        ])
        out = apply_price_list(df, 'data/raw/does_not_exist.xlsx')
        assert out.iloc[0]['cost_per_kg'] == 5.0

    def test_none_path_is_a_noop(self):
        df = pd.DataFrame([{'item': 'x', 'cost_per_kg': 5.0}])
        assert apply_price_list(df, None).equals(df)

    def test_a_sheet_without_the_columns_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.xlsx"
        pd.DataFrame([{'item': 'x', 'something_else': 1}]).to_excel(
            bad, index=False,
        )
        with pytest.raises(ValueError, match="missing column"):
            load_price_list(bad)

    def test_white_rice_resolves_to_the_lists_sona_masoori(self):
        """The ontology's white rice is the list's "steamed_rice - Sona
        Masoori" — the same dish under the name the Menu List uses, and
        the default variant rather than Bullet. Without the alias it
        would keep a stale cached value."""
        df = pd.DataFrame([
            {'item': 'white_rice', 'cost_per_kg': 1.0,
             'grammage_per_serving': 0.01},
        ])
        out = apply_price_list(df, 'data/raw/menu_prices.xlsx')
        assert out.iloc[0]['cost_per_kg'] == 20.0
        assert out.iloc[0]['grammage_per_serving'] == 0.20

    def test_the_constant_slot_is_shown_as_white_rice(self):
        """The plan table shows whatever CONSTANT_ITEMS says, and the slot
        serves plain white rice — so that is what it is called."""
        from src.constants import CONSTANT_ITEMS

        assert CONSTANT_ITEMS['white_rice'] == 'White Rice'

    def test_the_retired_names_are_gone_from_the_dataset(self):
        """`steamed_rice` is now `white_rice` (one dish, one name, shown
        as White Rice), and `myos` was withdrawn."""
        from api.config import DEFAULT_EXCEL_PATH

        onto = pd.read_excel(DEFAULT_EXCEL_PATH, sheet_name=0)
        items = set(onto['item'])
        categories = set(onto['category'])
        assert 'white_rice' in items
        assert 'steamed_rice' not in items
        assert 'myos' not in items and 'myos' not in categories

    def test_every_shipped_item_is_priced_by_the_list(self):
        """Coverage guard on the shipped pair of files: an item the list
        doesn't price falls back to a cached value, which is exactly the
        staleness the import exists to remove."""
        from api.config import DEFAULT_EXCEL_PATH, DEFAULT_PRICE_LIST_PATH
        from src.preprocessor.price_list import _match_key

        onto = pd.read_excel(DEFAULT_EXCEL_PATH, sheet_name=0)
        prices = load_price_list(DEFAULT_PRICE_LIST_PATH)
        unpriced = [
            item for item in onto['item']
            if _match_key(item) not in set(prices['key'])
        ]
        assert unpriced == []

    def test_the_shipped_ontology_carries_the_lists_numbers(self):
        """The two columns are baked into the workbook (see
        scripts/bake_price_list.py), so the dataset costs correctly even
        with no price list present — not just after the overlay runs."""
        from api.config import DEFAULT_EXCEL_PATH, DEFAULT_PRICE_LIST_PATH
        from src.preprocessor.price_list import _match_key

        onto = pd.read_excel(DEFAULT_EXCEL_PATH, sheet_name=0)
        prices = load_price_list(DEFAULT_PRICE_LIST_PATH).set_index('key')
        keys = onto['item'].map(_match_key)
        for column in ('cost_per_kg', 'grammage_per_serving'):
            got = pd.to_numeric(onto[column], errors='coerce')
            assert got.notna().all(), f"{column} has non-numeric cells"
            expected = keys.map(prices[column])
            drifted = int((got.round(6) != expected.round(6)).sum())
            assert drifted == 0, (
                f"{drifted} {column} values in the ontology differ from the "
                "price list — run scripts/bake_price_list.py after dropping "
                "in a new Menu List"
            )

    def test_bread_ends_up_at_60g_with_a_real_price(self):
        """The two data fixes together: the list supplies a believable
        price, the cleanser fixes the serving weight the list still has
        wrong (chapatti at 350 g)."""
        from src.preprocessor.data_cleanser import DataCleanser

        df = DataCleanser(apply_price_list(pd.DataFrame([
            {'item': 'plain_chapatti', 'course_type': 'bread',
             'cost_per_kg': 2.0, 'grammage_per_serving': 1.00},
        ]), 'data/raw/menu_prices.xlsx')).clean()
        row = df.iloc[0]
        assert row['grammage_per_serving'] == 0.06
        assert row['cost_per_kg'] == 58.0
        lookup = build_cost_lookup(df)
        assert lookup['plain_chapatti']['cost_per_person'] == pytest.approx(3.48)
