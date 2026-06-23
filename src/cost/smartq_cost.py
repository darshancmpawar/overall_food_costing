"""
SmartQ cost model.

Builds on the shared overall cost per plate (see ``src.cost.overall_cost``):

    selling_price  = overall_per_plate * 1.30          (30% above cost)
    buying_amount  = overall_per_plate * pax * days
    selling_amount = selling_price     * pax * days

Each operating line is a share of the selling amount. Most are monthly and
taken as-is; the yearly Food Licenses line is divided by 12 so its
monthly-equivalent sits alongside the others when they're summed into the
SmartQ cost.

Pure module — no Streamlit, no I/O — so the arithmetic is unit-testable. The
``ui.smartq_cost`` layer renders it and wires up the percentage <-> rupee
inputs.
"""

from typing import Iterable, List, Tuple

# Selling price is set 30% above the fully-loaded overall cost per plate.
SELLING_PRICE_MARKUP = 0.30

# Defaults for the operating inputs (a typical month).
DEFAULT_WORKING_DAYS = 22
DEFAULT_SELLING_PAX = 150

MONTHS_PER_YEAR = 12

# SmartQ operating cost lines:
#   (stable_key, display_label, default_pct_of_selling_amount, cadence,
#    monthly_divisor)
# ``stable_key`` builds Streamlit widget keys, so it must not change once
# shipped. ``monthly_divisor`` is 1 for monthly lines and 12 for the yearly
# Food Licenses line (2% of the selling amount, spread across the year).
SMARTQ_COST_LINES: List[Tuple[str, str, float, str, int]] = [
    ("manpower_salary", "Manpower Salary", 8.0, "monthly", 1),
    ("tech_licenses", "Tech Licenses", 2.0, "monthly", 1),
    ("food_licenses", "Food Licenses", 2.0, "yearly", MONTHS_PER_YEAR),
    ("cloud", "Cloud", 2.0, "monthly", 1),
    ("depreciation", "Depreciation", 1.0, "monthly", 1),
    ("hseq", "HSEQ", 1.0, "monthly", 1),
    ("miscellaneous", "Miscellaneous", 1.0, "monthly", 1),
    ("up_margin", "UP Margin", 2.0, "monthly", 1),
]


def selling_price(overall_per_plate: float) -> float:
    """Selling price per plate — 30% above the overall cost per plate."""
    return overall_per_plate * (1.0 + SELLING_PRICE_MARKUP)


def buying_amount(overall_per_plate: float, selling_pax: float,
                  working_days: float) -> float:
    """Total cost of producing the plates over the working period."""
    return overall_per_plate * selling_pax * working_days


def selling_amount(sell_price: float, selling_pax: float,
                   working_days: float) -> float:
    """Total revenue over the working period."""
    return sell_price * selling_pax * working_days


def line_abs(pct: float, sell_amount: float, monthly_divisor: int = 1) -> float:
    """Rupee value of a SmartQ cost line: ``pct`` of the selling amount,
    divided by ``monthly_divisor`` (12 for a yearly line shown monthly)."""
    return round(pct / 100.0 * sell_amount / monthly_divisor, 2)


def line_pct(abs_value: float, sell_amount: float,
             monthly_divisor: int = 1) -> float:
    """Inverse of :func:`line_abs` — the share a rupee value represents."""
    if sell_amount <= 0:
        return 0.0
    return abs_value * monthly_divisor / sell_amount * 100.0


def smartq_cost(line_values: Iterable[float]) -> float:
    """SmartQ cost = sum of every operating line's rupee value."""
    return round(sum(line_values), 2)
