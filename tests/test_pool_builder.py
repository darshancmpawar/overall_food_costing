"""Tests for PoolBuilder."""

import pandas as pd
import pytest
from src.constants import COMBINED_SLOT_SOURCES, REQUIRED_POOL_SLOTS
from src.preprocessor.pool_builder import (
    PoolBuilder, _base_slot, _slot_num,
    _expand_slots_in_order, scope_to_source_pools,
)


def _make_ontology_df():
    """Create a minimal ontology DataFrame with at least 1 item per slot."""
    rows = []
    for slot in ['welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
                 'healthy_rice', 'dal', 'veg_gravy', 'veg_dry', 'nonveg_main',
                 'curd_side', 'dessert']:
        rows.append({'item': f'{slot}_item_1', 'course_type': slot, 'cuisine_family': 'indian', 'item_color': 'red'})
        rows.append({'item': f'{slot}_item_2', 'course_type': slot, 'cuisine_family': 'indian', 'item_color': 'green'})

    # sambar and rasam via sambar/rasam course_type
    rows.append({'item': 'sambar dal', 'course_type': 'sambar', 'cuisine_family': 'south_indian', 'item_color': 'yellow'})
    rows.append({'item': 'tomato rasam', 'course_type': 'sambar/rasam', 'cuisine_family': 'south_indian', 'item_color': 'orange'})
    rows.append({'item': 'sambar special', 'course_type': 'sambar/rasam', 'cuisine_family': 'south_indian', 'item_color': 'yellow'})

    # infused_water maps to welcome_drink
    rows.append({'item': 'lemon water', 'course_type': 'infused_water', 'cuisine_family': 'indian', 'item_color': 'yellow'})

    # Plain curd + curd rice back the dedicated 'curd' / 'curd_rice' slots.
    rows.append({'item': 'curd', 'course_type': 'curd_side', 'cuisine_family': 'south_indian',
                 'item_color': 'white', 'is_plain_curd': 1})
    rows.append({'item': 'curd_rice_with_grapes', 'course_type': 'rice', 'cuisine_family': 'south_indian',
                 'item_color': 'white', 'is_curd_rice': 1})

    df = pd.DataFrame(rows)
    for flag in ('is_plain_curd', 'is_curd_rice'):
        df[flag] = df.get(flag, 0)
        df[flag] = df[flag].fillna(0).astype(int)
    return df


class TestPoolBuilder:
    def test_all_required_slots_populated(self):
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        for slot in REQUIRED_POOL_SLOTS:
            assert len(pools[slot]) > 0, f"Slot {slot} has no items"

    def test_curd_and_curd_rice_carved_out_by_flag(self):
        pools = PoolBuilder.build_pools(_make_ontology_df())
        assert pools['curd']['item'].tolist() == ['curd']
        assert pools['curd_rice']['item'].tolist() == ['curd_rice_with_grapes']

    def test_combined_slots_union_their_sources(self):
        pools = PoolBuilder.build_pools(_make_ontology_df())
        for slot, sources in COMBINED_SLOT_SOURCES.items():
            expected = set()
            for source in sources:
                expected |= set(pools[source]['item'].tolist())
            assert set(pools[slot]['item'].tolist()) == expected

    def test_optional_slot_empty_does_not_raise(self):
        """An ontology with no plain curd still builds — 'curd' is opt-in."""
        df = _make_ontology_df()
        df.loc[df['item'] == 'curd', 'is_plain_curd'] = 0
        pools = PoolBuilder.build_pools(df)
        assert len(pools['curd']) == 0

    def test_sambar_rasam_split(self):
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        # 'tomato rasam' should be in rasam pool
        rasam_items = pools['rasam']['item'].tolist()
        assert 'tomato rasam' in rasam_items
        # 'sambar special' and 'sambar dal' should be in sambar pool
        sambar_items = pools['sambar']['item'].tolist()
        assert 'sambar dal' in sambar_items
        assert 'sambar special' in sambar_items

    def test_welcome_drink_includes_infused_water(self):
        df = _make_ontology_df()
        pools = PoolBuilder.build_pools(df)
        items = pools['welcome_drink']['item'].tolist()
        assert 'lemon water' in items

    def test_empty_slot_raises(self):
        # Create df missing 'dessert'
        df = _make_ontology_df()
        df = df[df['course_type'] != 'dessert']
        with pytest.raises(ValueError, match="dessert"):
            PoolBuilder.build_pools(df)


class TestSourcePoolScoping:
    def test_no_source_pool_column_returns_everything(self):
        df = _make_ontology_df()
        # Even with a client that declares pools, an ontology with no
        # source_pool column must not be filtered down to nothing.
        assert len(scope_to_source_pools(df, ['amadeus'])) == len(df)

    def test_shared_items_always_in_scope(self):
        df = _make_ontology_df()
        df['source_pool'] = ''
        df.loc[df['course_type'] == 'dessert', 'source_pool'] = 'amadeus'
        scoped = scope_to_source_pools(df, [])
        assert 'amadeus' not in set(scoped['source_pool'])
        assert len(scoped) == len(df) - 2

    def test_declared_pool_is_added_to_shared(self):
        df = _make_ontology_df()
        df['source_pool'] = ''
        df.loc[df['course_type'] == 'dessert', 'source_pool'] = 'amadeus'
        scoped = scope_to_source_pools(df, ['Amadeus'])
        assert len(scoped) == len(df)

    def test_build_pools_applies_scoping(self):
        df = _make_ontology_df()
        df['source_pool'] = ''
        df.loc[df['item'] == 'dessert_item_2', 'source_pool'] = 'amadeus'
        shared = PoolBuilder.build_pools(df)
        widened = PoolBuilder.build_pools(df, source_pools=['amadeus'])
        assert 'dessert_item_2' not in shared['dessert']['item'].tolist()
        assert 'dessert_item_2' in widened['dessert']['item'].tolist()


class TestSlotHelpers:
    def test_base_slot_simple(self):
        assert _base_slot('veg_dry') == 'veg_dry'

    def test_base_slot_numbered(self):
        assert _base_slot('veg_dry__2') == 'veg_dry'

    def test_slot_num_simple(self):
        assert _slot_num('veg_dry') is None

    def test_slot_num_numbered(self):
        assert _slot_num('veg_dry__2') == 2

    def test_expand_slots_single(self):
        result = _expand_slots_in_order(['rice', 'veg_dry'], {'rice': 1, 'veg_dry': 1})
        assert result == ['rice', 'veg_dry']

    def test_expand_slots_multiple(self):
        result = _expand_slots_in_order(['rice', 'veg_dry'], {'rice': 1, 'veg_dry': 2})
        assert result == ['rice', 'veg_dry__1', 'veg_dry__2']

    def test_expand_slots_zero(self):
        result = _expand_slots_in_order(['rice', 'veg_dry'], {'rice': 0, 'veg_dry': 1})
        assert result == ['veg_dry']
