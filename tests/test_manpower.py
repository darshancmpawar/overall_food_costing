"""Tests for the manpower cost model (src.cost.manpower)."""

import pytest

from src.cost.manpower import (
    DAYS_PER_SALARY_MONTH,
    MANPOWER_ROLES,
    daily_wage_bill,
    default_roster,
    manpower_per_plate,
    monthly_wage_bill,
    per_plate_cost,
    role_labels,
    role_monthly_cost,
)
from src.cost.overall_cost import abs_to_pct, overall_food_cost


# --- the roster ------------------------------------------------------------

def test_the_four_roles_are_the_ones_a_cafeteria_staffs():
    assert [label for _k, label in role_labels()] == [
        "Service Boy", "Supervisor", "Cafeteria Manager", "Chef",
    ]


def test_role_keys_are_unique():
    keys = [k for k, _l, _u, _s in MANPOWER_ROLES]
    assert len(keys) == len(set(keys))


def test_default_roster_shape():
    roster = default_roster()
    assert set(roster) == {k for k, _l, _u, _s in MANPOWER_ROLES}
    for units, salary in roster.values():
        assert units > 0 and salary > 0


# --- one role --------------------------------------------------------------

def test_a_role_costs_units_times_salary():
    assert role_monthly_cost(6, 22000.0) == 132000.0


def test_no_one_on_the_payroll_costs_nothing():
    assert role_monthly_cost(0, 22000.0) == 0.0
    assert role_monthly_cost(6, 0.0) == 0.0


def test_negative_headcount_is_treated_as_none():
    """A negative unit count is a typo, not a credit."""
    assert role_monthly_cost(-3, 22000.0) == 0.0
    assert role_monthly_cost(3, -22000.0) == 0.0


# --- the chain -------------------------------------------------------------

def test_the_monthly_bill_is_the_sum_of_the_roster():
    assert monthly_wage_bill(default_roster()) == pytest.approx(278000.0)


def test_a_month_is_thirty_days_not_the_service_calendar():
    """Staff are paid for the month, so the divisor is 30 — not the 22
    working days the SmartQ tab quotes its period totals over."""
    assert DAYS_PER_SALARY_MONTH == 30
    assert daily_wage_bill(300000.0) == pytest.approx(10000.0)


def test_the_daily_bill_is_split_across_the_days_plates():
    assert per_plate_cost(9000.0, 150) == pytest.approx(60.0)


def test_no_pax_means_no_per_plate_cost_rather_than_a_crash():
    assert per_plate_cost(9000.0, 0) == 0.0
    assert per_plate_cost(9000.0, None) == 0.0


def test_the_whole_chain_end_to_end():
    # 278,000 a month / 30 = 9,266.67 a day / 150 plates = 61.78 a plate
    assert manpower_per_plate(default_roster(), 150) == pytest.approx(61.78)


def test_the_same_team_costs_less_per_plate_on_a_bigger_site():
    """The point of computing manpower instead of assuming a share: a
    fixed team spread over more covers is cheaper per plate."""
    small = manpower_per_plate(default_roster(), 100)
    large = manpower_per_plate(default_roster(), 400)
    assert small > large
    assert small / large == pytest.approx(4.0, abs=0.01)


def test_the_default_roster_lands_on_the_old_25_percent():
    """The defaults were picked so switching from a typed-in 25% to a
    computed wage bill doesn't move every other figure on the tab."""
    overall = overall_food_cost(111.17, 45.0)
    per_plate = manpower_per_plate(default_roster(), 150)
    assert abs_to_pct(per_plate, overall) == pytest.approx(25.0, abs=0.05)


def test_hiring_one_more_chef_moves_the_plate():
    roster = default_roster()
    roster["chef"] = (3, 38000.0)
    assert monthly_wage_bill(roster) == pytest.approx(316000.0)
    # 38,000 more a month is 1,266.67 a day, 8.44 across 150 plates.
    assert manpower_per_plate(roster, 150) - manpower_per_plate(
        default_roster(), 150,
    ) == pytest.approx(8.45, abs=0.02)


def test_an_empty_roster_costs_nothing():
    assert monthly_wage_bill({}) == 0.0
    assert manpower_per_plate({}, 150) == 0.0


# --- KPI tone (ui.kpi, the one pure function on the presentation side) ------

class TestKpiTone:
    """Colour on the costing panel carries meaning, so the rule that
    picks it is worth pinning."""

    def test_a_profit_is_good_and_a_loss_is_bad(self):
        from ui.kpi import tone_for_amount

        assert tone_for_amount(16302.0) == "good"
        assert tone_for_amount(-16302.0) == "bad"

    def test_exactly_nothing_is_neutral_by_default(self):
        from ui.kpi import tone_for_amount

        assert tone_for_amount(0.0) == "neutral"
        assert tone_for_amount(0.0, zero="warn") == "warn"

    def test_every_tone_defines_a_full_set_of_colours(self):
        from ui.kpi import _TONES

        for tone, colours in _TONES.items():
            assert len(colours) == 4, tone
            assert all(c.startswith("#") for c in colours), tone
