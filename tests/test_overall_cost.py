"""Tests for the overall operating-cost model (src.cost.overall_cost)."""

import pytest

from src.cost.overall_cost import (
    DEFAULT_FOOD_COST_PCT,
    MAX_EXPECTED_PROFIT_PCT,
    MIN_HEALTHY_PROFIT_PCT,
    VENDOR_COST_LINES,
    abs_to_pct,
    average_food_cost,
    day_costs_from_cost_data,
    overall_food_cost,
    pct_to_abs,
    profit_pct,
    profit_status,
)


# --- average_food_cost -----------------------------------------------------

def test_average_food_cost_basic():
    assert average_food_cost([100.0, 200.0, 300.0]) == 200.0


def test_average_food_cost_skips_none():
    # Days without cost data contribute nothing to the mean.
    assert average_food_cost([100.0, None, 300.0]) == 200.0


def test_average_food_cost_empty_is_zero():
    assert average_food_cost([]) == 0.0
    assert average_food_cost([None, None]) == 0.0


# --- overall_food_cost -----------------------------------------------------

def test_overall_food_cost_scales_45_to_100():
    # ₹45 food cost at a 45% share implies a ₹100 fully-loaded cost.
    assert overall_food_cost(45.0, 45.0) == pytest.approx(100.0)


def test_overall_food_cost_other_share():
    assert overall_food_cost(60.0, 30.0) == pytest.approx(200.0)


def test_overall_food_cost_zero_share_is_safe():
    assert overall_food_cost(45.0, 0.0) == 0.0
    assert overall_food_cost(45.0, -10.0) == 0.0


# --- pct/abs round trips ---------------------------------------------------

def test_pct_to_abs():
    assert pct_to_abs(25.0, 100.0) == 25.0
    assert pct_to_abs(2.5, 100.0) == 2.5


def test_abs_to_pct():
    assert abs_to_pct(25.0, 100.0) == pytest.approx(25.0)


def test_abs_to_pct_zero_overall_is_safe():
    assert abs_to_pct(25.0, 0.0) == 0.0


def test_pct_abs_round_trip():
    overall = 222.22
    for pct in (25.0, 5.0, 3.0, 2.0):
        assert abs_to_pct(pct_to_abs(pct, overall), overall) == pytest.approx(pct, abs=0.01)


# --- profit_pct ------------------------------------------------------------

def test_profit_pct_is_remainder():
    vendor = {key: default for key, _label, default in VENDOR_COST_LINES}
    # Defaults: 45 food + 45 vendor -> 10 profit.
    assert profit_pct(DEFAULT_FOOD_COST_PCT, vendor) == pytest.approx(10.0)


def test_profit_pct_can_go_negative_when_over_allocated():
    assert profit_pct(45.0, {"a": 40.0, "b": 30.0}) == pytest.approx(-15.0)


def test_vendor_defaults_sum_to_45():
    assert sum(d for _k, _l, d in VENDOR_COST_LINES) == pytest.approx(45.0)


# --- profit_status ---------------------------------------------------------

def test_profit_status_ok_band():
    assert profit_status(MIN_HEALTHY_PROFIT_PCT).level == "ok"
    assert profit_status(7.0).level == "ok"
    assert profit_status(MAX_EXPECTED_PROFIT_PCT).level == "ok"


def test_profit_status_error_below_minimum():
    assert profit_status(4.99).level == "error"
    assert profit_status(0.0).level == "error"
    assert profit_status(-5.0).level == "error"


def test_profit_status_warning_above_expected():
    assert profit_status(10.01).level == "warning"
    assert profit_status(25.0).level == "warning"


# --- day_costs_from_cost_data ----------------------------------------------

def test_day_costs_prefers_numeric_total():
    cost_data = {
        "2026-06-23": {"day_cost_total": 148.5, "day_cost_display": "₹148.50"},
        "2026-06-24": {"day_cost_total": 151.5, "day_cost_display": "₹151.50"},
    }
    assert day_costs_from_cost_data(cost_data) == [148.5, 151.5]


def test_day_costs_falls_back_to_display_string():
    # Older saved plans may carry only the rupee display string.
    cost_data = {
        "2026-06-23": {"day_cost_total": None, "day_cost_display": "₹1,148.50"},
        "2026-06-24": {"day_cost_display": "₹151.50"},
    }
    assert day_costs_from_cost_data(cost_data) == [1148.5, 151.5]


def test_day_costs_skips_non_dicts_and_missing():
    cost_data = {
        "2026-06-23": {"day_cost_total": 100.0},
        "bad": "not-a-dict",
        "2026-06-24": {"day_cost_total": None, "day_cost_display": ""},
    }
    assert day_costs_from_cost_data(cost_data) == [100.0]


def test_average_over_extracted_day_costs():
    cost_data = {
        "d1": {"day_cost_total": 40.0},
        "d2": {"day_cost_total": 50.0},
    }
    avg = average_food_cost(day_costs_from_cost_data(cost_data))
    assert avg == pytest.approx(45.0)
    assert overall_food_cost(avg, DEFAULT_FOOD_COST_PCT) == pytest.approx(100.0)
