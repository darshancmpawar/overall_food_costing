"""Tests for the SmartQ cost model (src.cost.smartq_cost)."""

import pytest

from src.cost.smartq_cost import (
    DEFAULT_SELLING_PAX,
    DEFAULT_WORKING_DAYS,
    MONTHS_PER_YEAR,
    SMARTQ_COST_LINES,
    buying_amount,
    line_abs,
    line_pct,
    selling_amount,
    selling_price,
    smartq_cost,
)


# --- selling price / period totals -----------------------------------------

def test_selling_price_is_30pct_above_overall():
    assert selling_price(100.0) == pytest.approx(130.0)


def test_buying_amount():
    assert buying_amount(100.0, 100, 26) == pytest.approx(260_000.0)


def test_selling_amount():
    assert selling_amount(130.0, 100, 26) == pytest.approx(338_000.0)


def test_period_totals_chain_from_overall():
    overall = 100.0
    price = selling_price(overall)
    assert selling_amount(price, 100, 26) == pytest.approx(338_000.0)
    assert buying_amount(overall, 100, 26) == pytest.approx(260_000.0)


# --- line value <-> share --------------------------------------------------

def test_line_abs_monthly():
    assert line_abs(8.0, 338_000.0, 1) == pytest.approx(27_040.0)


def test_line_abs_yearly_divides_by_12():
    # Food Licenses: 2% of the selling amount, spread across the year.
    assert line_abs(2.0, 338_000.0, MONTHS_PER_YEAR) == pytest.approx(563.33, abs=0.01)


def test_line_pct_inverts_line_abs_monthly():
    assert line_pct(27_040.0, 338_000.0, 1) == pytest.approx(8.0)


def test_line_pct_inverts_line_abs_yearly():
    abs_val = line_abs(2.0, 338_000.0, MONTHS_PER_YEAR)
    assert line_pct(abs_val, 338_000.0, MONTHS_PER_YEAR) == pytest.approx(2.0, abs=0.01)


def test_line_pct_zero_selling_amount_is_safe():
    assert line_pct(500.0, 0.0, 1) == 0.0


# --- smartq_cost -----------------------------------------------------------

def test_smartq_cost_sums_lines():
    assert smartq_cost([27_040.0, 6_760.0, 563.33]) == pytest.approx(34_363.33)


def test_smartq_cost_full_default_breakdown():
    # End-to-end with the default shares at overall=100, 100 pax, 26 days.
    sell_amt = selling_amount(selling_price(100.0), DEFAULT_SELLING_PAX,
                              DEFAULT_WORKING_DAYS)
    values = [
        line_abs(default, sell_amt, divisor)
        for _key, _label, default, _cadence, divisor in SMARTQ_COST_LINES
    ]
    assert smartq_cost(values) == pytest.approx(58_023.33, abs=0.01)


# --- cost lines config -----------------------------------------------------

def test_smartq_lines_keys_unique_and_count():
    keys = [k for k, _l, _d, _c, _dv in SMARTQ_COST_LINES]
    assert len(keys) == len(set(keys)) == 8


def test_food_licenses_is_yearly_over_12():
    food = next(line for line in SMARTQ_COST_LINES if line[0] == "food_licenses")
    _key, _label, default, cadence, divisor = food
    assert (default, cadence, divisor) == (2.0, "yearly", MONTHS_PER_YEAR)


def test_all_non_food_lines_are_monthly():
    for key, _label, _default, cadence, divisor in SMARTQ_COST_LINES:
        if key == "food_licenses":
            continue
        assert cadence == "monthly"
        assert divisor == 1
