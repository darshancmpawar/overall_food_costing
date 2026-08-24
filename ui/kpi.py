"""KPI cards for the costing panel.

The panel reuses the planner's ``.metrics-grid`` / ``.metric-card`` look
(see ``ui.styles``) so the costing screens read as part of the same app
rather than a second design. What this module adds is **tone**: a card
knows whether it is showing a cost, a revenue, or a profit, and colours
itself accordingly.

The rule the tones follow — colour means something, or it isn't used:

* **money out** (buying price, operating cost) — blue accent, black value
* **money in** (selling price and amount) — purple accent, black value
* **profit** — green accent *and* a green value when it is positive, red
  when it is negative. This is the only place a number itself is
  coloured, because a negative profit is the one thing on these screens
  that must not read like every other figure.
* **derived elsewhere** (a figure the other tab produced) — a blue note,
  so it is clear the number is a link rather than an input
* **neutral** — grey accent, black value. Facts and inputs.

A negative value always carries its minus sign as well as its colour, so
the meaning survives for anyone who can't tell the two apart.
"""

from typing import Iterable, Optional, Tuple

import streamlit as st

from ui import theme as t

# tone -> (accent bar, value colour, note background, note text)
_TONES = {
    "neutral": (t.BORDER_SUBTLE, t.TEXT, t.PAGE_BG, t.TEXT_3),
    "cost": (t.BRAND_BLUE, t.TEXT, t.PAGE_BG, t.TEXT_3),
    "revenue": (t.PURPLE, t.TEXT, t.PURPLE_BG, t.PURPLE_FG),
    "good": (t.SUCCESS, t.SUCCESS_FG, t.SUCCESS_BG, t.SUCCESS_FG),
    "bad": (t.ERROR, t.ERROR_FG, t.ERROR_BG, t.ERROR_FG),
    "info": (t.BRAND_BLUE, t.TEXT, t.BRAND_BLUE_BG, t.BRAND_BLUE_FG),
    "warn": (t.WARNING, t.TEXT, t.WARNING_BG, t.WARNING_FG),
}

KPI_CSS = "<style>" + "".join(
    f"""
    .metrics-grid .metric-card.tone-{tone}::before {{ background: {accent}; }}
    .stApp .metrics-grid .metric-card.tone-{tone} .metric-value {{ color: {value}; }}
    .stApp .metrics-grid .metric-card.tone-{tone} .metric-note {{
        background: {note_bg}; color: {note_fg};
    }}
    """
    for tone, (accent, value, note_bg, note_fg) in _TONES.items()
) + f"""
    .stApp .metrics-grid .metric-note {{
        display: inline-block; margin-top: 0.4rem;
        padding: 2px 8px; border-radius: 99px;
        font-size: 0.68rem; font-weight: 600; line-height: 1.5;
    }}
    /* The panel's cards sit inside tabs, where the planner's bottom
       margin leaves too big a gap before the first section card. */
    .metrics-grid.kpi-band {{ margin-bottom: 0.9rem; }}
    .stApp .metrics-grid .metric-label {{ color: {t.TEXT_3}; }}
</style>"""


def inject_kpi_css() -> None:
    """Inject the tone styles. Cheap and idempotent per rerun."""
    st.markdown(KPI_CSS, unsafe_allow_html=True)


def tone_for_amount(value: float, *, zero: str = "neutral") -> str:
    """``"good"`` above zero, ``"bad"`` below, *zero* at exactly zero.

    For profit figures, where the sign is the whole point.
    """
    if value > 0:
        return "good"
    if value < 0:
        return "bad"
    return zero


def kpi_grid(items: Iterable[Tuple[str, str, Optional[str], str]]) -> None:
    """Render a row of KPI cards.

    Each item is ``(label, value, note, tone)``; *note* may be ``None``.
    The grid auto-fits, so three cards or five both lay out sensibly.
    """
    cards = []
    for label, value, note, tone in items:
        note_html = (
            f'<div class="metric-note">{note}</div>' if note else ""
        )
        cards.append(
            f'<div class="metric-card tone-{tone}">'
            f'<div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div>'
            f"{note_html}"
            f"</div>"
        )
    st.markdown(
        '<div class="metrics-grid kpi-band">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
