"""
"Overall Estimated Cost" entry point — a button on the planner that opens a
costing panel with two independent tabs:

    * Vendor Cost   — ``ui.vendor_cost.render_vendor_cost``
    * SmartQ Costing — ``ui.smartq_cost.render_smartq_cost``

This module only owns the button, the dialog/inline shell, and the shared
average-food-cost figure both tabs work off. Each tab's rendering and model
live in its own module so the two costing types stay independent.
"""

import streamlit as st

from src.cost.overall_cost import average_food_cost, day_costs_from_cost_data
from ui.smartq_cost import render_smartq_cost
from ui.vendor_cost import render_vendor_cost


def _render_panel(avg: float) -> None:
    vendor_tab, smartq_tab = st.tabs(["Vendor Cost", "SmartQ Costing"])
    with vendor_tab:
        render_vendor_cost(avg)
    with smartq_tab:
        render_smartq_cost(avg)


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
