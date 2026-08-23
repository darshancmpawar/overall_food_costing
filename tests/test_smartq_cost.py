"""Tests for the SmartQ cost model (src.cost.smartq_cost)."""

import pytest

from src.cost.smartq_cost import (
    DEFAULT_SELLING_PAX,
    DEFAULT_WORKING_DAYS,
    MIN_MARKUP_PCT,
    MONTHS_PER_YEAR,
    SMARTQ_COST_LINES,
    buying_amount,
    line_abs,
    line_pct,
    markup_pct_from_price,
    selling_amount,
    selling_price,
    smartq_cost,
    smartq_profit,
    smartq_profit_pct,
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
    # End-to-end with the default shares at overall=100, 150 pax, 22 days
    # (selling amount = 130 * 150 * 22 = 429,000).
    sell_amt = selling_amount(selling_price(100.0), DEFAULT_SELLING_PAX,
                              DEFAULT_WORKING_DAYS)
    values = [
        line_abs(default, sell_amt, divisor)
        for _key, _label, default, _cadence, divisor in SMARTQ_COST_LINES
    ]
    assert smartq_cost(values) == pytest.approx(73_645.0, abs=0.01)


# --- smartq_profit ---------------------------------------------------------

def test_smartq_profit_value():
    # revenue 429,000 - buying 330,000 - cost 73,645 = 25,355
    assert smartq_profit(429_000.0, 330_000.0, 73_645.0) == pytest.approx(25_355.0)


def test_smartq_profit_can_be_negative():
    assert smartq_profit(100.0, 80.0, 50.0) == pytest.approx(-30.0)


def test_smartq_profit_pct_of_selling_amount():
    assert smartq_profit_pct(25_355.0, 429_000.0) == pytest.approx(5.91, abs=0.01)


def test_smartq_profit_pct_zero_selling_is_safe():
    assert smartq_profit_pct(100.0, 0.0) == 0.0


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

# ---------------------------------------------------------------------------
# Configurable markup and its inverse
# ---------------------------------------------------------------------------

class TestSellingMarkup:
    def test_default_markup_is_30_percent(self):
        from src.cost.smartq_cost import DEFAULT_SELLING_MARKUP_PCT

        assert DEFAULT_SELLING_MARKUP_PCT == 30.0
        assert selling_price(100.0) == pytest.approx(130.0)

    @pytest.mark.parametrize("markup,expected", [
        (0.0, 100.0), (25.0, 125.0), (30.0, 130.0), (55.5, 155.5),
    ])
    def test_markup_is_applied(self, markup, expected):
        assert selling_price(100.0, markup) == pytest.approx(expected)

    def test_price_and_markup_round_trip(self):
        from src.cost.smartq_cost import markup_pct_from_price

        overall = 247.04
        for markup in (0.0, 12.5, 30.0, 47.3):
            price = selling_price(overall, markup)
            assert markup_pct_from_price(price, overall) == pytest.approx(markup)

    def test_a_price_below_cost_implies_a_negative_markup(self):
        """Selling under cost is a real (bad) scenario, not an error to
        swallow — the number has to stay honest."""
        from src.cost.smartq_cost import markup_pct_from_price

        assert markup_pct_from_price(90.0, 100.0) == pytest.approx(-10.0)

    def test_no_overall_cost_gives_a_zero_markup(self):
        """Before a plan is costed there is nothing to mark up; the UI
        needs a finite number rather than a division by zero."""
        from src.cost.smartq_cost import markup_pct_from_price

        assert markup_pct_from_price(150.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# The vendor's leftover share, credited to profit
# ---------------------------------------------------------------------------

class TestVendorShareCredit:
    def test_share_is_added_to_profit(self):
        without = smartq_profit(1000.0, 700.0, 100.0)
        with_share = smartq_profit(1000.0, 700.0, 100.0, vendor_share=50.0)
        assert without == 200.0
        assert with_share == 250.0

    def test_share_defaults_to_nothing(self):
        assert smartq_profit(1000.0, 700.0, 100.0) == 200.0

    def test_crediting_the_share_equals_buying_cheaper(self):
        """The credit is presentation, not extra money: adding it to
        profit is the same arithmetic as buying at (overall - share)."""
        credited = smartq_profit(1000.0, 700.0, 100.0, vendor_share=30.0)
        bought_cheaper = smartq_profit(1000.0, 670.0, 100.0)
        assert credited == bought_cheaper

    def test_the_share_does_not_touch_the_cost_lines(self):
        """It is a margin, so it must not inflate SmartQ's cost total."""
        lines = [10.0, 20.0, 30.0]
        assert smartq_cost(lines) == 60.0

    def test_a_negative_share_reduces_profit(self):
        """An over-allocated plate means SmartQ is short, and the profit
        must show it rather than clamping at zero."""
        assert smartq_profit(1000.0, 700.0, 100.0, vendor_share=-50.0) == 150.0

    def test_end_to_end_with_the_defaults(self):
        """The whole chain on realistic numbers, so a change to any one
        constant that breaks the arithmetic shows up here."""
        from src.cost.vendor_cost import (
            DEFAULT_VENDOR_PROFIT_PCT, VENDOR_COST_LINES, share_amount,
            smartq_share_pct,
        )

        overall, pax, days = 247.04, 150, 22
        price = selling_price(overall)                       # 30% markup
        sell = selling_amount(price, pax, days)
        buy = buying_amount(overall, pax, days)
        cost = smartq_cost(
            line_abs(d, sell, div)
            for _k, _l, d, _c, div in SMARTQ_COST_LINES
        )
        share_pct = smartq_share_pct(
            45.0, {k: d for k, _l, d in VENDOR_COST_LINES},
            DEFAULT_VENDOR_PROFIT_PCT,
        )
        share = share_amount(share_pct, overall, pax, days)

        assert share_pct == pytest.approx(2.0)
        plain = smartq_profit(sell, buy, cost)
        credited = smartq_profit(sell, buy, cost, share)
        assert credited > plain
        assert credited - plain == pytest.approx(share)
        assert smartq_profit_pct(credited, sell) > 0


class TestBelowCostPricing:
    """A price under the fully-loaded cost is a real bid, not an error, and
    the markup that comes back must stay inside the input's range."""

    def test_a_price_below_cost_gives_a_negative_markup(self):
        assert markup_pct_from_price(200.0, 250.0) == pytest.approx(-20.0)

    def test_a_free_plate_is_minus_one_hundred(self):
        assert markup_pct_from_price(0.0, 250.0) == pytest.approx(-100.0)

    def test_the_markup_never_falls_below_the_input_floor(self):
        """The UI's Markup % input is bounded at MIN_MARKUP_PCT; a value
        under it would be rejected when written back into the widget."""
        assert markup_pct_from_price(-500.0, 250.0) == MIN_MARKUP_PCT
        assert MIN_MARKUP_PCT == -100.0

    def test_a_negative_markup_round_trips_through_the_price(self):
        price = selling_price(250.0, -20.0)
        assert price == pytest.approx(200.0)
        assert markup_pct_from_price(price, 250.0) == pytest.approx(-20.0)

    def test_selling_below_cost_loses_money(self):
        overall, pax, days = 250.0, 150, 22
        sell = selling_amount(selling_price(overall, -20.0), pax, days)
        buy = buying_amount(overall, pax, days)
        assert smartq_profit(sell, buy, 0.0) < 0
