"""
Theme Editor -- Customize day-wise menu theme per counter.

Global defaults: Mon=Mix, Tue=Chinese, Wed=Biryani, Thu=South, Fri=North
(plus Sat=South, Sun=North for clients that serve weekends). Each of a
client's counters can override any day.
"""

import streamlit as st
from typing import Dict, List, Optional

from ui import theme as t
from ui.cards import card_header
from ui.formatters import (
    THEME_ICONS,
    THEME_TAG_COLORS,
    THEME_TAG_NEUTRAL,
)

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

_THEME_DISPLAY = {
    'mix': 'Mix (South + North)',
    'chinese': 'Chinese',
    'biryani': 'Biryani',
    'south': 'South Indian',
    'north': 'North Indian',
    'chinese_continental': 'Chinese / Continental',
}


def render_theme_editor(
    current_theme_map: Dict[str, str],
    default_theme_map: Dict[str, str],
    available_themes: List[str],
    client_name: str = "",
    days: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Render theme day editor. Returns updated theme_map dict.

    *days* is the list of days to show — Mon–Fri by default, extended with
    Saturday/Sunday for clients that serve weekends.
    """

    updated = {}

    with st.container(border=True):
        card_header(
            "Day Themes",
            "Override the default cuisine theme for any day on this "
            "counter. Other counters and clients keep their own settings.",
        )

        for day in (days or _WEEKDAYS):
            day_display = day.capitalize()
            current_val = current_theme_map.get(day, default_theme_map.get(day, 'mix'))
            default_val = default_theme_map.get(day, 'mix')

            col_day, col_select, col_tag = st.columns([1.2, 2, 1.5])
            with col_day:
                st.markdown(
                    f'<p style="font-weight:700;color:{t.TEXT};margin:0.5rem 0;'
                    f'font-size:0.85rem;">{day_display}</p>',
                    unsafe_allow_html=True,
                )
            with col_select:
                try:
                    default_idx = available_themes.index(current_val)
                except ValueError:
                    default_idx = 0
                chosen = st.selectbox(
                    f"Theme for {day_display}",
                    available_themes,
                    index=default_idx,
                    format_func=lambda t: _THEME_DISPLAY.get(t, t.title()),
                    key=f"editor_theme_{client_name}_{day}",
                    label_visibility="collapsed",
                )
                updated[day] = chosen

            with col_tag:
                bg, fg = THEME_TAG_COLORS.get(chosen, THEME_TAG_NEUTRAL)
                icon = THEME_ICONS.get(chosen, '')
                is_override = (chosen != default_val)
                border = f' border:1px solid {fg};' if is_override else ''
                label = _THEME_DISPLAY.get(chosen, chosen.title())
                st.markdown(
                    f'<span style="display:inline-flex;align-items:center;gap:4px;'
                    f'margin-top:0.45rem;padding:3px 10px;border-radius:99px;'
                    f'font-size:0.65rem;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.04em;background:{bg};color:{fg};{border}">'
                    f'{icon} {label}{"  *" if is_override else ""}'
                    f'</span>',
                    unsafe_allow_html=True,
                )

        # Loop vars are named out of the way of the ``t`` theme-token
        # alias imported above.
        overrides = {day_key: val for day_key, val in updated.items()
                     if val != default_theme_map.get(day_key)}
        if overrides:
            parts = [f"{day_key.capitalize()}: {_THEME_DISPLAY.get(val, val)}"
                     for day_key, val in overrides.items()]
            st.markdown(
                f'<p style="font-size:0.75rem;color:{t.WARNING_FG};margin:0.5rem 0 0;">'
                f'Overrides: {" | ".join(parts)}</p>',
                unsafe_allow_html=True,
            )

    return updated
