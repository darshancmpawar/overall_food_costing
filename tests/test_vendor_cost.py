"""Tests for the vendor / operating cost model (src.cost.vendor_cost)."""

import pytest

from src.cost.overall_cost import DEFAULT_FOOD_COST_PCT
from src.cost.vendor_cost import (
    DEFAULT_VENDOR_PROFIT_PCT,
    MAX_EXPECTED_PROFIT_PCT,
    MIN_HEALTHY_PROFIT_PCT,
    VENDOR_COST_LINES,
    profit_status,
    share_amount,
    share_status,
    smartq_share_pct,
)


# --- cost lines ------------------------------------------------------------

def test_vendor_defaults_sum_to_45():
    assert sum(d for _k, _l, d in VENDOR_COST_LINES) == pytest.approx(45.0)


def test_vendor_line_keys_are_unique():
    keys = [k for k, _l, _d in VENDOR_COST_LINES]
    assert len(keys) == len(set(keys))


# --- smartq_share_pct ------------------------------------------------------

def test_the_defaults_leave_a_share_for_smartq():
    """45 food + 45 operating + 8 vendor profit = 98, so 2% is SmartQ's."""
    vendor = {key: default for key, _label, default in VENDOR_COST_LINES}
    share = smartq_share_pct(
        DEFAULT_FOOD_COST_PCT, vendor, DEFAULT_VENDOR_PROFIT_PCT,
    )
    assert share == pytest.approx(2.0)


def test_vendor_profit_defaults_to_8():
    assert DEFAULT_VENDOR_PROFIT_PCT == 8.0


def test_the_shares_always_account_for_the_whole_plate():
    vendor = {key: default for key, _label, default in VENDOR_COST_LINES}
    total = (
        DEFAULT_FOOD_COST_PCT + sum(vendor.values())
        + DEFAULT_VENDOR_PROFIT_PCT
        + smartq_share_pct(DEFAULT_FOOD_COST_PCT, vendor, DEFAULT_VENDOR_PROFIT_PCT)
    )
    assert total == pytest.approx(100.0)


def test_raising_vendor_profit_takes_from_smartqs_share():
    """The two are the only claimants on what's left, so one grows at the
    other's expense — the point of making profit an input."""
    vendor = {"manpower": 25.0}
    at_eight = smartq_share_pct(45.0, vendor, 8.0)
    at_twelve = smartq_share_pct(45.0, vendor, 12.0)
    assert at_eight - at_twelve == pytest.approx(4.0)


def test_share_can_go_negative_when_over_allocated():
    assert smartq_share_pct(45.0, {"a": 40.0, "b": 30.0}, 8.0) == pytest.approx(-23.0)


# --- share_amount ----------------------------------------------------------

def test_share_amount_scales_over_the_period():
    # 2% of a ₹250 plate, 150 pax, 22 days = 0.02 * 250 * 3300
    assert share_amount(2.0, 250.0, 150, 22) == pytest.approx(16500.0)


def test_share_amount_of_nothing_is_nothing():
    assert share_amount(0.0, 250.0, 150, 22) == 0.0
    assert share_amount(2.0, 0.0, 150, 22) == 0.0


def test_negative_share_stays_negative():
    """An over-allocated plate must not quietly read as zero."""
    assert share_amount(-2.0, 250.0, 150, 22) < 0


# --- share_status ----------------------------------------------------------

def test_share_status_ok_when_something_remains():
    assert share_status(2.0).level == "ok"
    assert "2.00%" in share_status(2.0).message


def test_share_status_errors_when_over_allocated():
    verdict = share_status(-3.0)
    assert verdict.level == "error"
    # The message names the real total so the fix is obvious.
    assert "103.00%" in verdict.message


def test_share_status_warns_when_exactly_nothing_is_left():
    assert share_status(0.0).level == "warning"


# --- profit_status (now advice on an input, not a derived value) -----------

def test_profit_status_ok_band():
    assert profit_status(MIN_HEALTHY_PROFIT_PCT).level == "ok"
    assert profit_status(DEFAULT_VENDOR_PROFIT_PCT).level == "ok"
    assert profit_status(MAX_EXPECTED_PROFIT_PCT).level == "ok"


def test_profit_status_error_below_minimum():
    assert profit_status(4.99).level == "error"
    assert profit_status(0.0).level == "error"
    assert profit_status(-5.0).level == "error"


def test_profit_status_warning_above_expected():
    assert profit_status(10.01).level == "warning"
    assert profit_status(25.0).level == "warning"
