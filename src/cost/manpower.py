"""Manpower cost, built from the team the vendor actually staffs.

Manpower used to be a share of the plate typed straight in — 25%, because
that is roughly what it comes to. But a wage bill is not a percentage of
anything: it is a number of people on a number of salaries, and the share
it works out to depends on how many plates that team serves. So it is
computed from the roster instead::

    monthly wage bill = sum(units x monthly salary)      per role
    per day           = monthly wage bill / 30           the whole site
    per plate         = per day / pax per day            what the tab shows

The two divisions matter and are different. Dividing the month by 30 gives
what the team costs the vendor *per day of service*, which is a
site-level figure. The Vendor Cost tab's Amount column is **per plate**,
so that daily figure is then split across the plates served that day. A
team of ten costs the same whether it serves 100 covers or 400; only the
per-plate cost moves.

Salaries are monthly because that is how they are agreed and paid.
Thirty is used as the month rather than the client's service days
deliberately: staff are paid for the month, not for the days the
cafeteria happens to open.

Pure module — no Streamlit, no I/O — so the arithmetic is unit-testable.
``ui.vendor_cost`` renders the roster and feeds the result into the
vendor cost lines.
"""

from typing import Dict, Iterable, List, Mapping, Tuple

# Salaries are monthly; this is the divisor that turns one into a day.
# Not the client's working days: staff are paid for the whole month.
DAYS_PER_SALARY_MONTH = 30

# The roster: (stable_key, display_label, default_units, default_monthly_salary).
# ``stable_key`` builds Streamlit widget keys, so it must not change once
# shipped. The defaults describe a mid-size corporate cafeteria and come
# to a wage bill of Rs 2,78,000 a month — which at 150 pax a day is
# almost exactly the 25% of the plate that manpower was assumed to be
# before it was costed properly. They are a starting point, not a
# recommendation: real salaries vary by city and by contract.
MANPOWER_ROLES: List[Tuple[str, str, int, float]] = [
    ("service_boy", "Service Boy", 6, 22000.0),
    ("supervisor", "Supervisor", 1, 30000.0),
    ("cafeteria_manager", "Cafeteria Manager", 1, 40000.0),
    ("chef", "Chef", 2, 38000.0),
]


def role_monthly_cost(units: float, monthly_salary: float) -> float:
    """One role's monthly wage bill. Negative inputs are treated as zero —
    there is no such thing as a negative headcount."""
    return max(0.0, float(units)) * max(0.0, float(monthly_salary))


def monthly_wage_bill(roster: Mapping[str, Tuple[float, float]]) -> float:
    """Total monthly wage bill across the roster.

    *roster* maps a role key to ``(units, monthly_salary)``.
    """
    return round(
        sum(role_monthly_cost(units, salary)
            for units, salary in roster.values()),
        2,
    )


def daily_wage_bill(monthly: float) -> float:
    """What the team costs per day of service, for the whole site."""
    return round(float(monthly) / DAYS_PER_SALARY_MONTH, 2)


def per_plate_cost(daily: float, pax_per_day: float) -> float:
    """The daily wage bill split across the plates served that day.

    Returns ``0.0`` for a non-positive head count rather than raising, so
    the UI stays finite before a client's pax is known.
    """
    if pax_per_day is None or float(pax_per_day) <= 0:
        return 0.0
    return round(float(daily) / float(pax_per_day), 2)


def manpower_per_plate(roster: Mapping[str, Tuple[float, float]],
                       pax_per_day: float) -> float:
    """The whole chain: roster -> monthly -> daily -> per plate."""
    return per_plate_cost(daily_wage_bill(monthly_wage_bill(roster)),
                          pax_per_day)


def default_roster() -> Dict[str, Tuple[int, float]]:
    """The starting roster, as a ``{key: (units, monthly_salary)}`` map."""
    return {key: (units, salary)
            for key, _label, units, salary in MANPOWER_ROLES}


def role_labels() -> Iterable[Tuple[str, str]]:
    """``(key, label)`` for each role, in display order."""
    return ((key, label) for key, label, _u, _s in MANPOWER_ROLES)
