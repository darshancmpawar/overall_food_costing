"""Section-card chrome shared by the customisation editor and the
Cost Estimator setup panel.

Both surfaces render the same four editors (client settings, categories,
frequency, day themes) as titled white cards on the light canvas, so the
card CSS and its heading helper live here rather than being duplicated —
or, worse, drifting — between them.

Why a container and not a wrapper div: Streamlit closes the HTML in each
``st.markdown`` block, so an opening ``<div class="section-card">``
followed by widgets never wrapped anything. It just drew an empty box
above them. :func:`card_header` is therefore paired with
``st.container(border=True)``, which draws the real card.
"""

import streamlit as st

from ui import theme as t

SECTION_CARD_CSS = f"""
<style>
    /* Bordered containers are the section cards. */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: {t.CARD_BG};
        border-radius: 14px;
        border-color: {t.BORDER} !important;
        box-shadow: 0 1px 2px rgba(19,19,19,0.06);
    }}
    .stApp p.section-title {{
        font-size: 1.125rem; font-weight: 700; color: {t.TEXT};
        margin: 0 0 0.15rem; letter-spacing: -0.2px;
    }}
    .stApp p.section-desc {{
        font-size: 0.8rem; color: {t.TEXT_3}; margin: 0 0 0.9rem;
    }}
    .status-pill {{
        display: inline-block; padding: 2px 8px;
        border-radius: 99px; font-size: 0.7rem; font-weight: 600;
    }}
    .status-pill.match {{ background: {t.SUCCESS_BG}; color: {t.SUCCESS_FG}; }}
    .status-pill.new   {{ background: {t.BRAND_YELLOW_BG}; color: {t.BRAND_YELLOW_FG}; }}
    .status-pill.warn  {{ background: {t.WARNING_BG}; color: {t.WARNING_FG}; }}
    /* "this value is computed, not typed" — informational, not a success. */
    .status-pill.info  {{ background: {t.BRAND_BLUE_BG}; color: {t.BRAND_BLUE_FG}; }}
    .changes-indicator {{
        display: inline-flex; align-items: center; gap: 0.35rem;
        padding: 0.3rem 0.75rem; background: {t.WARNING_BG};
        border: 1px solid {t.WARNING}; border-radius: 99px;
        font-size: 0.78rem; color: {t.WARNING_FG}; font-weight: 500;
        margin-bottom: 0.75rem;
    }}
</style>
"""


def inject_card_css() -> None:
    """Inject the section-card styles. Cheap and idempotent per rerun."""
    st.markdown(SECTION_CARD_CSS, unsafe_allow_html=True)


def card_header(title: str, desc: str) -> None:
    """Render a section card's title and one-line description.

    Call as the first thing inside ``with st.container(border=True):``.
    """
    st.markdown(
        f'<p class="section-title">{title}</p>'
        f'<p class="section-desc">{desc}</p>',
        unsafe_allow_html=True,
    )
