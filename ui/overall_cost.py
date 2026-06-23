"""
"Overall Estimated Cost" UI — a button on the planner that opens a costing
panel with two tabs:

    * Vendor Cost  — scales the average plate food cost up to a fully-loaded
      operating cost and breaks it down into editable operating lines, with a
      live profit readout and guardrails.
    * SmartQ Costing — placeholder; the model lands in a later update.

The arithmetic lives in ``src.cost.overall_cost`` (pure + unit-tested). This
module only renders it and wires up the two-way percentage <-> rupee inputs.

Two-way sync, Streamlit-style: the percentage is the single source of truth.
Each interactive line keeps a ``..._pct`` and a ``..._abs`` widget; their
``on_change`` callbacks convert one into the other and write the partner
widget's value *before* the rerun re-instantiates it (the supported pattern).
The overall cost is anchored by the food-cost share, so editing a vendor line's
rupee amount moves that line's percentage (and therefore profit) while leaving
the overall total fixed.
"""

import streamlit as st

from src.cost.overall_cost import (
    DEFAULT_FOOD_COST_PCT,
    VENDOR_COST_LINES,
    abs_to_pct,
    average_food_cost,
    day_costs_from_cost_data,
    overall_food_cost,
    pct_to_abs,
    profit_pct,
    profit_status,
)


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
        ss.get("oc_avg_food_cost", 0.0),
        ss.get("oc_food_cost_pct", DEFAULT_FOOD_COST_PCT),
    )


def _on_food_pct_change() -> None:
    # Food share moves the overall total, so every vendor line's rupee amount
    # has to be re-derived from its (unchanged) percentage.
    overall = _current_overall()
    for key, _label, _default in VENDOR_COST_LINES:
        st.session_state[f"oc_{key}_abs"] = pct_to_abs(
            st.session_state[f"oc_{key}_pct"], overall
        )


def _on_pct_change(key: str) -> None:
    st.session_state[f"oc_{key}_abs"] = pct_to_abs(
        st.session_state[f"oc_{key}_pct"], _current_overall()
    )


def _on_abs_change(key: str) -> None:
    st.session_state[f"oc_{key}_pct"] = abs_to_pct(
        st.session_state[f"oc_{key}_abs"], _current_overall()
    )


def _seed_state(avg: float) -> None:
    """Seed the widget values once, and re-derive the rupee amounts whenever
    the average food cost changes (e.g. after a regenerate) so a stale amount
    never lingers next to a fresh percentage."""
    ss = st.session_state
    ss.oc_avg_food_cost = avg

    if "oc_food_cost_pct" not in ss:
        ss.oc_food_cost_pct = DEFAULT_FOOD_COST_PCT
        for key, _label, default in VENDOR_COST_LINES:
            ss[f"oc_{key}_pct"] = default

    if ss.get("oc_seed_avg") != avg:
        ss.oc_seed_avg = avg
        overall = overall_food_cost(avg, ss.oc_food_cost_pct)
        for key, _label, _default in VENDOR_COST_LINES:
            ss[f"oc_{key}_abs"] = pct_to_abs(ss[f"oc_{key}_pct"], overall)


def _render_vendor_cost(avg: float) -> None:
    ss = st.session_state

    if avg <= 0:
        st.warning(
            "This plan has no food-cost data (the source sheet is missing the "
            "cost columns), so the overall cost can't be estimated."
        )
        return

    _seed_state(avg)
    overall = overall_food_cost(avg, ss.oc_food_cost_pct)

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
        "Food cost share %", key="oc_food_cost_pct",
        min_value=1.0, max_value=100.0, step=1.0, format="%.2f",
        label_visibility="collapsed", on_change=_on_food_pct_change,
    )
    food[2].markdown(f"₹{avg:,.2f}")

    # Vendor lines: percentage and rupee amount, kept in sync both ways.
    for key, label, _default in VENDOR_COST_LINES:
        row = _cols([2.4, 1.1, 1.4])
        row[0].markdown(label)
        row[1].number_input(
            f"{label} share %", key=f"oc_{key}_pct",
            min_value=0.0, step=0.5, format="%.2f",
            label_visibility="collapsed",
            on_change=_on_pct_change, args=(key,),
        )
        row[2].number_input(
            f"{label} amount", key=f"oc_{key}_abs",
            min_value=0.0, step=1.0, format="%.2f",
            label_visibility="collapsed",
            on_change=_on_abs_change, args=(key,),
        )

    # Profit is the remainder — read-only, derived from the shares above.
    vendor_pcts = {key: ss[f"oc_{key}_pct"] for key, _l, _d in VENDOR_COST_LINES}
    p_pct = profit_pct(ss.oc_food_cost_pct, vendor_pcts)
    p_abs = pct_to_abs(p_pct, overall)

    st.divider()
    profit = _cols([2.4, 1.1, 1.4])
    profit[0].markdown("**Profit (remaining)**")
    profit[1].markdown(f"**{p_pct:.2f}%**")
    profit[2].markdown(f"**₹{p_abs:,.2f}**")

    total = _cols([2.4, 1.1, 1.4])
    total[0].markdown("**Total**")
    total[1].markdown("**100.00%**")
    total[2].markdown(f"**₹{overall:,.2f}**")

    status = profit_status(p_pct)
    {"error": st.error, "warning": st.warning, "ok": st.success}[status.level](
        status.message
    )


def _render_panel(avg: float) -> None:
    vendor_tab, smartq_tab = st.tabs(["Vendor Cost", "SmartQ Costing"])
    with vendor_tab:
        _render_vendor_cost(avg)
    with smartq_tab:
        st.info("SmartQ costing — the model lands in the next update.")


def render_overall_estimated_cost(cost_data: dict) -> None:
    """Render the "Overall Estimated Cost" button and its costing panel.

    Opens in a modal dialog when the installed Streamlit supports one
    (``st.dialog``, >=1.37, or the older ``st.experimental_dialog``), and
    falls back to an inline expandable panel otherwise so the feature works
    across the supported Streamlit range.
    """
    avg = average_food_cost(day_costs_from_cost_data(cost_data))

    dialog_fn = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)

    if dialog_fn is not None:
        try:
            decorator = dialog_fn("Overall Estimated Cost", width="large")
        except TypeError:
            # Older signatures predate the `width` keyword.
            decorator = dialog_fn("Overall Estimated Cost")

        @decorator
        def _dialog() -> None:
            _render_panel(avg)

        if st.button("Overall Estimated Cost", key="open_overall_cost_btn",
                     type="primary", use_container_width=True):
            _dialog()
        return

    # Fallback: toggle an inline panel below the button.
    if st.button("Overall Estimated Cost", key="open_overall_cost_btn",
                 type="primary", use_container_width=True):
        st.session_state.oc_show_inline = not st.session_state.get("oc_show_inline", False)
    if st.session_state.get("oc_show_inline"):
        with st.container(border=True):
            _render_panel(avg)
