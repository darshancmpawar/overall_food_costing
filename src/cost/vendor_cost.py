"""
Vendor / operating cost model.

Splits the fully-loaded overall cost (see ``src.cost.overall_cost``) into the
operating lines a vendor carries — manpower, utilities, consumables, etc. —
each expressed as a share of the overall cost. Profit is whatever share is
left over once food and every operating line are accounted for, and it's
validated against a healthy band.

Pure module — no Streamlit, no I/O — so the arithmetic is unit-testable. The
``ui.vendor_cost`` layer renders it and wires up the percentage <-> rupee
inputs.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

# Vendor / operating cost lines: (stable_key, display_label, default_share_pct).
# ``stable_key`` is used to build Streamlit widget keys, so it must not change
# once shipped (changing it resets a live session's inputs to the defaults).
# The order here is the on-screen order. The default shares sum to 45%, which
# leaves the default profit at 100 - 45 (food) - 45 (vendor) = 10%.
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


def profit_pct(food_cost_pct: float, vendor_pcts: Dict[str, float]) -> float:
    """Profit is whatever share of the 100% is left after food + vendors.

    May be negative when the lines are over-allocated; the UI surfaces that
    as an error rather than clamping it, so the number stays honest.
    """
    return 100.0 - food_cost_pct - sum(vendor_pcts.values())


@dataclass(frozen=True)
class ProfitStatus:
    """Validation verdict for a profit share. ``level`` is one of
    ``"ok"`` / ``"warning"`` / ``"error"`` so the UI can pick the right
    Streamlit alert box."""

    level: str
    message: str


def profit_status(p_pct: float) -> ProfitStatus:
    """Classify a profit percentage against the healthy band.

    < 5%  -> error (too thin / over-allocated)
    > 10% -> warning (verify; the margin looks high)
    else  -> ok
    """
    if p_pct < MIN_HEALTHY_PROFIT_PCT:
        return ProfitStatus(
            "error",
            f"Vendor profit is {p_pct:.2f}% — below the "
            f"{MIN_HEALTHY_PROFIT_PCT:.0f}% minimum. Lower the cost shares "
            "above before committing to these numbers.",
        )
    if p_pct > MAX_EXPECTED_PROFIT_PCT:
        return ProfitStatus(
            "warning",
            f"Vendor profit is {p_pct:.2f}% — above "
            f"{MAX_EXPECTED_PROFIT_PCT:.0f}%. Double-check the cost shares; "
            "this margin looks high.",
        )
    return ProfitStatus(
        "ok",
        f"Vendor profit is {p_pct:.2f}% — within the healthy "
        f"{MIN_HEALTHY_PROFIT_PCT:.0f}–{MAX_EXPECTED_PROFIT_PCT:.0f}% range.",
    )
