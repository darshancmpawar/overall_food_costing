"""App-wide CSS styles for the Streamlit frontend.

Design language — **Pulse / OP Lens**: the shared visual system across
every Pulse module. Light grey canvas, white content cards, generous
white space, Figtree at every size, brand yellow for the one primary
action on a screen, brand blue for links / information / selection, and
a status palette where green, orange and red always mean the same thing.

Colour values mirror :mod:`ui.theme` — that module is the source of
truth, this file projects it into ``:root`` custom properties so the
stylesheet and the inline-HTML builders can't drift apart. Editing the
palette is a one-stop change in ``ui/theme.py``.
"""

from ui import theme as t

STYLES = f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Figtree:wght@300;400;500;600;700;800&family=Inter:wght@400;500;600&display=swap');

    /* ================================================================
       DESIGN TOKENS  —  Pulse / OP Lens light theme
       ================================================================ */
    :root {{
        --page:          {t.PAGE_BG};      /* main canvas                 */
        --surface:       {t.CARD_BG};      /* cards / panels / modals     */
        --surface-2:     {t.ROW_ALT_BG};   /* alternate rows, sunk areas  */
        --surface-3:     {t.DISABLED_BG};  /* disabled areas              */
        --ink:           {t.BORDER_ACTIVE};/* dark bars: table head, nav  */

        --border:        {t.BORDER};
        --border-subtle: {t.BORDER_SUBTLE};
        --border-active: {t.BORDER_ACTIVE};

        --text:          {t.TEXT};         /* headings, body              */
        --text-2:        {t.TEXT_2};       /* supporting descriptions     */
        --text-3:        {t.TEXT_3};       /* hints, metadata             */
        --text-disabled: {t.TEXT_DISABLED};
        --text-invert:   {t.TEXT_ON_DARK};

        --yellow:        {t.BRAND_YELLOW};       /* primary action       */
        --yellow-hover:  {t.BRAND_YELLOW_HOVER};
        --yellow-bg:     {t.BRAND_YELLOW_BG};
        --yellow-fg:     {t.BRAND_YELLOW_FG};

        --blue:          {t.BRAND_BLUE};         /* links / information  */
        --blue-hover:    {t.BRAND_BLUE_HOVER};
        --blue-bg:       {t.BRAND_BLUE_BG};
        --blue-fg:       {t.BRAND_BLUE_FG};

        --purple:        {t.PURPLE};             /* special emphasis     */
        --purple-bg:     {t.PURPLE_BG};
        --purple-fg:     {t.PURPLE_FG};

        --nav-deep:      {t.NAV_DEEP};
        --nav-mid:       {t.NAV_MID};

        --success:       {t.SUCCESS};
        --success-bg:    {t.SUCCESS_BG};
        --success-fg:    {t.SUCCESS_FG};
        --warning:       {t.WARNING};
        --warning-bg:    {t.WARNING_BG};
        --warning-fg:    {t.WARNING_FG};
        --error:         {t.ERROR};
        --error-bg:      {t.ERROR_BG};
        --error-fg:      {t.ERROR_FG};

        --font-body: {t.FONT_FAMILY};
        --font-num: 'Inter', {t.FONT_FAMILY};

        --radius-sm: 6px;
        --radius-md: 10px;
        --radius-lg: 14px;
        --radius-xl: 20px;
        --shadow-sm: 0 1px 2px rgba(19,19,19,0.06);
        --shadow-md: 0 2px 8px rgba(19,19,19,0.08);
        --shadow-lg: 0 12px 32px rgba(19,19,19,0.16);
        --transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
    }}

    /* ================================================================
       GLOBAL
       ================================================================ */
    .stApp {{
        background: var(--page);
        color: var(--text);
        font-family: var(--font-body);
        -webkit-font-smoothing: antialiased;
    }}
    .block-container {{
        padding: 3.4rem 2rem 2rem;
        max-width: 1400px;
    }}
    /* 16px Regular body copy is the baseline of the type scale. */
    html, body, .stApp, [data-testid="stMarkdownContainer"] {{
        font-size: 16px;
    }}
    /* Streamlit ships its own font on generated `.st-emotion-cache-*`
       classes, whose `.class p` selectors out-specify a bare element
       rule — so Figtree has to be asserted with !important or the whole
       app silently falls back to Source Sans. */
    html, body, .stApp, [class*="st-emotion-cache"],
    button, input, textarea, select, table, th, td {{
        font-family: var(--font-body) !important;
    }}
    [data-testid="stMarkdownContainer"] p {{
        color: var(--text-2);
        font-weight: 400;
    }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ color: var(--blue-hover); text-decoration: underline; }}

    /* Numerals line up like a ledger wherever money or counts appear */
    .metric-value, .cost-value, .qty-value, .cost-pill, .qty-pill,
    .stNumberInput input,
    [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{
        font-family: var(--font-num) !important;
        font-feature-settings: "tnum" 1, "zero" 1;
    }}

    ::-webkit-scrollbar {{ width: 11px; height: 11px; }}
    ::-webkit-scrollbar-track {{ background: var(--page); }}
    ::-webkit-scrollbar-thumb {{
        background: var(--border-subtle); border-radius: 99px;
        border: 3px solid var(--page);
    }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--text-3); }}

    /* Keyboard focus — brand blue ring (interaction, not action) */
    *:focus-visible {{
        outline: 2px solid var(--blue) !important;
        outline-offset: 2px !important;
        border-radius: var(--radius-sm);
    }}

    /* ================================================================
       STREAMLIT HEADER / TOOLBAR
       ================================================================ */
    header[data-testid="stHeader"] {{
        background: rgba(255,255,255,0.88) !important;
        backdrop-filter: blur(8px);
        border-bottom: 1px solid var(--border) !important;
    }}
    [data-testid="stToolbar"] button,
    [data-testid="stToolbar"] a {{ color: var(--text-2) !important; }}
    [data-testid="stToolbar"] button:hover,
    [data-testid="stToolbar"] a:hover {{ color: var(--text) !important; }}
    [data-testid="collapsedControl"] button,
    [data-testid="stSidebarCollapsedControl"] button {{ color: var(--text-2) !important; }}
    [data-testid="collapsedControl"] button:hover,
    [data-testid="stSidebarCollapsedControl"] button:hover {{ color: var(--text) !important; }}
    footer, .stDeployButton,
    [data-testid="stDecoration"] {{ display: none !important; }}
    ._profileContainer_gzau3_53,
    [data-testid="manage-app-button"] {{ display: none !important; }}

    /* ================================================================
       SIDEBAR  —  deep blue navigation panel
       ================================================================ */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, var(--nav-deep) 0%, var(--nav-mid) 100%) !important;
        border-right: none !important;
    }}
    [data-testid="stSidebar"][aria-expanded="true"] {{
        min-width: 300px !important; max-width: 300px !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{ padding-top: 4rem !important; }}
    [data-testid="stSidebar"] label {{
        color: rgba(255,255,255,0.72) !important;
        font-size: 0.75rem !important; font-weight: 600 !important;
        letter-spacing: 0.03em; text-transform: uppercase;
    }}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
        color: rgba(255,255,255,0.66) !important;
    }}
    /* Radio / checkbox labels inside the nav panel stay white */
    [data-testid="stSidebar"] .stRadio label p,
    [data-testid="stSidebar"] .stCheckbox label p {{
        color: rgba(255,255,255,0.92) !important;
        text-transform: none; letter-spacing: 0;
        font-size: 0.88rem !important; font-weight: 500 !important;
    }}
    [data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.16) !important; }}
    /* Inputs on the dark panel keep a white field so text stays readable */
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-baseweb="input"],
    [data-testid="stSidebar"] [data-baseweb="base-input"] {{
        background-color: var(--surface) !important;
        border-color: rgba(255,255,255,0.24) !important;
    }}

    .sidebar-brand {{
        padding: 0.25rem 0 1.3rem;
        border-bottom: 1px solid rgba(255,255,255,0.16);
        margin-bottom: 1.3rem;
    }}
    .sidebar-brand-row {{ display: flex; align-items: center; gap: 0.7rem; }}
    .sidebar-brand-icon {{
        width: 40px; height: 40px; border-radius: var(--radius-md);
        background: var(--yellow);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.2rem; flex-shrink: 0;
    }}
    .stApp .sidebar-brand h2 {{
        margin: 0; font-size: 1.25rem; color: var(--text-invert);
        font-weight: 700; letter-spacing: -0.2px; line-height: 1.15;
    }}
    .stApp .sidebar-brand p {{
        margin: 2px 0 0; font-size: 0.7rem; color: rgba(255,255,255,0.62);
        font-weight: 500; letter-spacing: 0.07em; text-transform: uppercase;
    }}

    /* Mode switch block at the top of the nav panel */
    .stApp p.mode-switch-label {{
        font-size: 0.7rem; font-weight: 700; letter-spacing: 0.07em;
        text-transform: uppercase; color: rgba(255,255,255,0.62);
        margin: 0 0 0.35rem;
    }}
    .mode-note {{
        font-size: 0.72rem; line-height: 1.5;
        color: rgba(255,255,255,0.66);
        background: rgba(255,255,255,0.08);
        border-left: 3px solid var(--yellow);
        border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
        padding: 0.5rem 0.7rem; margin: 0.15rem 0 0.9rem;
    }}

    .user-chip {{
        display: flex; align-items: center; gap: 0.6rem;
        padding: 0.6rem 0.7rem; background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.16); border-radius: var(--radius-md);
        margin-bottom: 0.75rem;
    }}
    .user-avatar {{
        width: 32px; height: 32px; border-radius: 50%;
        background: var(--yellow);
        display: flex; align-items: center; justify-content: center;
        font-size: 0.74rem; font-weight: 700; color: var(--text); flex-shrink: 0;
    }}
    .user-chip-info {{ flex: 1; min-width: 0; }}
    .user-chip-name {{
        font-size: 0.85rem; font-weight: 600; color: var(--text-invert);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .user-chip-role {{
        font-size: 0.66rem; color: rgba(255,255,255,0.62);
        text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
    }}

    /* ================================================================
       PAGE HEADER  —  24px page title
       ================================================================ */
    .stApp p.page-title {{
        font-size: 1.5rem; font-weight: 600; color: var(--text);
        margin: 0; letter-spacing: -0.3px; line-height: 1.2;
    }}
    .stApp p.page-subtitle {{
        font-size: 0.875rem; color: var(--text-3); margin: 0.3rem 0 0;
        font-weight: 400;
    }}
    .plan-source-badge {{ font-family: var(--font-body); }}

    /* ================================================================
       METRIC CARDS  (custom .metric-card grid)
       ================================================================ */
    .metrics-grid {{
        display: grid;
        /* auto-fit rather than a fixed 4 so the Counter card added for
           multi-line clients wraps instead of squeezing the row. */
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 0.8rem; margin-bottom: 1.6rem;
    }}
    .metric-card {{
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-lg); padding: 1rem 1.15rem;
        position: relative; overflow: hidden; transition: var(--transition);
        box-shadow: var(--shadow-sm);
    }}
    .metric-card:hover {{
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }}
    .metric-card::before {{
        content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
    }}
    .metric-card:nth-child(1)::before {{ background: var(--yellow); }}
    .metric-card:nth-child(2)::before {{ background: var(--blue); }}
    .metric-card:nth-child(3)::before {{ background: var(--success); }}
    .metric-card:nth-child(4)::before {{ background: var(--purple); }}
    .metric-card:nth-child(5)::before {{ background: var(--warning); }}
    .metric-label {{
        font-size: 0.7rem; color: var(--text-3);
        text-transform: uppercase; letter-spacing: 0.06em;
        font-weight: 600; margin-bottom: 0.35rem;
    }}
    .metric-value {{
        font-size: 1.35rem; font-weight: 700; color: var(--text);
        letter-spacing: -0.3px; line-height: 1.15;
    }}

    /* ================================================================
       MENU TABLE  —  the hero.  Dark header, alternating rows.
       ================================================================ */
    .menu-table-wrap {{
        border: 1px solid var(--border); border-radius: var(--radius-lg);
        overflow: hidden; box-shadow: var(--shadow-sm); background: var(--surface);
    }}
    .menu-table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
    .menu-table thead th {{
        background: var(--ink); color: var(--text-invert);
        padding: 0.8rem 0.85rem; text-align: center; font-weight: 600;
        font-size: 0.8rem;
        border-right: 1px solid rgba(255,255,255,0.12);
    }}
    .menu-table thead th:first-child {{
        text-align: left; min-width: 130px;
    }}
    .menu-table thead th:last-child {{ border-right: none; }}
    .day-label {{
        display: block; color: var(--text-invert); font-weight: 700;
        font-size: 0.82rem; margin-bottom: 5px;
    }}
    .theme-tag {{
        display: inline-flex; align-items: center; gap: 4px;
        padding: 2px 9px; border-radius: 99px;
        font-size: 0.62rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.6;
    }}
    .menu-table tbody td {{
        padding: 0.75rem 0.9rem;
        border-bottom: 1px solid var(--border);
        border-right: 1px solid var(--border);
        color: var(--text-2); background: var(--surface);
        vertical-align: top; transition: background 0.15s ease;
    }}
    /* Alternating rows for scannability */
    .menu-table tbody tr:nth-child(even) td {{ background: var(--surface-2); }}
    .menu-table tbody td:first-child {{
        font-weight: 600; color: var(--text-2);
        font-size: 0.75rem; white-space: nowrap; min-width: 130px;
        text-transform: uppercase; letter-spacing: 0.04em; vertical-align: middle;
    }}
    .menu-table tbody td:last-child {{ border-right: none; }}
    .menu-table tbody tr:last-child td {{ border-bottom: none; }}
    /* Hover highlights the row in brand blue, like a selected grid row */
    .menu-table tbody tr:hover td {{ background: var(--blue-bg); }}

    .item-name {{
        color: var(--text); font-weight: 600; font-size: 0.875rem;
        line-height: 1.35;
    }}
    .color-pill {{
        display: inline-block; margin-left: 5px; padding: 1px 7px;
        border-radius: 99px; font-size: 0.62rem; font-weight: 700;
    }}
    .cell-empty {{ color: var(--text-disabled); font-size: 0.875rem; }}

    /* Cost & quantity pills (second line of a cell) */
    .item-cost-row {{ display: flex; align-items: center; gap: 6px; margin-top: 7px; }}
    .qty-pill {{
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: var(--radius-sm);
        font-size: 0.66rem; font-weight: 600; letter-spacing: 0.01em;
        background: var(--surface-3); color: var(--text-2);
    }}
    .cost-pill {{
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: var(--radius-sm);
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.01em;
        background: var(--yellow-bg); color: var(--yellow-fg);
    }}

    /* Plate-cost / qty footer rows */
    .menu-table tbody .cost-footer-row td,
    .menu-table tbody tr:nth-child(even).cost-footer-row td {{
        background: var(--blue-bg) !important;
        vertical-align: middle !important;
        padding: 0.8rem 0.9rem !important;
    }}
    .menu-table tbody .cost-footer-row.cost-footer-first td {{
        border-top: 2px solid var(--blue) !important;
    }}
    .cost-footer-label {{
        font-size: 0.72rem !important; font-weight: 700 !important;
        color: var(--text) !important;
        text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap;
    }}
    .cost-footer-value {{
        text-align: center; font-weight: 700 !important; font-size: 0.95rem !important;
    }}
    .cost-footer-row .cost-value {{ color: var(--success-fg) !important; }}
    .cost-footer-row .qty-value  {{ color: var(--text-2) !important; }}

    /* ================================================================
       POOL WARNINGS / EMPTY STATE / CHANGES LOG
       ================================================================ */
    .pool-warn-bar {{
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.65rem 1rem; margin-bottom: 0.6rem;
        background: var(--warning-bg);
        border: 1px solid var(--warning);
        border-radius: var(--radius-md); font-size: 0.85rem;
        color: var(--warning-fg);
    }}

    .empty-state {{
        text-align: center; padding: 4rem 2rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-xl); margin: 2.5rem auto; max-width: 520px;
        box-shadow: var(--shadow-sm);
    }}
    .empty-icon {{
        width: 64px; height: 64px; margin: 0 auto 1.1rem; border-radius: 50%;
        background: var(--yellow-bg);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.6rem;
    }}
    .empty-state h3 {{
        color: var(--text); margin: 0 0 0.45rem;
        font-size: 1.25rem; font-weight: 700;
    }}
    .empty-state p {{
        color: var(--text-3); font-size: 0.875rem; margin: 0; line-height: 1.6;
    }}

    .log-entry {{
        padding: 0.5rem 0.85rem; background: var(--surface);
        border: 1px solid var(--border);
        border-left: 3px solid var(--blue);
        border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
        margin-bottom: 0.35rem; font-size: 0.82rem; color: var(--text-2);
        animation: fadeInUp 0.18s ease-out;
    }}
    .log-entry.log-diff {{ display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }}
    .log-day {{
        color: var(--text); font-weight: 700;
        font-size: 0.76rem; letter-spacing: 0.02em;
    }}
    .log-slot {{
        color: var(--text-3); font-weight: 600;
        font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .log-sep {{ color: var(--text-disabled); font-size: 0.74rem; }}
    .log-old {{
        color: var(--text-3); text-decoration: line-through;
        text-decoration-color: var(--error); font-size: 0.82rem;
    }}
    .log-arrow {{ color: var(--blue); font-weight: 700; padding: 0 2px; }}
    .log-new {{ color: var(--success-fg); font-weight: 600; font-size: 0.84rem; }}
    .regen-day-header {{
        font-weight: 700; font-size: 0.85rem; color: var(--text);
        margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.4rem;
    }}

    @keyframes fadeInUp {{
        from {{ opacity: 0; transform: translateY(3px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .menu-table-wrap, .metrics-grid {{ animation: fadeInUp 0.24s ease-out; }}

    /* ================================================================
       STREAMLIT COMPONENTS
       ================================================================ */

    /* --- BUTTONS  (16px Semibold labels) --- */
    .stButton > button,
    .stFormSubmitButton > button,
    .stDownloadButton > button,
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-minimal"] {{
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        letter-spacing: 0.005em;
        transition: var(--transition) !important;
    }}
    /* Primary — brand yellow with dark text. One per screen. */
    .stButton > button[kind="primary"],
    .stFormSubmitButton > button,
    button[data-testid="baseButton-primary"] {{
        background: var(--yellow) !important;
        border: 1px solid var(--yellow) !important;
        color: var(--text) !important;
        box-shadow: var(--shadow-sm) !important;
    }}
    .stButton > button[kind="primary"]:hover,
    .stFormSubmitButton > button:hover,
    button[data-testid="baseButton-primary"]:hover {{
        background: var(--yellow-hover) !important;
        border-color: var(--yellow-hover) !important;
        box-shadow: var(--shadow-md) !important;
    }}
    /* The label is a nested <p> inside the button; without this it
       inherits the surrounding text colour — white in the sidebar —
       and the yellow button reads as blank. */
    .stButton > button[kind="primary"] *,
    .stFormSubmitButton > button *,
    button[data-testid="baseButton-primary"] * {{
        color: var(--text) !important;
    }}
    /* Secondary — outline on white */
    .stButton > button:not([kind="primary"]),
    .stDownloadButton > button,
    button[data-testid="baseButton-secondary"] {{
        background: var(--surface) !important;
        color: var(--text) !important;
        border: 1px solid var(--border-subtle) !important;
    }}
    .stButton > button:not([kind="primary"]):hover,
    .stDownloadButton > button:hover,
    button[data-testid="baseButton-secondary"]:hover {{
        background: var(--blue-bg) !important;
        color: var(--blue-hover) !important;
        border-color: var(--blue) !important;
    }}
    /* Buttons on the dark nav panel */
    [data-testid="stSidebar"] .stButton > button:not([kind="primary"]),
    [data-testid="stSidebar"] .stButton > button:not([kind="primary"]) * {{
        background-color: transparent;
        color: var(--text-invert) !important;
    }}
    [data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {{
        background: rgba(255,255,255,0.10) !important;
        border-color: rgba(255,255,255,0.28) !important;
    }}
    [data-testid="stSidebar"] .stButton > button:not([kind="primary"]):hover {{
        background: rgba(255,255,255,0.18) !important;
        color: var(--text-invert) !important;
        border-color: var(--yellow) !important;
    }}

    /* --- INPUTS --- */
    input, textarea, select,
    .stTextInput input, .stNumberInput input, .stDateInput input,
    .stTextArea textarea,
    [data-baseweb="input"] input, [data-baseweb="base-input"] input,
    [data-baseweb="textarea"] textarea {{
        background-color: var(--surface) !important;
        border-color: var(--border-subtle) !important;
        color: var(--text) !important;
        -webkit-text-fill-color: var(--text) !important;
        border-radius: var(--radius-sm) !important;
        caret-color: var(--text) !important;
        font-size: 1rem !important;
    }}
    .stSelectbox [data-baseweb="select"],
    .stSelectbox [data-baseweb="select"] > div,
    .stMultiSelect [data-baseweb="select"],
    .stMultiSelect [data-baseweb="select"] > div {{
        background-color: var(--surface) !important;
        border-color: var(--border-subtle) !important;
        border-radius: var(--radius-sm) !important;
    }}
    .stSelectbox [data-baseweb="select"] span,
    .stSelectbox [data-baseweb="select"] [data-testid="stMarkdownContainer"],
    .stMultiSelect [data-baseweb="select"] span,
    [data-baseweb="select"] .css-1dimb5e-singleValue {{
        color: var(--text) !important;
        -webkit-text-fill-color: var(--text) !important;
    }}
    .stSelectbox svg, .stMultiSelect svg, [data-baseweb="select"] svg {{
        fill: var(--text-2) !important;
    }}
    input::placeholder, textarea::placeholder,
    [data-baseweb="input"] input::placeholder {{
        color: var(--text-3) !important;
        -webkit-text-fill-color: var(--text-3) !important;
        opacity: 1 !important;
    }}
    [data-baseweb="popover"], [data-baseweb="menu"],
    [data-baseweb="popover"] ul, [data-baseweb="menu"] ul,
    [data-baseweb="popover"] > div, [role="listbox"] {{
        background: var(--surface) !important;
        background-color: var(--surface) !important;
        border: 1px solid var(--border) !important;
        box-shadow: var(--shadow-md) !important;
    }}
    [data-baseweb="menu"] li, [role="option"] {{
        color: var(--text) !important; background: transparent !important;
    }}
    [data-baseweb="menu"] li:hover, [role="option"]:hover,
    [role="option"][aria-selected="true"] {{ background: var(--blue-bg) !important; }}
    /* Active / focused border is near-black, per the form spec */
    input:focus, textarea:focus,
    [data-baseweb="input"]:focus-within,
    [data-baseweb="select"]:focus-within {{
        border-color: var(--border-active) !important;
        box-shadow: 0 0 0 2px rgba(13,110,253,0.18) !important;
    }}
    .stTextInput button, [data-baseweb="input"] button {{
        color: var(--text-3) !important; background: transparent !important;
    }}
    .stTextInput button:hover, [data-baseweb="input"] button:hover {{ color: var(--text) !important; }}
    .stTextInput label, .stNumberInput label, .stDateInput label,
    .stTextArea label, .stSelectbox label, .stMultiSelect label,
    .stSlider label, .stCheckbox label, .stRadio label {{
        color: var(--text-2) !important;
    }}

    /* Multiselect chips (category picker, regenerate picker) */
    .stMultiSelect [data-baseweb="tag"] {{
        background: var(--blue-bg) !important;
        border: 1px solid var(--blue) !important;
    }}
    .stMultiSelect [data-baseweb="tag"] span {{ color: var(--blue-fg) !important; }}
    .stMultiSelect [data-baseweb="tag"] svg {{ fill: var(--blue-fg) !important; }}

    /* --- CHECKBOX / RADIO — blue active state --- */
    [data-baseweb="checkbox"] span[data-checked="true"],
    [data-baseweb="radio"] div[data-checked="true"] {{
        background-color: var(--blue) !important;
        border-color: var(--blue) !important;
    }}

    /* --- SLIDER --- */
    .stSlider [data-baseweb="slider"] [role="slider"] {{ background: var(--blue) !important; }}
    .stSlider [data-baseweb="slider"] > div > div {{ background: var(--blue) !important; }}
    .stSlider > div > div > div {{ color: var(--text) !important; }}
    [data-testid="stSidebar"] .stSlider > div > div > div {{
        color: var(--text-invert) !important;
    }}
    [data-testid="stSidebar"] .stSlider [data-baseweb="slider"] [role="slider"],
    [data-testid="stSidebar"] .stSlider [data-baseweb="slider"] > div > div {{
        background: var(--yellow) !important;
    }}

    /* --- TABS  (active tab bold + underline) --- */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px; border-bottom: 1px solid var(--border);
    }}
    .stTabs [data-baseweb="tab"] {{
        color: var(--text-3) !important;
        font-weight: 600 !important; font-size: 0.9rem !important;
        background: transparent !important;
        padding: 0.5rem 0.9rem;
    }}
    .stTabs [data-baseweb="tab"]:hover {{ color: var(--text) !important; }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        color: var(--text) !important; font-weight: 700 !important;
    }}
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {{ background: var(--blue) !important; }}

    /* --- METRICS (cost panel) --- */
    [data-testid="stMetric"] {{
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-md); padding: 0.8rem 1rem;
        box-shadow: var(--shadow-sm);
    }}
    [data-testid="stMetricLabel"] p,
    [data-testid="stMetricLabel"] {{
        color: var(--text-3) !important;
        font-size: 0.72rem !important; font-weight: 600 !important;
        text-transform: uppercase; letter-spacing: 0.05em;
    }}
    [data-testid="stMetricValue"] {{
        color: var(--text) !important;
        font-weight: 700 !important; font-size: 1.35rem !important;
        letter-spacing: -0.3px;
    }}

    /* --- DIVIDER --- */
    hr, [data-testid="stDivider"] hr {{
        border-color: var(--border) !important; opacity: 1;
    }}

    /* --- EXPANDERS --- */
    .stExpander {{ border-color: var(--border) !important; }}
    div[data-testid="stExpander"] details {{
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
        box-shadow: var(--shadow-sm);
    }}
    div[data-testid="stExpander"] summary span {{
        color: var(--text) !important; font-weight: 600 !important;
    }}
    div[data-testid="stExpander"] summary:hover span {{ color: var(--blue-hover) !important; }}

    /* --- ALERTS  (st.error / warning / success / info) --- */
    .stAlert {{
        border-radius: var(--radius-md) !important;
        border: 1px solid var(--border) !important;
    }}
    .stAlert p, .stAlert div, .stAlert span {{ color: var(--text) !important; }}

    /* --- DIALOG (Overall Estimated Cost modal) --- */
    div[role="dialog"], div[role="dialog"] > div,
    [data-testid="stDialog"] > div > div {{
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-lg) !important;
        box-shadow: var(--shadow-lg) !important;
    }}
    div[role="dialog"] h1, div[role="dialog"] h2, div[role="dialog"] h3 {{
        color: var(--text); font-weight: 700; font-size: 1.125rem;
    }}

    /* --- CAPTIONS / SPINNER / TOAST --- */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
        color: var(--text-3) !important;
    }}
    .stSpinner > div {{
        border-top-color: var(--blue) !important; color: var(--text-2) !important;
    }}
    .stToast {{
        background: var(--surface) !important; color: var(--text) !important;
        border: 1px solid var(--border) !important;
    }}

    /* ================================================================
       RESPONSIVE & MOTION
       ================================================================ */
    @media (max-width: 768px) {{
        .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
        .block-container {{ padding: 3.4rem 1rem 1rem; }}
        .menu-table {{ font-size: 0.8rem; }}
        .page-title {{ font-size: 1.3rem; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
        *, *::before, *::after {{
            animation-duration: 0.001ms !important;
            transition-duration: 0.001ms !important;
        }}
    }}
</style>
"""
