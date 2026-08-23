"""
SmartQ cost model.

Builds on the shared overall cost per plate (see ``src.cost.overall_cost``):

    selling_price  = overall_per_plate * (1 + markup)  (markup defaults to 30%)
    buying_amount  = overall_per_plate * pax * days
    selling_amount = selling_price     * pax * days

The markup is an input, and so is the selling price it produces — the two
are two views of one number, so the UI keeps them in step. Quoting a
round price per plate is often how a deal is actually discussed, and
working back to the implied markup is more useful than forcing the
operator to do that arithmetic.

Each operating line is a share of the selling amount. Most are monthly and
taken as-is; the yearly Food Licenses line is divided by 12 so its
monthly-equivalent sits alongside the others when they're summed into the
SmartQ cost.

SmartQ's profit also picks up the share of the plate the vendor doesn't
need (see ``src.cost.vendor_cost.smartq_share_pct``). That share is a
margin, not an operating cost, so it is added to profit — equivalently,
SmartQ buys at less than the full overall cost and keeps the difference.

Pure module — no Streamlit, no I/O — so the arithmetic is unit-testable. The
``ui.smartq_cost`` layer renders it and wires up the percentage <-> rupee
inputs.
"""

from typing import Iterable, List, Tuple

# Default markup over the fully-loaded overall cost per plate, in percent.
DEFAULT_SELLING_MARKUP_PCT = 30.0

# Kept as a fraction for callers that predate the configurable markup.
SELLING_PRICE_MARKUP = DEFAULT_SELLING_MARKUP_PCT / 100.0

# A markup can be negative — a bid below the fully-loaded cost is a real
# (if unhappy) position, and the model should show the loss rather than
# refuse the number. -100% is a free plate, which is the floor: below it
# SmartQ would be paying people to eat.
MIN_MARKUP_PCT = -100.0

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


def selling_price(overall_per_plate: float,
                  markup_pct: float = DEFAULT_SELLING_MARKUP_PCT) -> float:
    """Selling price per plate — *markup_pct* above the overall cost."""
    return overall_per_plate * (1.0 + markup_pct / 100.0)


def markup_pct_from_price(price: float, overall_per_plate: float) -> float:
    """The markup a given selling price implies — inverse of
    :func:`selling_price`.

    Returns ``0.0`` when there is no overall cost to mark up, so the UI
    stays finite before a plan has been costed. A price below the overall
    cost gives a negative markup — the loss is the answer, not an error —
    floored at :data:`MIN_MARKUP_PCT` so the value stays inside the range
    the markup input accepts.
    """
    if overall_per_plate <= 0:
        return 0.0
    return max(MIN_MARKUP_PCT, (price / overall_per_plate - 1.0) * 100.0)


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


def smartq_profit(sell_amount: float, buy_amount: float,
                  total_cost: float, vendor_share: float = 0.0) -> float:
    """Net SmartQ profit over the period.

    Revenue, less the plates bought from the vendor, less SmartQ's own
    operating cost, **plus** the share of the plate the vendor doesn't
    need (:func:`src.cost.vendor_cost.share_amount`).

    That last term is a credit rather than a cost reduction only in
    presentation: ``buy_amount`` is quoted at the full overall cost, so
    adding the share back is the same arithmetic as buying at
    ``overall - share`` and says more plainly where the money came from.
    """
    return round(sell_amount - buy_amount - total_cost + vendor_share, 2)


def smartq_profit_pct(profit: float, sell_amount: float) -> float:
    """SmartQ profit as a percentage of revenue (the selling amount).

    Returns ``0.0`` when there's no revenue so the UI stays finite.
    """
    if sell_amount <= 0:
        return 0.0
    return profit / sell_amount * 100.0
