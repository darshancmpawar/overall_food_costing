"""Cost Estimator setup panel — the "new client" mode of the planner.

Sales and ops price a *prospective* client by describing the menu they'd
serve — name, categories, per-category frequency, and day themes — then
generating a plan from it and reading the costing panel. Nothing here is
written to the database: the client doesn't exist yet, and an estimate
that half-created one would leave the client list littered with deals
that never closed.

The four controls reuse the same editor components the customisation page
uses (:mod:`customisation.slot_editor`, ``multi_slot_editor``,
``theme_editor``), so a setup entered here looks and behaves exactly like
a stored counter's config. The difference is purely where it goes: the
dict this module returns is POSTed to ``/api/v1/estimate-plan`` and then
lives in ``st.session_state`` for as long as the browser tab does.

Session-state keys are prefixed ``est_``; the editor components' widget
keys are namespaced by the ``_estimator_`` client key.
"""

from typing import Any, Dict, List, Optional

import streamlit as st

from customisation.slot_editor import render_slot_editor
from customisation.multi_slot_editor import render_multi_slot_editor
from customisation.theme_editor import render_theme_editor
from ui import theme as t
from ui.cards import inject_card_css

# Namespace for the reused editor components' widget keys. Distinct from
# any real client name so switching between the editor page and this panel
# can't collide on a widget key.
_KEY = "_estimator_"


def _default_categories(metadata: Dict[str, Any]) -> List[str]:
    """A sensible starting menu for a new estimate.

    Defaults to ``required_pool_slots`` — the slots the ontology is
    guaranteed to be able to fill — rather than every slot it knows
    about. Starting with all of them would include the niche opt-in
    lines (combined dal/sambar, curd rice) whose pools can legitimately
    be empty, so a fresh estimate would open on a pre-flight error
    instead of a menu. Operators add those deliberately.
    """
    const = set(metadata.get("const_slots") or [])
    required = metadata.get("required_pool_slots") or []
    if required:
        return [s for s in required if s not in const]
    # Older backend without the field: fall back to everything non-constant.
    return [s for s in (metadata.get("base_slot_names") or []) if s not in const]


def render_estimator_setup(
    metadata: Dict[str, Any],
    *,
    expanded: bool = True,
) -> Optional[Dict[str, Any]]:
    """Render the setup expander and the Generate Menu button below it.

    Returns the estimator config dict when the user clicks Generate and
    the setup is valid, otherwise ``None``. The config shape is exactly
    what ``/api/v1/estimate-plan`` expects::

        {"client_name", "categories", "slot_counts", "theme_map",
         "serve_weekends"}

    *metadata* is the ``/editor-metadata`` payload — the slot vocabulary,
    constant slots, theme list, and default theme map.
    """
    inject_card_css()

    all_base_slots = metadata.get("base_slot_names", [])
    const_slots = metadata.get("const_slots", [])
    default_theme_map = metadata.get("default_theme_map", {})
    available_themes = metadata.get("available_themes", [])
    weekday_names = metadata.get("weekday_names") or [
        "monday", "tuesday", "wednesday", "thursday", "friday",
    ]
    all_day_names = metadata.get("all_day_names") or weekday_names

    # Seed the working config once per session so a rerun doesn't reset
    # the operator's edits mid-setup.
    if "est_categories" not in st.session_state:
        st.session_state.est_categories = _default_categories(metadata)
        st.session_state.est_slot_counts = {s: 1 for s in all_base_slots}
        st.session_state.est_theme_map = dict(default_theme_map)

    with st.expander("Client Setup — categories, frequency & day themes",
                     expanded=expanded):
        st.markdown(
            f'<p style="font-size:0.85rem;color:{t.TEXT_2};margin:0 0 1rem;">'
            f'Describe the counter you would serve this prospect. Nothing '
            f'here is saved to the database &mdash; it is used only to '
            f'generate a menu and cost it.</p>',
            unsafe_allow_html=True,
        )

        col_name, col_weekend = st.columns([2.4, 1])
        with col_name:
            client_name = st.text_input(
                "Client name",
                key="est_client_name",
                placeholder="e.g. Acme Corp",
                help="A label for this estimate. It is not looked up in, "
                     "or written to, the client list.",
            ).strip()
        with col_weekend:
            serve_weekends = st.checkbox(
                "Serve weekends",
                key="est_serve_weekends",
                help="When on, Sat/Sun count as service days and get "
                     "their own day themes.",
            )

        categories = render_slot_editor(
            all_base_slots, st.session_state.est_categories, const_slots, _KEY,
        )
        slot_counts = render_multi_slot_editor(
            categories, st.session_state.est_slot_counts, const_slots, _KEY,
        )
        theme_map = render_theme_editor(
            st.session_state.est_theme_map,
            default_theme_map,
            available_themes,
            _KEY,
            days=all_day_names if serve_weekends else weekday_names,
        )

        # Persist the edits so they survive the rerun that Generate causes.
        st.session_state.est_categories = categories
        st.session_state.est_slot_counts = slot_counts
        st.session_state.est_theme_map = theme_map

    generate = st.button(
        "Generate Menu", type="primary", key="est_generate_btn",
        use_container_width=True,
    )
    if not generate:
        return None

    # Validate only on submit — nagging while the operator is still
    # filling the form in would be noise.
    if not client_name:
        st.warning("Enter a client name for this estimate.")
        return None
    if not categories:
        st.warning("Select at least one category to build a menu from.")
        return None

    # Constant slots (white rice, papad, pickle, chutney) are served by
    # every counter and are not offered in the category picker, so add
    # them back before handing the config to the solver.
    return {
        "client_name": client_name,
        "categories": list(categories) + list(const_slots),
        "slot_counts": dict(slot_counts),
        "theme_map": dict(theme_map),
        "serve_weekends": bool(serve_weekends),
    }
