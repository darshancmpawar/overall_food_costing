"""
Shared scaling primitives for the overall operating-cost estimate.

The solver gives a per-person food cost for each day. Averaged across the plan
that figure is the *food cost* — but food is only one slice of what it costs to
actually run the operation. The working assumption is that food is ~45% of the
fully-loaded cost, so scaling the average food cost up from that 45% share to
100% gives the "overall food cost" the operation should price against::

    overall = average_food_cost / (food_cost_pct / 100)

Both costing models build on this: the vendor-cost model
(``src.cost.vendor_cost``) breaks the overall cost into operating lines, and
the SmartQ model (``src.cost.smartq_cost``) will layer its own model on top.
The percentage <-> rupee conversion helpers live here too since both models
share them.

This module is intentionally pure — no Streamlit, no I/O — so the arithmetic is
unit-testable. The Streamlit layer renders it.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

# Default food-cost share of the fully-loaded operating cost.
DEFAULT_FOOD_COST_PCT = 45.0


def _parse_money(value: Any) -> Optional[float]:
    """Pull the first numeric token out of a display string like '₹148.50'.

    Returns ``None`` when nothing numeric is present. Tolerates thousands
    separators ('₹1,234.50') and currency symbols on either side.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d[\d,]*\.?\d*", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def day_costs_from_cost_data(cost_data: Dict[str, Any]) -> List[float]:
    """Extract the numeric per-day food costs from the UI ``cost_data`` dict.

    Prefers the numeric ``day_cost_total``; falls back to parsing the
    ``day_cost_display`` rupee string for plans that were costed before the
    numeric field existed. Days with neither are skipped.
    """
    costs: List[float] = []
    for day in cost_data.values():
        if not isinstance(day, dict):
            continue
        value = day.get("day_cost_total")
        if value is None:
            value = _parse_money(day.get("day_cost_display"))
        if value is not None:
            costs.append(float(value))
    return costs


def average_food_cost(day_costs: Iterable[Optional[float]]) -> float:
    """Mean per-person food cost across the days that have a cost.

    ``None`` entries (days with no cost data) are ignored. Returns ``0.0``
    when nothing is costed so callers can branch on a single truthiness check.
    """
    values = [float(c) for c in day_costs if c is not None]
    if not values:
        return 0.0
    return sum(values) / len(values)


def overall_food_cost(avg_food_cost: float, food_cost_pct: float) -> float:
    """Scale the average food cost up from its share to the full 100%.

    Returns ``0.0`` when the share is non-positive — that's a nonsensical
    input the UI guards against, and returning 0 keeps every downstream
    multiplication finite instead of raising.
    """
    if food_cost_pct <= 0:
        return 0.0
    return avg_food_cost / (food_cost_pct / 100.0)


def pct_to_abs(pct: float, overall: float) -> float:
    """Rupee amount for a percentage share of the overall cost (2 dp)."""
    return round(pct / 100.0 * overall, 2)


def abs_to_pct(abs_value: float, overall: float) -> float:
    """Percentage share that a rupee amount represents of the overall cost."""
    if overall <= 0:
        return 0.0
    return abs_value / overall * 100.0
