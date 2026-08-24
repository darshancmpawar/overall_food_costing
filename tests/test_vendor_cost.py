"""Tests for the vendor / operating cost model (src.cost.vendor_cost)."""

import pytest

from src.cost.manpower import default_roster, manpower_per_plate
from src.cost.overall_cost import (
    DEFAULT_FOOD_COST_PCT,
    abs_to_pct,
    overall_food_cost,
    pct_to_abs,
)
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


# The plan the defaults are quoted against: the ₹99.35 average plate a
# five-day plan on the default counter produces, which at a 45% food share
# is a ₹220.8 overall cost. The default roster over 150 pax a day is
# manpower's 25% of it.
_AVG_FOOD_COST = 99.35
_PAX = 150


def _overall():
    return overall_food_cost(_AVG_FOOD_COST, DEFAULT_FOOD_COST_PCT)


def _manpower_pct():
    """Manpower's share, computed the way the tab computes it."""
    return abs_to_pct(manpower_per_plate(default_roster(), _PAX), _overall())


def _defaults(*, with_manpower: bool = True):
    """The vendor shares the tab feeds into the model.

    Manpower is not one of ``VENDOR_COST_LINES`` — it is computed from the
    roster — so the UI adds it to the dict. Tests do the same.
    """
    lines = {key: default for key, _label, default in VENDOR_COST_LINES}
    if with_manpower:
        lines["manpower"] = _manpower_pct()
    return lines


# --- cost lines ------------------------------------------------------------

def test_the_typed_lines_sum_to_20():
    """Manpower is computed, not typed, so it is not in this list."""
    assert sum(d for _k, _l, d in VENDOR_COST_LINES) == pytest.approx(20.0)


def test_manpower_is_not_a_typed_line():
    assert "manpower" not in [k for k, _l, _d in VENDOR_COST_LINES]


def test_the_default_roster_is_manpowers_old_25_percent():
    """The roster defaults were chosen to land where the typed-in share
    used to sit, so switching to a computed wage bill doesn't silently
    move every other number on the tab."""
    assert _manpower_pct() == pytest.approx(25.0, abs=0.1)


def test_vendor_line_keys_are_unique():
    keys = [k for k, _l, _d in VENDOR_COST_LINES]
    assert len(keys) == len(set(keys))


# --- buying_share_pct ------------------------------------------------------

def test_the_buying_price_is_everything_the_vendor_is_paid():
    """45 food + 25 manpower + 20 operating + 8 vendor profit = 98%."""
    assert buying_share_pct(
        DEFAULT_FOOD_COST_PCT, _defaults(), DEFAULT_VENDOR_PROFIT_PCT,
    ) == pytest.approx(98.0, abs=0.1)


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
    overall = _overall()
    buying = buying_share_pct(45.0, _defaults(), 8.0)
    assert pct_to_abs(buying, overall) == pytest.approx(216.3, abs=0.3)


def test_a_bigger_client_leaves_more_margin():
    """The same team over more plates is cheaper per plate, so the buying
    price falls and SmartQ's margin grows — the whole reason manpower is
    computed rather than assumed."""
    overall = _overall()
    at_150 = abs_to_pct(manpower_per_plate(default_roster(), 150), overall)
    at_400 = abs_to_pct(manpower_per_plate(default_roster(), 400), overall)
    lines = {key: default for key, _label, default in VENDOR_COST_LINES}
    small = smartq_margin_pct(45.0, {**lines, "manpower": at_150}, 8.0)
    large = smartq_margin_pct(45.0, {**lines, "manpower": at_400}, 8.0)
    assert large > small
    assert small == pytest.approx(2.0, abs=0.1)


# --- smartq_margin_pct -----------------------------------------------------

def test_the_defaults_leave_a_margin_for_smartq():
    assert smartq_margin_pct(
        DEFAULT_FOOD_COST_PCT, _defaults(), DEFAULT_VENDOR_PROFIT_PCT,
    ) == pytest.approx(2.0, abs=0.1)


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
