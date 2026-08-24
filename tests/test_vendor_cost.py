"""Tests for the vendor / operating cost model (src.cost.vendor_cost)."""

import pytest

from src.cost.overall_cost import DEFAULT_FOOD_COST_PCT, pct_to_abs
from src.cost.vendor_cost import (
    DEFAULT_VENDOR_PROFIT_PCT,
    MAX_EXPECTED_PROFIT_PCT,
    MIN_HEALTHY_PROFIT_PCT,
    VENDOR_COST_LINES,
    buying_share_pct,
    extra_margin_amount,
    margin_status,
    profit_status,
    smartq_margin_pct,
)


def _defaults():
    return {key: default for key, _label, default in VENDOR_COST_LINES}


# --- cost lines ------------------------------------------------------------

def test_vendor_defaults_sum_to_45():
    assert sum(d for _k, _l, d in VENDOR_COST_LINES) == pytest.approx(45.0)


def test_vendor_line_keys_are_unique():
    keys = [k for k, _l, _d in VENDOR_COST_LINES]
    assert len(keys) == len(set(keys))


# --- buying_share_pct ------------------------------------------------------

def test_the_buying_price_is_everything_the_vendor_is_paid():
    """45 food + 45 operating + 8 vendor profit = 98% of the plate."""
    assert buying_share_pct(
        DEFAULT_FOOD_COST_PCT, _defaults(), DEFAULT_VENDOR_PROFIT_PCT,
    ) == pytest.approx(98.0)


def test_the_buying_price_excludes_smartqs_margin():
    """The total stops at the vendor's profit — that's the whole point of
    the split, so the two must never both be inside it."""
    buying = buying_share_pct(45.0, _defaults(), 8.0)
    margin = smartq_margin_pct(45.0, _defaults(), 8.0)
    assert buying + margin == pytest.approx(100.0)
    assert margin not in (buying, 0.0)


def test_raising_vendor_profit_raises_the_buying_price():
    at_eight = buying_share_pct(45.0, {"manpower": 25.0}, 8.0)
    at_twelve = buying_share_pct(45.0, {"manpower": 25.0}, 12.0)
    assert at_twelve - at_eight == pytest.approx(4.0)


def test_the_buying_price_in_rupees():
    overall = 247.04
    buying = buying_share_pct(45.0, _defaults(), 8.0)
    assert pct_to_abs(buying, overall) == pytest.approx(242.1, abs=0.05)


# --- smartq_margin_pct -----------------------------------------------------

def test_the_defaults_leave_a_margin_for_smartq():
    assert smartq_margin_pct(
        DEFAULT_FOOD_COST_PCT, _defaults(), DEFAULT_VENDOR_PROFIT_PCT,
    ) == pytest.approx(2.0)


def test_vendor_profit_defaults_to_8():
    assert DEFAULT_VENDOR_PROFIT_PCT == 8.0


def test_raising_vendor_profit_takes_from_smartqs_margin():
    """The two are the only claimants on what's left, so one grows at the
    other's expense — the point of making profit an input."""
    at_eight = smartq_margin_pct(45.0, {"manpower": 25.0}, 8.0)
    at_twelve = smartq_margin_pct(45.0, {"manpower": 25.0}, 12.0)
    assert at_eight - at_twelve == pytest.approx(4.0)


def test_margin_can_go_negative_when_over_allocated():
    assert smartq_margin_pct(45.0, {"a": 40.0, "b": 30.0}, 8.0) == pytest.approx(-23.0)


# --- extra_margin_amount ---------------------------------------------------

def test_extra_margin_scales_over_the_period():
    # 2% of a ₹250 plate, 150 pax, 22 days = 0.02 * 250 * 3300
    assert extra_margin_amount(2.0, 250.0, 150, 22) == pytest.approx(16500.0)


def test_extra_margin_of_nothing_is_nothing():
    assert extra_margin_amount(0.0, 250.0, 150, 22) == 0.0
    assert extra_margin_amount(2.0, 0.0, 150, 22) == 0.0


def test_negative_margin_stays_negative():
    """An over-allocated plate must not quietly read as zero."""
    assert extra_margin_amount(-2.0, 250.0, 150, 22) < 0


# --- margin_status ---------------------------------------------------------

def test_margin_status_ok_when_something_remains():
    assert margin_status(2.0).level == "ok"
    assert "2.0%" in margin_status(2.0).message


def test_margin_status_errors_when_over_allocated():
    verdict = margin_status(-3.0)
    assert verdict.level == "error"
    # The message names the real buying total so the fix is obvious.
    assert "103.0%" in verdict.message


def test_margin_status_warns_when_exactly_nothing_is_left():
    assert margin_status(0.0).level == "warning"


# --- profit_status (advice on an input, not a derived value) ---------------

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


def test_every_message_reads_to_one_decimal():
    """The costing screens are all one-decimal now; the alert text that
    sits under them must not drift back to two."""
    for message in (
        profit_status(8.25).message,
        profit_status(3.333).message,
        profit_status(12.567).message,
        margin_status(2.345).message,
        margin_status(-3.456).message,
    ):
        assert "%" in message
        for token in message.replace("%", " ").split():
            if token.replace(".", "", 1).replace("-", "", 1).isdigit():
                if "." in token:
                    assert len(token.split(".")[1]) == 1, message
