"""
SmartQ Costing tab.

Placeholder until the SmartQ cost model is specified. When it lands, the pure
arithmetic goes in ``src.cost.smartq_cost`` and this module renders it —
mirroring how ``ui.vendor_cost`` pairs with ``src.cost.vendor_cost``.

Takes the same average plate food cost as the other tabs so it can scale off
the shared overall cost once the model is defined.
"""

import streamlit as st


def render_smartq_cost(avg: float) -> None:
    """Render the SmartQ Costing tab for an average plate food cost of ``avg``.

    ``avg`` is accepted now so the tab signature is stable; it feeds the
    SmartQ model once that's specified.
    """
    st.info("SmartQ costing — the model lands in the next update.")
