"""
Vendor / operating cost model.

Splits the fully-loaded overall cost (see ``src.cost.overall_cost``) into the
operating lines a vendor carries — manpower, utilities, consumables, etc. —
each expressed as a share of the overall cost, plus the vendor's own profit.

Those lines are what the vendor is paid, and together they are the **buying
price**: what SmartQ hands over per plate::

    buying price = food + operating lines + vendor profit

Every one of those is an input, and their total is the buying price rather
than the whole plate. What is left between the buying price and the overall
cost is **SmartQ's profit** — an extra margin, not a cost, and deliberately
*outside* the total::

    smartq margin = overall - buying price

``src.cost.smartq_cost`` turns that margin into money over the period and
adds it to SmartQ's revenue.

Pure module — no Streamlit, no I/O — so the arithmetic is unit-testable. The
``ui.vendor_cost`` layer renders it and wires up the percentage <-> rupee
inputs.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

# The vendor's own profit, as a share of the overall cost. An input like
# every other line rather than a leftover: a vendor negotiates a margin,
# it doesn't accept whatever remains.
DEFAULT_VENDOR_PROFIT_PCT = 8.0

# Vendor / operating cost lines: (stable_key, display_label, default_share_pct).
# ``stable_key`` is used to build Streamlit widget keys, so it must not change
# once shipped (changing it resets a live session's inputs to the defaults).
# The order here is the on-screen order. The default shares sum to 45%,
# which with 45% food and 8% vendor profit puts the buying price at 98% of
# the overall cost and leaves 2% as SmartQ's margin.
VENDOR_COST_LINES: List[Tuple[str, str, float]] = [
    ("manpower", "Manpower", 25.0),
    ("electricity", "Electricity & Water", 5.0),
    ("consumables", "Consumables", 3.0),
    ("transport", "Transport", 2.0),
    ("admin", "Admin", 5.0),
    ("depreciation", "Depreciation", 5.0),
]

# Profit guardrails, in percentage points of the overall cost.
MIN_HEALTHY_PROFIT_PCT = 5.0
MAX_EXPECTED_PROFIT_PCT = 10.0


def buying_share_pct(
    food_cost_pct: float,
    vendor_pcts: Dict[str, float],
    vendor_profit_pct: float,
) -> float:
    """Share of the overall cost that SmartQ actually pays the vendor.

    The sum of every input line — food, operating, vendor profit. This is
    the total the Vendor Cost tab shows, and the per-plate buying price it
    converts to is what the SmartQ tab buys at.
    """
    return food_cost_pct + sum(vendor_pcts.values()) + vendor_profit_pct


def smartq_margin_pct(
    food_cost_pct: float,
    vendor_pcts: Dict[str, float],
    vendor_profit_pct: float,
) -> float:
    """SmartQ's profit per plate: overall cost less the buying price.

    May be negative when the inputs are over-allocated (the buying price
    exceeds the overall cost); the UI surfaces that as an error rather
    than clamping it, so the number stays honest.
    """
    return 100.0 - buying_share_pct(
        food_cost_pct, vendor_pcts, vendor_profit_pct,
    )


def extra_margin_amount(margin_pct: float, overall: float,
                        selling_pax: float, working_days: float) -> float:
    """SmartQ's margin as money over the period.

    ``margin_pct`` of the overall cost per plate, across every plate
    served — pax x days. This is the "extra margin" figure that lands in
    SmartQ's revenue.

    The per-plate margin is rounded to the paisa *before* being scaled up,
    because that is the figure the Vendor Cost tab shows and the one the
    buying price is quoted against: buying price + margin per plate is the
    overall cost, so the two period totals reconcile against each other
    instead of drifting by a rounding on every plate.
    """
    per_plate = round(margin_pct / 100.0 * overall, 2)
    return round(per_plate * selling_pax * working_days, 2)


@dataclass(frozen=True)
class ProfitStatus:
    """Validation verdict for a profit share. ``level`` is one of
    ``"ok"`` / ``"warning"`` / ``"error"`` so the UI can pick the right
    Streamlit alert box."""

    level: str
    message: str


def profit_status(p_pct: float) -> ProfitStatus:
    """Classify the vendor's profit share against the healthy band.

    Now that the share is typed in rather than derived, this is advice on
    a number the user chose — so it stays quiet when the figure is
    sensible and speaks up when it isn't.

    < 5%  -> error (too thin to be a real vendor margin)
    > 10% -> warning (verify; the margin looks high)
    else  -> ok
    """
    if p_pct < MIN_HEALTHY_PROFIT_PCT:
        return ProfitStatus(
            "error",
            f"Vendor profit is {p_pct:.1f}% — below the "
            f"{MIN_HEALTHY_PROFIT_PCT:.0f}% minimum a vendor would accept.",
        )
    if p_pct > MAX_EXPECTED_PROFIT_PCT:
        return ProfitStatus(
            "warning",
            f"Vendor profit is {p_pct:.1f}% — above "
            f"{MAX_EXPECTED_PROFIT_PCT:.0f}%. Double-check it; this margin "
            "looks high for a vendor.",
        )
    return ProfitStatus(
        "ok",
        f"Vendor profit is {p_pct:.1f}% — within the healthy "
        f"{MIN_HEALTHY_PROFIT_PCT:.0f}–{MAX_EXPECTED_PROFIT_PCT:.0f}% range.",
    )


def margin_status(margin_pct: float) -> ProfitStatus:
    """Validate SmartQ's margin — the gap between buying price and overall.

    Negative means the buying price has passed the overall cost: the
    inputs are over-allocated and every number downstream is wrong, so
    it's an error. Exactly zero is legal but worth flagging: SmartQ would
    be paying the vendor the entire plate and earning nothing on it.
    """
    if margin_pct < 0:
        return ProfitStatus(
            "error",
            f"The buying price adds up to {100.0 - margin_pct:.1f}% — "
            f"{abs(margin_pct):.1f}% more than the plate costs. Reduce a "
            "cost line or the vendor profit.",
        )
    if margin_pct == 0:
        return ProfitStatus(
            "warning",
            "Nothing is left for SmartQ: the vendor's costs and profit "
            "account for the whole plate.",
        )
    return ProfitStatus(
        "ok",
        f"SmartQ's profit is {margin_pct:.1f}% of the plate, added as "
        "extra margin in SmartQ Costing.",
    )
