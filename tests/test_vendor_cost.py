"""Tests for the vendor / operating cost model (src.cost.vendor_cost)."""

import pytest

from src.cost.overall_cost import DEFAULT_FOOD_COST_PCT
from src.cost.vendor_cost import (
    MAX_EXPECTED_PROFIT_PCT,
    MIN_HEALTHY_PROFIT_PCT,
    VENDOR_COST_LINES,
    profit_pct,
    profit_status,
)


# --- cost lines ------------------------------------------------------------

def test_vendor_defaults_sum_to_45():
    assert sum(d for _k, _l, d in VENDOR_COST_LINES) == pytest.approx(45.0)


def test_vendor_line_keys_are_unique():
    keys = [k for k, _l, _d in VENDOR_COST_LINES]
    assert len(keys) == len(set(keys))


# --- profit_pct ------------------------------------------------------------

def test_profit_pct_is_remainder():
    vendor = {key: default for key, _label, default in VENDOR_COST_LINES}
    # Defaults: 45 food + 45 vendor -> 10 profit.
    assert profit_pct(DEFAULT_FOOD_COST_PCT, vendor) == pytest.approx(10.0)


def test_profit_pct_can_go_negative_when_over_allocated():
    assert profit_pct(45.0, {"a": 40.0, "b": 30.0}) == pytest.approx(-15.0)


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
