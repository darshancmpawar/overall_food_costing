"""
Vendor Cost tab.

Scales the average plate food cost up to a fully-loaded operating cost and
breaks it into editable lines — the vendor's operating costs and its
profit — leaving SmartQ's share as the remainder. The arithmetic lives in
``src.cost.overall_cost`` (shared scaling) and ``src.cost.vendor_cost``
(lines, profit, share); this module only renders it and wires up the
two-way percentage <-> rupee inputs.

Two-way sync, Streamlit-style: the percentage is the single source of truth.
Each interactive line keeps a ``..._pct`` and a ``..._abs`` widget; their
``on_change`` callbacks convert one into the other and write the partner
widget's value *before* the rerun re-instantiates it (the supported pattern).
The overall cost is anchored by the food-cost share, so editing a vendor line's
rupee amount moves that line's percentage (and therefore profit) while leaving
the overall total fixed.

Session-state keys are prefixed ``vc_``.
"""

import streamlit as st

from src.cost.overall_cost import (
    DEFAULT_FOOD_COST_PCT,
    abs_to_pct,
    overall_food_cost,
    pct_to_abs,
)
from src.cost.vendor_cost import (
    DEFAULT_VENDOR_PROFIT_PCT,
    VENDOR_COST_LINES,
    profit_status,
    share_status,
    smartq_share_pct,
)

# The vendor's profit is edited exactly like an operating cost line, so it
# reuses the same two-way percentage/rupee machinery. Its key follows the
# same ``vc_<key>_pct`` / ``vc_<key>_abs`` convention.
_PROFIT_KEY = "profit"


def _cols(weights):
    """``st.columns`` with centered vertical alignment when the installed
    Streamlit supports it (>=1.36), falling back gracefully otherwise."""
    try:
        return st.columns(weights, vertical_alignment="center")
    except TypeError:
        return st.columns(weights)


def _current_overall() -> float:
    """Overall cost from the current session inputs — safe to call inside a
    widget callback, which runs before the script reruns."""
    ss = st.session_state
    return overall_food_cost(
        ss.get("vc_avg_food_cost", 0.0),
        ss.get("vc_food_cost_pct", DEFAULT_FOOD_COST_PCT),
    )


def _editable_keys():
    """Keys of every row whose percentage the user can set — the operating
    lines plus the vendor's profit."""
    return [key for key, _label, _default in VENDOR_COST_LINES] + [_PROFIT_KEY]


def _on_food_pct_change() -> None:
    # Food share moves the overall total, so every vendor line's rupee amount
    # has to be re-derived from its (unchanged) percentage.
    overall = _current_overall()
    for key in _editable_keys():
        st.session_state[f"vc_{key}_abs"] = pct_to_abs(
            st.session_state[f"vc_{key}_pct"], overall
        )


def _on_pct_change(key: str) -> None:
    st.session_state[f"vc_{key}_abs"] = pct_to_abs(
        st.session_state[f"vc_{key}_pct"], _current_overall()
    )


def _on_abs_change(key: str) -> None:
    st.session_state[f"vc_{key}_pct"] = abs_to_pct(
        st.session_state[f"vc_{key}_abs"], _current_overall()
    )


def _seed_state(avg: float) -> None:
    """Seed the widget values once, and re-derive the rupee amounts whenever
    the average food cost changes (e.g. after a regenerate) so a stale amount
    never lingers next to a fresh percentage."""
    ss = st.session_state
    ss.vc_avg_food_cost = avg

    if "vc_food_cost_pct" not in ss:
        ss.vc_food_cost_pct = DEFAULT_FOOD_COST_PCT
        for key, _label, default in VENDOR_COST_LINES:
            ss[f"vc_{key}_pct"] = default
        ss[f"vc_{_PROFIT_KEY}_pct"] = DEFAULT_VENDOR_PROFIT_PCT

    if ss.get("vc_seed_avg") != avg:
        ss.vc_seed_avg = avg
        overall = overall_food_cost(avg, ss.vc_food_cost_pct)
        for key in _editable_keys():
            ss[f"vc_{key}_abs"] = pct_to_abs(ss[f"vc_{key}_pct"], overall)


def render_vendor_cost(avg: float) -> None:
    """Render the Vendor Cost tab for an average plate food cost of ``avg``."""
    ss = st.session_state

    if avg <= 0:
        st.warning(
            "This plan has no food-cost data (the source sheet is missing the "
            "cost columns), so the overall cost can't be estimated."
        )
        return

    _seed_state(avg)
    overall = overall_food_cost(avg, ss.vc_food_cost_pct)

    st.caption(
        "Food cost is the average plate cost across every day in the generated "
        "plan. It's only one slice of what the operation costs to run — scaling "
        "it up from its share to 100% gives the overall cost to price against."
    )

    m1, m2 = st.columns(2)
    m1.metric("Avg Food Cost / plate", f"₹{avg:,.2f}")
    m2.metric("Overall Cost / plate", f"₹{overall:,.2f}")

    st.divider()

    head = _cols([2.4, 1.1, 1.4])
    head[0].markdown("**Cost line**")
    head[1].markdown("**Share %**")
    head[2].markdown("**Amount (₹)**")

    # Food cost: the share is editable (it's the scaling anchor); the rupee
    # amount is fixed — it's the average plate cost the menu actually produced.
    food = _cols([2.4, 1.1, 1.4])
    food[0].markdown("Food Cost")
    food[1].number_input(
        "Food cost share %", key="vc_food_cost_pct",
        min_value=1.0, max_value=100.0, step=1.0, format="%.2f",
        label_visibility="collapsed", on_change=_on_food_pct_change,
    )
    food[2].markdown(f"₹{avg:,.2f}")

    # Vendor lines: percentage and rupee amount, kept in sync both ways.
    for key, label, _default in VENDOR_COST_LINES:
        row = _cols([2.4, 1.1, 1.4])
        row[0].markdown(label)
        row[1].number_input(
            f"{label} share %", key=f"vc_{key}_pct",
            min_value=0.0, step=0.5, format="%.2f",
            label_visibility="collapsed",
            on_change=_on_pct_change, args=(key,),
        )
        row[2].number_input(
            f"{label} amount", key=f"vc_{key}_abs",
            min_value=0.0, step=1.0, format="%.2f",
            label_visibility="collapsed",
            on_change=_on_abs_change, args=(key,),
        )

    # The vendor's profit: an input like the lines above it, not a
    # leftover. A vendor negotiates a margin; it doesn't accept whatever
    # happens to remain.
    st.divider()
    prof = _cols([2.4, 1.1, 1.4])
    prof[0].markdown("**Vendor Profit**")
    prof[1].number_input(
        "Vendor profit share %", key=f"vc_{_PROFIT_KEY}_pct",
        min_value=0.0, step=0.5, format="%.2f",
        label_visibility="collapsed",
        on_change=_on_pct_change, args=(_PROFIT_KEY,),
    )
    prof[2].number_input(
        "Vendor profit amount", key=f"vc_{_PROFIT_KEY}_abs",
        min_value=0.0, step=1.0, format="%.2f",
        label_visibility="collapsed",
        on_change=_on_abs_change, args=(_PROFIT_KEY,),
    )

    # Whatever is left of the plate is SmartQ's, and it is a margin rather
    # than a cost — the SmartQ tab credits it to profit.
    vendor_pcts = {key: ss[f"vc_{key}_pct"] for key, _l, _d in VENDOR_COST_LINES}
    vendor_profit = ss[f"vc_{_PROFIT_KEY}_pct"]
    share_pct = smartq_share_pct(
        ss.vc_food_cost_pct, vendor_pcts, vendor_profit,
    )
    share_abs = pct_to_abs(share_pct, overall)
    # Published for the SmartQ tab, which turns it into money over the
    # period and adds it to SmartQ's profit.
    ss.vc_smartq_share_pct = share_pct

    share = _cols([2.4, 1.1, 1.4])
    share[0].markdown("**SmartQ Share (remaining)**")
    share[1].markdown(f"**{share_pct:.2f}%**")
    share[2].markdown(f"**₹{share_abs:,.2f}**")

    total = _cols([2.4, 1.1, 1.4])
    total[0].markdown("**Total**")
    total[1].markdown("**100.00%**")
    total[2].markdown(f"**₹{overall:,.2f}**")

    # Two things can be wrong here, and they're different problems: the
    # shares can over-allocate the plate (arithmetic), or the vendor's
    # margin can be unrealistic (judgement). Show the first always, the
    # second only when it needs saying.
    status = share_status(share_pct)
    {"error": st.error, "warning": st.warning, "ok": st.success}[status.level](
        status.message
    )
    profit_verdict = profit_status(vendor_profit)
    if profit_verdict.level != "ok":
        {"error": st.error, "warning": st.warning}[profit_verdict.level](
            profit_verdict.message
        )
