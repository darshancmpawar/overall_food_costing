"""
Vendor / operating cost model.

Splits the fully-loaded overall cost (see ``src.cost.overall_cost``) into the
operating lines a vendor carries — manpower, utilities, consumables, etc. —
each expressed as a share of the overall cost, plus the vendor's own profit.

The overall cost is what SmartQ pays the vendor per plate, so allocating it
answers "where does that money go?":

    food + operating lines + vendor profit + SmartQ share = 100%

Every term except the last is an input. **SmartQ's share is the
remainder** — the part of the buying price the vendor doesn't need, which
accrues to SmartQ. It is a margin, not a cost, so
``src.cost.smartq_cost.smartq_profit`` adds it to SmartQ's profit rather
than to SmartQ's operating cost.

Pure module — no Streamlit, no I/O — so the arithmetic is unit-testable. The
``ui.vendor_cost`` layer renders it and wires up the percentage <-> rupee
inputs.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

# The vendor's own profit, as a share of the overall cost. An input like
# every other line rather than the leftover it used to be: a vendor
# negotiates a margin, it doesn't accept whatever remains.
DEFAULT_VENDOR_PROFIT_PCT = 8.0

# Vendor / operating cost lines: (stable_key, display_label, default_share_pct).
# ``stable_key`` is used to build Streamlit widget keys, so it must not change
# once shipped (changing it resets a live session's inputs to the defaults).
# The order here is the on-screen order. The default shares sum to 45%,
# which with 45% food and 8% vendor profit leaves 2% as SmartQ's share.
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


def smartq_share_pct(
    food_cost_pct: float,
    vendor_pcts: Dict[str, float],
    vendor_profit_pct: float,
) -> float:
    """SmartQ's share: what's left of the 100% once the vendor is paid.

    May be negative when the inputs are over-allocated; the UI surfaces
    that as an error rather than clamping it, so the number stays honest.
    """
    return (
        100.0 - food_cost_pct - sum(vendor_pcts.values()) - vendor_profit_pct
    )


def share_amount(share_pct: float, overall: float,
                 selling_pax: float, working_days: float) -> float:
    """SmartQ's share as money over the period.

    ``share_pct`` of the overall cost per plate, across every plate
    served. This is the figure that lands in SmartQ's profit.
    """
    return round(share_pct / 100.0 * overall * selling_pax * working_days, 2)


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
            f"Vendor profit is {p_pct:.2f}% — below the "
            f"{MIN_HEALTHY_PROFIT_PCT:.0f}% minimum a vendor would accept.",
        )
    if p_pct > MAX_EXPECTED_PROFIT_PCT:
        return ProfitStatus(
            "warning",
            f"Vendor profit is {p_pct:.2f}% — above "
            f"{MAX_EXPECTED_PROFIT_PCT:.0f}%. Double-check it; this margin "
            "looks high for a vendor.",
        )
    return ProfitStatus(
        "ok",
        f"Vendor profit is {p_pct:.2f}% — within the healthy "
        f"{MIN_HEALTHY_PROFIT_PCT:.0f}–{MAX_EXPECTED_PROFIT_PCT:.0f}% range.",
    )


def share_status(share_pct: float) -> ProfitStatus:
    """Validate the leftover that becomes SmartQ's share.

    Negative means the shares above add past 100% — the plate is
    over-allocated and every number downstream is wrong, so it's an
    error. Exactly zero is legal but worth flagging: SmartQ would be
    passing the client's money straight through at no margin.
    """
    if share_pct < 0:
        return ProfitStatus(
            "error",
            f"The shares above add up to {100.0 - share_pct:.2f}% — "
            f"{abs(share_pct):.2f}% more than the plate costs. Reduce a "
            "cost line or the vendor profit.",
        )
    if share_pct == 0:
        return ProfitStatus(
            "warning",
            "Nothing is left for SmartQ: the vendor's costs and profit "
            "account for the whole plate.",
        )
    return ProfitStatus(
        "ok",
        f"SmartQ's share is {share_pct:.2f}% of the plate, credited to "
        "SmartQ profit in the next tab.",
    )
