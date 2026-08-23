"""Cost Estimator setup panel — the "new client" mode of the planner.

Sales and ops price a *prospective* client by describing the menu they'd
serve — name, categories, per-category frequency, and day themes — then
generating a plan from it and reading the costing panel. Nothing here is
written to the database: the client doesn't exist yet, and an estimate
that half-created one would leave the client list littered with deals
that never closed.

Categories and day themes reuse the customisation page's editors
(:mod:`customisation.slot_editor`, ``theme_editor``) so a setup entered
here behaves exactly like a stored counter's config. Frequency does not:
see :func:`render_frequency_picker` for why.

Session-state keys are prefixed ``est_``; the reused editors' widget keys
are namespaced by the ``_estimator_`` client key.
"""

from typing import Any, Dict, List, Optional

import streamlit as st

from customisation.slot_editor import render_slot_editor
from customisation.theme_editor import render_theme_editor
from ui.cards import card_header, inject_card_css
from ui.formatters import prettify_slot_name

# Namespace for the reused editor components' widget keys. Distinct from
# any real client name so switching between the editor page and this panel
# can't collide on a widget key.
_KEY = "_estimator_"

# Ceiling on servings per category per day, matching the customisation
# editor's own limit.
_MAX_PER_DAY = 3


def _default_categories(metadata: Dict[str, Any]) -> List[str]:
    """The menu shape a new estimate starts from.

    Prefers the backend's ``default_counter_slots`` — a realistic client
    counter — over ``required_pool_slots``, which is "every slot the
    ontology can always fill". The latter is more courses than any real
    client serves and builds a plate of roughly 1.28 kg before a single
    item is chosen, so a fresh estimate would open on a plate-weight
    error. Operators add the extra courses deliberately.
    """
    const = set(metadata.get("const_slots") or [])
    for key in ("default_counter_slots", "required_pool_slots", "base_slot_names"):
        candidates = metadata.get(key) or []
        if candidates:
            return [s for s in candidates if s not in const]
    return []


def render_frequency_picker(
    categories: List[str],
    current: Dict[str, int],
) -> Dict[str, int]:
    """Ask which categories are served more than once a day.

    The customisation editor renders one number input per category — a
    reasonable way to *audit* a stored config, but here it meant a wall
    of fifteen inputs every one of which read "1". Almost every counter
    doubles up on nothing, and the ones that do double up on one line
    (Rippling's second veg dry, Stripe's second nonveg main).

    So the question is asked the way it actually arises: name the
    exceptions, then set a count for each. The common case renders as a
    single empty picker instead of fifteen controls.
    """
    doubled_default = [
        s for s in categories if int(current.get(s, 1) or 1) > 1
    ]
    doubled = st.multiselect(
        "Served more than once a day",
        options=categories,
        default=doubled_default,
        format_func=prettify_slot_name,
        key=f"est_doubled_{_KEY}",
        help="Most counters serve one of each. Name the exceptions here "
             "— e.g. two veg dry, or two nonveg mains.",
        placeholder="Everything once a day",
    )

    counts = {slot: 1 for slot in categories}
    if doubled:
        cols = st.columns(min(len(doubled), 3))
        for idx, slot in enumerate(doubled):
            with cols[idx % len(cols)]:
                counts[slot] = st.number_input(
                    prettify_slot_name(slot),
                    min_value=2, max_value=_MAX_PER_DAY,
                    value=min(max(int(current.get(slot, 2) or 2), 2), _MAX_PER_DAY),
                    step=1,
                    key=f"est_count_{_KEY}_{slot}",
                )
    return counts


def _setup_summary(
    client_name: str, categories: List[str], counts: Dict[str, int],
    serve_weekends: bool,
) -> str:
    """One-line description of the setup, for the collapsed panel's label.

    A collapsed panel that only says "Client Setup" forces the operator
    to re-open it to remember what the numbers on screen were costed
    from.
    """
    if not client_name:
        return "Client setup — name, categories, frequency & day themes"
    bits = [
        client_name,
        f"{len(categories)} categor{'y' if len(categories) == 1 else 'ies'}",
        "7-day service" if serve_weekends else "Mon–Fri",
    ]
    doubled = [s for s in categories if int(counts.get(s, 1) or 1) > 1]
    if doubled:
        bits.append(
            ", ".join(f"{prettify_slot_name(s)} ×{counts[s]}" for s in doubled)
        )
    return "Client setup — " + "  ·  ".join(bits)


def render_estimator_setup(
    metadata: Dict[str, Any],
    *,
    expanded: bool = True,
    has_plan: bool = False,
) -> Optional[Dict[str, Any]]:
    """Render the setup panel and its submit button.

    Returns the estimator config dict when the button is pressed and the
    setup is valid, otherwise ``None``. The config shape is exactly what
    ``/api/v1/estimate-plan`` expects::

        {"client_name", "categories", "slot_counts", "theme_map",
         "serve_weekends"}

    *metadata* is the ``/editor-metadata`` payload — the slot vocabulary,
    constant slots, theme list, and default theme map. *has_plan* tells
    the panel a menu is already on screen, which demotes its button:
    the primary action is then reading the costing, not generating again.
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
        st.session_state.est_slot_counts = {}
        st.session_state.est_theme_map = dict(default_theme_map)

    # The label is built from session state, before the widgets re-render,
    # so a collapsed panel still says what it holds.
    label = _setup_summary(
        st.session_state.get("est_client_name", "") or "",
        st.session_state.get("est_categories") or [],
        st.session_state.get("est_slot_counts") or {},
        bool(st.session_state.get("est_serve_weekends")),
    )

    with st.expander(label, expanded=expanded):
        # Held to two thirds: a full-width field for a short name
        # strands its help icon at the far edge of the panel.
        col_name, _ = st.columns([2, 1])
        with col_name:
            client_name = st.text_input(
                "Client name",
                key="est_client_name",
                placeholder="e.g. Acme Corp",
                help="A label for this estimate. It is not looked up in, "
                     "or written to, the client list.",
            ).strip()

        categories = render_slot_editor(
            all_base_slots, st.session_state.est_categories, const_slots, _KEY,
        )

        with st.container(border=True):
            card_header(
                "Item Frequency",
                "How many of each category go out per day.",
            )
            slot_counts = render_frequency_picker(
                categories, st.session_state.est_slot_counts,
            )

        # Weekend service decides which days the theme editor shows, so
        # it belongs with the themes rather than up by the name field.
        serve_weekends = st.checkbox(
            "Serve weekends (Sat & Sun get their own themes)",
            key="est_serve_weekends",
        )
        theme_map = render_theme_editor(
            st.session_state.est_theme_map,
            default_theme_map,
            available_themes,
            _KEY,
            days=all_day_names if serve_weekends else weekday_names,
        )

        # Persist the edits so they survive the rerun that submitting causes.
        st.session_state.est_categories = categories
        st.session_state.est_slot_counts = slot_counts
        st.session_state.est_theme_map = theme_map

    # One primary action per screen: once a menu is on screen the primary
    # action is the costing panel, so this demotes itself — to a
    # secondary style, and out of the full-width slot that reads as a
    # call to action.
    if has_plan:
        col_update, _rest = st.columns([1, 2.4])
        with col_update:
            submitted = st.button(
                "Update estimate", type="secondary",
                key="est_generate_btn", use_container_width=True,
                help="Re-run the menu from the setup above.",
            )
    else:
        submitted = st.button(
            "Generate Menu", type="primary",
            key="est_generate_btn", use_container_width=True,
        )
    if not submitted:
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
