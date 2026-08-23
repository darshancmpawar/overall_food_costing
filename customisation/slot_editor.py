"""
Category Editor -- Toggle categories on/off for a client.
"""

import streamlit as st
from typing import List

from ui import theme as t
from ui.cards import card_header
from ui.formatters import prettify_slot_name


def render_slot_editor(
    all_base_slots: List[str],
    current_active: List[str],
    const_slots: List[str],
    client_name: str = "",
) -> List[str]:
    """Render category toggle UI. Returns the list of selected base categories."""

    toggleable = [s for s in all_base_slots if s not in const_slots]
    active_set = set(current_active)

    with st.container(border=True):
        card_header(
            "Categories",
            "Toggle which categories this client uses. Constant items "
            "(White Rice, Papad, Pickle, Chutney) are always included.",
        )
        selected = st.multiselect(
            "Active Categories",
            options=toggleable,
            default=[s for s in toggleable if s in active_set],
            format_func=prettify_slot_name,
            key=f"editor_slot_multiselect_{client_name}",
            label_visibility="collapsed",
        )

        if selected:
            st.markdown(
                f'<p style="font-size:0.75rem;color:{t.TEXT_3};margin:0.25rem 0 0;">'
                f'{len(selected)} of {len(toggleable)} categories active</p>',
                unsafe_allow_html=True,
            )

    return selected
