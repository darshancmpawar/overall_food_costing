"""
Customisation Editor -- Main page that orchestrates all editor sections.

Two flows:
  Select Existing: select client + counter -> edit settings/categories/
                   frequency/themes -> Save | Reset | Delete
  Create New:      enter name -> pick categories/frequency/themes ->
                   Create Client | Reset Setup

A client has one or more *counters* (serving lines), each with its own
category list, per-slot counts, and day themes. The editor works on one
counter at a time and can add or remove them.

Called from app.py when st.session_state.view == "editor".
"""

import streamlit as st

from ui import theme as t
from ui.api_client import MenuApiClient
from ui.cards import card_header, inject_card_css
from customisation.slot_editor import render_slot_editor
from customisation.multi_slot_editor import render_multi_slot_editor
from customisation.theme_editor import render_theme_editor

_NEW_COUNTER_SENTINEL = "+ Add new counter"

def inject_editor_css() -> None:
    """Inject the editor page's chrome: the shared section-card styles
    plus the page-header styles only this page uses."""
    inject_card_css()
    st.markdown(f"""
    <style>
        .editor-header {{
            display: flex; align-items: center; gap: 1rem;
            margin-bottom: 1.75rem;
        }}
        .stApp p.editor-title {{
            font-size: 1.5rem; font-weight: 600; color: {t.TEXT};
            letter-spacing: -0.3px; margin: 0; line-height: 1.2;
        }}
        .stApp p.editor-subtitle {{
            font-size: 0.875rem; color: {t.TEXT_3}; margin: 0.15rem 0 0;
            font-weight: 400;
        }}
    </style>
    """, unsafe_allow_html=True)


def _render_client_settings(current: dict, client_key: str) -> dict:
    """Render the client-level settings card. Returns the edited values.

    These live on the client row rather than a counter: every serving line
    shares the same city, weekend calendar, cooldown window, and item
    source pools.
    """
    with st.container(border=True):
        card_header(
            "Client Settings",
            "Shared by every counter for this client",
        )
        col_city, col_cooldown, col_weekend = st.columns([2, 1.4, 1.4])
        with col_city:
            city = st.text_input(
                "City", value=current.get('city', ''),
                key=f"editor_city_{client_key}",
                placeholder="e.g. Bangalore",
            ).strip()
        with col_cooldown:
            cooldown = st.number_input(
                "Item cooldown (days)",
                min_value=0, max_value=120,
                value=int(current.get('item_cooldown_days') or 20),
                step=1,
                key=f"editor_cooldown_{client_key}",
                help="An item served within this many days can't repeat.",
            )
        with col_weekend:
            serve_weekends = st.checkbox(
                "Serve weekends",
                value=bool(current.get('serve_weekends')),
                key=f"editor_weekends_{client_key}",
                help="When on, Sat/Sun count as service days and get their "
                     "own day themes.",
            )
        pools_raw = st.text_input(
            "Source pools (comma-separated)",
            value=", ".join(current.get('source_pools') or []),
            key=f"editor_pools_{client_key}",
            help="Extra item collections this client may draw from, on top "
                 "of the shared ontology. Leave empty for shared items only.",
        )

    return {
        'city': city,
        'item_cooldown_days': int(cooldown),
        'serve_weekends': bool(serve_weekends),
        'source_pools': [
            p.strip() for p in pools_raw.split(',') if p.strip()
        ],
    }


def render_customisation_editor(api: MenuApiClient):
    """Main entry point for the customisation editor view."""
    inject_editor_css()

    # --- Top bar ---
    col_back, col_title = st.columns([1, 5])
    with col_back:
        if st.button("< Back to Menu", key="editor_back_btn", use_container_width=True):
            st.session_state.view = "planner"
            st.rerun()
    with col_title:
        st.markdown(
            '<div><p class="editor-title">Customisation Editor</p>'
            '<p class="editor-subtitle">Create or edit clients, categories, frequency, and day themes</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # --- Show success message ---
    if st.session_state.get('editor_success_msg'):
        st.success(st.session_state.pop('editor_success_msg'))

    # --- Load metadata ---
    try:
        metadata = api.get_editor_metadata()
    except Exception as e:
        st.error(f"Failed to load editor data: {e}")
        return

    clients = metadata.get('clients', [])
    all_base_slots = metadata.get('base_slot_names', [])
    const_slots = metadata.get('const_slots', [])
    default_theme_map = metadata.get('default_theme_map', {})
    available_themes = metadata.get('available_themes', [])
    weekday_names = metadata.get('weekday_names') or [
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
    ]
    all_day_names = metadata.get('all_day_names') or weekday_names

    # ============================================================
    # Section 1: Client Management
    # ============================================================
    st.markdown(
        '<div class="section-card">'
        '<p class="section-title">Client</p>'
        '<p class="section-desc">Select an existing client or create a new one</p>',
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Mode",
        ["Select Existing", "Create New"],
        horizontal=True,
        key="editor_mode",
        label_visibility="collapsed",
    )
    is_create_mode = (mode == "Create New")

    selected_client = None
    new_client_name = ""

    if not is_create_mode:
        if not clients:
            st.info("No clients found. Switch to **Create New** to add one.")
            st.markdown('</div>', unsafe_allow_html=True)
            return
        selected_client = st.selectbox(
            "Client", clients,
            key="editor_client_select",
            label_visibility="collapsed",
        )
    else:
        new_client_name = st.text_input(
            "Client Name", key="editor_new_client_name",
            placeholder="e.g. Acme Corp",
        )

    st.markdown('</div>', unsafe_allow_html=True)

    # For Select Existing: load config from DB
    # For Create New: use defaults
    selected_counter = None
    is_new_counter = False
    if not is_create_mode:
        try:
            config = api.get_client_config(selected_client)
        except Exception as e:
            st.error(f"Failed to load config for {selected_client}: {e}")
            return

        counters = config.get('counters') or []
        counter_names = [c.get('name', '') for c in counters]

        # --- Counter picker ---
        st.markdown(
            '<div class="section-card">'
            '<p class="section-title">Counter</p>'
            '<p class="section-desc">Each counter is a separate serving line '
            'with its own categories, frequency, and day themes</p>',
            unsafe_allow_html=True,
        )
        counter_choice = st.selectbox(
            "Counter",
            counter_names + [_NEW_COUNTER_SENTINEL],
            key=f"editor_counter_select_{selected_client}",
            label_visibility="collapsed",
        )
        is_new_counter = (counter_choice == _NEW_COUNTER_SENTINEL)
        if is_new_counter:
            selected_counter = st.text_input(
                "New counter name",
                key=f"editor_new_counter_name_{selected_client}",
                placeholder="e.g. South Indian",
            ).strip()
        else:
            selected_counter = counter_choice
        st.markdown('</div>', unsafe_allow_html=True)

        if is_new_counter and not selected_counter:
            st.info("Enter a name for the new counter to start configuring it.")
            return

        counter_cfg = next(
            (c for c in counters if c.get('name') == selected_counter), {},
        )
        if is_new_counter:
            current_active = [
                s for s in all_base_slots if s not in set(const_slots)
            ]
            current_counts = {s: 1 for s in all_base_slots}
            current_theme = dict(default_theme_map)
        else:
            current_active = counter_cfg.get('active_base_slots', [])
            current_counts = counter_cfg.get('slot_counts', {})
            current_theme = counter_cfg.get(
                'theme_map', dict(default_theme_map),
            )
        # Optimistic-concurrency counter returned by GET /client-config.
        # Every PUT that modifies this client must send it back so two
        # admins editing at once can't last-write-wins silently.
        current_version = config.get('version')
        current_settings = {
            'city': config.get('city', ''),
            'serve_weekends': bool(config.get('serve_weekends')),
            'item_cooldown_days': config.get('item_cooldown_days', 20),
            'source_pools': config.get('source_pools') or [],
        }
        client_key = f"{selected_client}::{selected_counter}"
    else:
        if not new_client_name.strip():
            st.markdown(
                f'<div style="text-align:center;padding:2rem;color:{t.TEXT_3};">'
                'Enter a client name above to start configuring.</div>',
                unsafe_allow_html=True,
            )
            return
        counters = []
        counter_names = []
        current_active = [s for s in all_base_slots if s not in set(const_slots)]
        current_counts = {s: 1 for s in all_base_slots}
        current_theme = dict(default_theme_map)
        current_version = None  # no row yet; set after api.create_client
        current_settings = {
            'city': '',
            'serve_weekends': False,
            'item_cooldown_days': 20,
            'source_pools': [],
        }
        client_key = "_new_"

    # ============================================================
    # Section 2: Client settings (shared by every counter)
    # ============================================================
    new_settings = _render_client_settings(current_settings, client_key)
    theme_days = (
        all_day_names if new_settings['serve_weekends'] else weekday_names
    )

    # ============================================================
    # Section 3: Customize Categories
    # ============================================================
    new_active_slots = render_slot_editor(
        all_base_slots, current_active, const_slots, client_key,
    )

    # ============================================================
    # Section 4: Item Frequency
    # ============================================================
    new_slot_counts = render_multi_slot_editor(
        new_active_slots, current_counts, const_slots, client_key,
    )

    # ============================================================
    # Section 5: Day-wise Theme Override
    # ============================================================
    new_theme_map = render_theme_editor(
        current_theme, default_theme_map, available_themes, client_key,
        days=theme_days,
    )

    # ============================================================
    # Action bar
    # ============================================================
    st.markdown("")

    # Unsaved changes indicator
    if not is_create_mode:
        changes = []
        if is_new_counter:
            changes.append(f"new counter '{selected_counter}'")
        if set(new_active_slots) != set(current_active):
            changes.append("categories")
        count_changes = {k: v for k, v in new_slot_counts.items()
                         if v != current_counts.get(k, 1) and k in new_active_slots}
        if count_changes:
            changes.append("frequency")
        theme_changes = {k: v for k, v in new_theme_map.items()
                         if v != current_theme.get(k)}
        if theme_changes:
            changes.append("themes")
        if new_settings != current_settings:
            changes.append("settings")
        if changes:
            st.markdown(
                f'<div class="changes-indicator">&#9679; Unsaved: {", ".join(changes)}</div>',
                unsafe_allow_html=True,
            )

    if is_create_mode:
        col_create, col_reset = st.columns(2)

        with col_create:
            create_clicked = st.button(
                "Create Client", type="primary",
                key="editor_create_btn", use_container_width=True,
            )

        with col_reset:
            reset_clicked = st.button(
                "Reset Setup",
                key="editor_reset_new", use_container_width=True,
            )

        if create_clicked:
            name = new_client_name.strip()
            if not name:
                st.error("Enter a client name.")
            elif name in clients:
                st.error(f"Client '{name}' already exists.")
            elif not new_active_slots:
                st.error("Select at least one category.")
            else:
                try:
                    # One round-trip: the create endpoint takes the
                    # starting counter's shape and the client settings, so
                    # there's no create-then-patch dance any more.
                    api.create_client(
                        name, new_active_slots,
                        slot_counts={
                            k: v for k, v in new_slot_counts.items()
                            if k in new_active_slots
                        },
                        theme_map=new_theme_map,
                        settings=new_settings,
                    )
                    # Invalidate the planner sidebar's cached client list
                    # so the new client shows up immediately rather than
                    # 60s later when the TTL expires.
                    st.cache_data.clear()
                    st.session_state['editor_success_msg'] = f"Client '{name}' created successfully!"
                    st.session_state.pop('editor_new_client_name', None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")

        if reset_clicked:
            for key in list(st.session_state.keys()):
                if '_new_' in key or key == 'editor_new_client_name':
                    st.session_state.pop(key, None)
            st.rerun()

    else:
        col_save, col_reset, col_del_counter, col_delete = st.columns(4)

        with col_save:
            save_clicked = st.button(
                "Save Counter" if is_new_counter else "Save", type="primary",
                key="editor_save_all", use_container_width=True,
            )

        with col_reset:
            reset_clicked = st.button(
                "Reset to Defaults",
                key="editor_reset_all", use_container_width=True,
                disabled=is_new_counter,
            )

        with col_del_counter:
            # Deleting the only counter would leave the client unplannable,
            # so that path is closed off here as well as server-side.
            delete_counter_clicked = st.button(
                "Delete Counter",
                key="editor_delete_counter_btn", use_container_width=True,
                disabled=is_new_counter or len(counter_names) <= 1,
                help=(
                    "A client must keep at least one counter."
                    if len(counter_names) <= 1 else
                    f"Remove the '{selected_counter}' serving line."
                ),
            )

        with col_delete:
            delete_clicked = st.button(
                "Delete Client",
                key="editor_delete_btn", use_container_width=True,
            )

        if delete_clicked:
            try:
                api.delete_client(selected_client)
                # Invalidate cached client list so the deleted client
                # disappears from the picker immediately.
                st.cache_data.clear()
                st.session_state['editor_success_msg'] = f"Client '{selected_client}' deleted."
                st.rerun()
            except Exception as e:
                st.error(f"Delete failed: {e}")

        if delete_counter_clicked:
            try:
                api.update_client_config(selected_client, {
                    'version': current_version,
                    'delete_counter': selected_counter,
                })
                st.cache_data.clear()
                st.session_state['editor_success_msg'] = (
                    f"Counter '{selected_counter}' removed from "
                    f"{selected_client}."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Delete counter failed: {e}")

        if save_clicked:
            if not new_active_slots:
                st.error("Select at least one category.")
            else:
                payload = {
                    'version': current_version,
                    'counter': selected_counter,
                    'active_base_slots': new_active_slots,
                    'slot_counts': {
                        k: v for k, v in new_slot_counts.items()
                        if k in new_active_slots
                    },
                    'theme_map': new_theme_map,
                    **new_settings,
                }
                if is_new_counter:
                    payload['create_counter'] = True
                try:
                    api.update_client_config(selected_client, payload)
                    # Counter list / weekend flag may have moved, and the
                    # planner sidebar caches both.
                    st.cache_data.clear()
                    st.session_state['editor_success_msg'] = (
                        f"Configuration saved for {selected_client} "
                        f"({selected_counter})"
                    )
                    st.rerun()
                except Exception as e:
                    # 409 surfaces here as an HTTPError with "modified by
                    # another request" in the message — tell the user to
                    # refresh rather than hide the conflict.
                    st.error(f"Save failed: {e}")

        if reset_clicked:
            payload = {
                'version': current_version,
                'counter': selected_counter,
                'active_base_slots': list(all_base_slots),
                'slot_counts': {s: 1 for s in all_base_slots},
                'theme_map': dict(default_theme_map),
            }
            try:
                api.update_client_config(selected_client, payload)
                st.session_state['editor_success_msg'] = (
                    f"Reset {selected_client} ({selected_counter}) to defaults"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")
