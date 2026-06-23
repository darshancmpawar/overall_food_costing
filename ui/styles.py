"""App-wide CSS styles for the Streamlit frontend.

Design language — "spice kitchen, run like an operation":
a warm espresso-charcoal ground with a saffron accent (drawn from the
subject — Indian corporate catering — rather than a generic dashboard
violet), basmati-cream text, and tabular mono numerals so every plate
cost and percentage lines up like a ledger. Every text/surface pair here
was checked for WCAG-AA contrast.

Tokens live in :root; every colour below derives from them. Editing the
palette is a one-stop change at the top.
"""

STYLES = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

    /* ================================================================
       DESIGN TOKENS  —  warm spice palette, contrast-checked
       ================================================================ */
    :root {
        --ground:        #17130E;  /* warm espresso-charcoal page bg     */
        --surface:       #211B14;  /* cards / panels                     */
        --surface-2:     #2A2219;  /* inputs, table header, sunk areas   */
        --elevated:      #34291D;  /* hover / active                     */
        --border:        #3A2F22;  /* subtle warm hairline               */
        --border-strong: #54422E;

        --text:          #F7F1E6;  /* basmati cream  (16.4:1 on ground)  */
        --text-2:        #C9BCA8;  /* warm secondary (8.4:1 on surface)  */
        --text-3:        #9A8C77;  /* warm tertiary  (4.8:1 on surface)  */
        --text-muted:    #6E6151;

        --saffron:       #F2A03D;  /* primary accent                     */
        --saffron-deep:  #D9822B;  /* accent hover / pressed             */
        --saffron-soft:  rgba(242,160,61,0.14);
        --paprika:       #C8472B;  /* secondary accent / deep warm       */

        --mint:          #8FD6A6;  /* success / coriander                */
        --turmeric:      #E8C24A;  /* warning                            */
        --chili:         #EF8A6A;  /* danger (text-safe, 6.2:1)          */
        --info:          #7FB6D9;  /* info                               */

        --font-display: 'Fraunces', 'Iowan Old Style', Georgia, serif;
        --font-body: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        --font-mono: 'IBM Plex Mono', 'SFMono-Regular', ui-monospace, 'Menlo', monospace;

        --radius-sm: 7px;
        --radius-md: 11px;
        --radius-lg: 16px;
        --radius-xl: 22px;
        --shadow-sm: 0 1px 2px rgba(0,0,0,0.35);
        --shadow-md: 0 6px 18px rgba(0,0,0,0.40);
        --shadow-lg: 0 16px 44px rgba(0,0,0,0.55);
        --glow:      0 0 24px rgba(242,160,61,0.22);
        --transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* ================================================================
       GLOBAL
       ================================================================ */
    .stApp {
        background:
            radial-gradient(1100px 380px at 78% -8%, rgba(242,160,61,0.07), transparent 60%),
            radial-gradient(820px 320px at 6% -4%, rgba(200,71,43,0.06), transparent 55%),
            var(--ground);
        color: var(--text);
        font-family: var(--font-body);
        -webkit-font-smoothing: antialiased;
    }
    .block-container {
        padding: 3.6rem 2rem 2rem;
        max-width: 1400px;
    }
    [data-testid="stMarkdownContainer"] p { color: var(--text-2); }
    a { color: var(--saffron); }
    a:hover { color: var(--saffron-deep); }

    /* Tabular, ledger-style numerals wherever money or counts appear */
    .metric-value, .cost-value, .qty-value, .cost-pill, .qty-pill,
    .stNumberInput input,
    [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
        font-family: var(--font-mono) !important;
        font-feature-settings: "tnum" 1, "zero" 1;
    }

    /* Warm scrollbars */
    ::-webkit-scrollbar { width: 11px; height: 11px; }
    ::-webkit-scrollbar-track { background: var(--ground); }
    ::-webkit-scrollbar-thumb {
        background: var(--border-strong); border-radius: 99px;
        border: 2px solid var(--ground);
    }
    ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

    /* Keyboard focus — saffron ring everywhere */
    *:focus-visible {
        outline: 2px solid var(--saffron) !important;
        outline-offset: 2px !important;
        border-radius: var(--radius-sm);
    }

    /* ================================================================
       STREAMLIT HEADER / TOOLBAR
       ================================================================ */
    header[data-testid="stHeader"] {
        background: rgba(23,19,14,0.85) !important;
        backdrop-filter: blur(8px);
        border-bottom: 1px solid var(--border) !important;
    }
    [data-testid="stToolbar"] button,
    [data-testid="stToolbar"] a { color: var(--text-2) !important; }
    [data-testid="stToolbar"] button:hover,
    [data-testid="stToolbar"] a:hover { color: var(--text) !important; }
    [data-testid="collapsedControl"] button,
    [data-testid="stSidebarCollapsedControl"] button { color: var(--text-2) !important; }
    [data-testid="collapsedControl"] button:hover,
    [data-testid="stSidebarCollapsedControl"] button:hover { color: var(--text) !important; }
    footer, .stDeployButton,
    [data-testid="stDecoration"] { display: none !important; }
    ._profileContainer_gzau3_53,
    [data-testid="manage-app-button"] { display: none !important; }

    /* ================================================================
       SIDEBAR
       ================================================================ */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1d1812 0%, var(--surface) 100%) !important;
        border-right: 1px solid var(--border) !important;
    }
    [data-testid="stSidebar"][aria-expanded="true"] {
        min-width: 300px !important; max-width: 300px !important;
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 4rem !important; }
    [data-testid="stSidebar"] label {
        color: var(--text-2) !important;
        font-size: 0.74rem !important; font-weight: 600 !important;
        letter-spacing: 0.04em; text-transform: uppercase;
    }

    .sidebar-brand {
        padding: 0.25rem 0 1.4rem;
        border-bottom: 1px solid var(--border);
        margin-bottom: 1.4rem;
    }
    .sidebar-brand-row { display: flex; align-items: center; gap: 0.7rem; }
    .sidebar-brand-icon {
        width: 40px; height: 40px; border-radius: var(--radius-md);
        background: linear-gradient(140deg, var(--saffron), var(--paprika));
        display: flex; align-items: center; justify-content: center;
        font-size: 1.25rem; flex-shrink: 0; box-shadow: var(--glow);
    }
    .sidebar-brand h2 {
        margin: 0; font-family: var(--font-display);
        font-size: 1.3rem; color: var(--text);
        font-weight: 600; letter-spacing: -0.2px; line-height: 1.1;
    }
    .sidebar-brand p {
        margin: 2px 0 0; font-size: 0.68rem; color: var(--text-3);
        font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase;
    }

    .user-chip {
        display: flex; align-items: center; gap: 0.6rem;
        padding: 0.6rem 0.7rem; background: var(--surface-2);
        border: 1px solid var(--border); border-radius: var(--radius-md);
        margin-bottom: 0.75rem;
    }
    .user-avatar {
        width: 32px; height: 32px; border-radius: 50%;
        background: linear-gradient(140deg, var(--saffron), var(--paprika));
        display: flex; align-items: center; justify-content: center;
        font-size: 0.74rem; font-weight: 700; color: #2a1708; flex-shrink: 0;
    }
    .user-chip-info { flex: 1; min-width: 0; }
    .user-chip-name {
        font-size: 0.82rem; font-weight: 600; color: var(--text);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .user-chip-role {
        font-size: 0.64rem; color: var(--text-3);
        text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
    }

    /* ================================================================
       PAGE HEADER
       ================================================================ */
    .page-title {
        font-family: var(--font-display);
        font-size: 2rem; font-weight: 600; color: var(--text);
        margin: 0; letter-spacing: -0.5px; line-height: 1.1;
    }
    .page-subtitle {
        font-size: 0.84rem; color: var(--text-3); margin: 0.3rem 0 0;
        font-weight: 400;
    }
    .plan-source-badge { font-family: var(--font-body); }

    /* ================================================================
       METRIC CARDS  (custom .metric-card grid)
       ================================================================ */
    .metrics-grid {
        display: grid; grid-template-columns: repeat(4, 1fr);
        gap: 0.8rem; margin-bottom: 1.75rem;
    }
    .metric-card {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-lg); padding: 1rem 1.15rem;
        position: relative; overflow: hidden; transition: var(--transition);
    }
    .metric-card:hover {
        border-color: var(--border-strong);
        transform: translateY(-2px); box-shadow: var(--shadow-md);
    }
    .metric-card::before {
        content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    }
    .metric-card:nth-child(1)::before { background: linear-gradient(90deg, var(--saffron), var(--paprika)); }
    .metric-card:nth-child(2)::before { background: linear-gradient(90deg, var(--mint), #4f9e6f); }
    .metric-card:nth-child(3)::before { background: linear-gradient(90deg, var(--turmeric), var(--saffron-deep)); }
    .metric-card:nth-child(4)::before { background: linear-gradient(90deg, var(--chili), var(--paprika)); }
    .metric-label {
        font-size: 0.64rem; color: var(--text-3);
        text-transform: uppercase; letter-spacing: 0.07em;
        font-weight: 600; margin-bottom: 0.35rem;
    }
    .metric-value {
        font-size: 1.55rem; font-weight: 600; color: var(--text);
        letter-spacing: -0.5px; line-height: 1;
    }

    /* ================================================================
       MENU TABLE  —  the hero
       ================================================================ */
    .menu-table-wrap {
        border: 1px solid var(--border); border-radius: var(--radius-lg);
        overflow: hidden; box-shadow: var(--shadow-md); background: var(--surface);
    }
    .menu-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    .menu-table thead th {
        background: var(--surface-2); color: var(--text-2);
        padding: 0.8rem 0.85rem; text-align: center; font-weight: 600;
        font-size: 0.76rem; border-bottom: 1px solid var(--border);
        border-right: 1px solid var(--border);
    }
    .menu-table thead th:first-child {
        text-align: left; min-width: 120px; background: var(--elevated);
    }
    .menu-table thead th:last-child { border-right: none; }
    .day-label {
        display: block; color: var(--text); font-weight: 700;
        font-size: 0.82rem; margin-bottom: 5px;
    }
    .theme-tag {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 2px 9px; border-radius: 99px;
        font-size: 0.6rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.6;
    }
    .menu-table tbody td {
        padding: 0.75rem 0.9rem;
        border-bottom: 1px solid var(--border);
        border-right: 1px solid var(--border);
        color: var(--text-2); background: var(--surface);
        vertical-align: top; transition: background 0.15s ease;
    }
    .menu-table tbody td:first-child {
        font-weight: 600; color: var(--text-2); background: var(--surface-2);
        font-size: 0.72rem; white-space: nowrap; min-width: 120px;
        text-transform: uppercase; letter-spacing: 0.04em; vertical-align: middle;
        border-right: 1px solid var(--border);
    }
    .menu-table tbody td:last-child { border-right: none; }
    .menu-table tbody tr:last-child td { border-bottom: none; }
    .menu-table tbody tr:hover td { background: var(--elevated); }
    .menu-table tbody tr:hover td:first-child { background: var(--elevated); }

    .item-name {
        color: var(--text); font-weight: 600; font-size: 0.84rem;
        line-height: 1.3;
    }
    .color-pill {
        display: inline-block; margin-left: 5px; padding: 1px 7px;
        border-radius: 99px; font-size: 0.6rem; font-weight: 700;
    }
    .cell-empty { color: var(--text-muted); font-size: 0.84rem; }

    /* Cost & quantity pills (second line of a cell) */
    .item-cost-row { display: flex; align-items: center; gap: 6px; margin-top: 7px; }
    .qty-pill {
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: 6px;
        font-size: 0.64rem; font-weight: 600; letter-spacing: 0.01em;
        background: rgba(201,188,168,0.12); color: var(--text-2);
    }
    .cost-pill {
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: 6px;
        font-size: 0.66rem; font-weight: 700; letter-spacing: 0.01em;
        background: var(--saffron-soft); color: var(--saffron);
    }

    /* Plate-cost / qty footer rows */
    .menu-table tbody .cost-footer-row td {
        background: var(--elevated) !important;
        vertical-align: middle !important;
        padding: 0.8rem 0.9rem !important;
    }
    .menu-table tbody .cost-footer-row.cost-footer-first td {
        border-top: 2px solid var(--saffron) !important;
    }
    .menu-table tbody .cost-footer-row:hover td { background: var(--elevated) !important; }
    .cost-footer-label {
        font-size: 0.68rem !important; font-weight: 700 !important;
        color: var(--text-2) !important;
        text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap;
    }
    .cost-footer-value {
        text-align: center; font-weight: 700 !important; font-size: 0.92rem !important;
    }
    .cost-footer-row .cost-value { color: var(--mint) !important; }
    .cost-footer-row .qty-value  { color: var(--text-2) !important; }

    /* ================================================================
       POOL WARNINGS / EMPTY STATE / CHANGES LOG
       ================================================================ */
    .pool-warn-bar {
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.65rem 1rem; margin-bottom: 0.6rem;
        background: rgba(232,194,74,0.08);
        border: 1px solid rgba(232,194,74,0.22);
        border-radius: var(--radius-md); font-size: 0.8rem; color: var(--turmeric);
    }

    .empty-state {
        text-align: center; padding: 5rem 2rem;
        border: 1.5px dashed var(--border-strong);
        border-radius: var(--radius-xl); margin: 3rem auto; max-width: 520px;
        background: linear-gradient(180deg, rgba(242,160,61,0.03), transparent);
    }
    .empty-icon {
        width: 68px; height: 68px; margin: 0 auto 1.1rem; border-radius: 50%;
        background: linear-gradient(140deg, var(--saffron), var(--paprika));
        display: flex; align-items: center; justify-content: center;
        font-size: 1.7rem; box-shadow: var(--glow);
    }
    .empty-state h3 {
        color: var(--text); margin: 0 0 0.45rem;
        font-family: var(--font-display); font-size: 1.3rem; font-weight: 600;
    }
    .empty-state p { color: var(--text-3); font-size: 0.86rem; margin: 0; line-height: 1.6; }

    .log-entry {
        padding: 0.45rem 0.8rem; background: var(--surface-2);
        border-left: 3px solid var(--saffron);
        border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
        margin-bottom: 0.35rem; font-size: 0.78rem; color: var(--text-2);
        animation: fadeInUp 0.18s ease-out;
    }
    .log-entry.log-diff { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }
    .log-day {
        color: var(--text); font-weight: 600;
        font-size: 0.74rem; letter-spacing: 0.02em;
    }
    .log-slot {
        color: var(--text-3); font-weight: 600;
        font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em;
    }
    .log-sep { color: var(--text-muted); font-size: 0.72rem; }
    .log-old {
        color: var(--text-3); text-decoration: line-through;
        text-decoration-color: rgba(239,138,106,0.6); font-size: 0.78rem;
    }
    .log-arrow { color: var(--saffron); font-weight: 700; padding: 0 2px; }
    .log-new { color: var(--mint); font-weight: 600; font-size: 0.8rem; }
    .regen-day-header {
        font-weight: 700; font-size: 0.82rem; color: var(--text);
        margin-bottom: 0.3rem; display: flex; align-items: center; gap: 0.4rem;
    }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(3px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .menu-table-wrap, .metrics-grid { animation: fadeInUp 0.24s ease-out; }

    /* ================================================================
       STREAMLIT COMPONENTS
       ================================================================ */

    /* --- BUTTONS --- */
    .stButton > button,
    .stFormSubmitButton > button,
    .stDownloadButton > button,
    button[data-testid="baseButton-secondary"],
    button[data-testid="baseButton-primary"],
    button[data-testid="baseButton-minimal"] {
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        font-size: 0.82rem !important;
        letter-spacing: 0.01em;
        transition: var(--transition) !important;
    }
    /* Primary — saffron, dark text (8.7:1) */
    .stButton > button[kind="primary"],
    .stFormSubmitButton > button,
    button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, var(--saffron), var(--saffron-deep)) !important;
        border: none !important;
        color: #241606 !important;
        box-shadow: 0 2px 10px rgba(242,160,61,0.30) !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stFormSubmitButton > button:hover,
    button[data-testid="baseButton-primary"]:hover {
        box-shadow: 0 6px 20px rgba(242,160,61,0.45) !important;
        transform: translateY(-1px);
    }
    /* Secondary — warm surface */
    .stButton > button:not([kind="primary"]),
    .stDownloadButton > button,
    button[data-testid="baseButton-secondary"] {
        background: var(--surface-2) !important;
        color: var(--text) !important;
        border: 1px solid var(--border-strong) !important;
    }
    .stButton > button:not([kind="primary"]):hover,
    .stDownloadButton > button:hover,
    button[data-testid="baseButton-secondary"]:hover {
        background: var(--elevated) !important;
        color: var(--text) !important;
        border-color: var(--saffron) !important;
    }

    /* --- INPUTS --- */
    input, textarea, select,
    .stTextInput input, .stNumberInput input, .stDateInput input,
    .stTextArea textarea,
    [data-baseweb="input"] input, [data-baseweb="base-input"] input,
    [data-baseweb="textarea"] textarea {
        background-color: var(--surface-2) !important;
        border-color: var(--border) !important;
        color: var(--text) !important;
        -webkit-text-fill-color: var(--text) !important;
        border-radius: var(--radius-sm) !important;
        caret-color: var(--saffron) !important;
    }
    .stSelectbox [data-baseweb="select"],
    .stSelectbox [data-baseweb="select"] > div,
    .stMultiSelect [data-baseweb="select"],
    .stMultiSelect [data-baseweb="select"] > div {
        background-color: var(--surface-2) !important;
        border-color: var(--border) !important;
        border-radius: var(--radius-sm) !important;
    }
    .stSelectbox [data-baseweb="select"] span,
    .stSelectbox [data-baseweb="select"] [data-testid="stMarkdownContainer"],
    .stMultiSelect [data-baseweb="select"] span,
    [data-baseweb="select"] .css-1dimb5e-singleValue {
        color: var(--text) !important;
        -webkit-text-fill-color: var(--text) !important;
    }
    .stSelectbox svg, .stMultiSelect svg, [data-baseweb="select"] svg { fill: var(--text-3) !important; }
    input::placeholder, textarea::placeholder,
    [data-baseweb="input"] input::placeholder {
        color: var(--text-muted) !important;
        -webkit-text-fill-color: var(--text-muted) !important;
        opacity: 1 !important;
    }
    [data-baseweb="popover"], [data-baseweb="menu"],
    [data-baseweb="popover"] ul, [data-baseweb="menu"] ul,
    [data-baseweb="popover"] > div, [role="listbox"] {
        background: var(--elevated) !important;
        background-color: var(--elevated) !important;
        border-color: var(--border) !important;
    }
    [data-baseweb="menu"] li, [role="option"] { color: var(--text) !important; background: transparent !important; }
    [data-baseweb="menu"] li:hover, [role="option"]:hover,
    [role="option"][aria-selected="true"] { background: var(--saffron-soft) !important; }
    input:focus, textarea:focus,
    [data-baseweb="input"]:focus-within,
    [data-baseweb="select"]:focus-within {
        border-color: var(--saffron) !important;
        box-shadow: 0 0 0 2px rgba(242,160,61,0.30) !important;
    }
    .stTextInput button, [data-baseweb="input"] button {
        color: var(--text-3) !important; background: transparent !important;
    }
    .stTextInput button:hover, [data-baseweb="input"] button:hover { color: var(--text) !important; }
    .stTextInput label, .stNumberInput label, .stDateInput label,
    .stTextArea label, .stSelectbox label, .stMultiSelect label,
    .stSlider label, .stCheckbox label, .stRadio label { color: var(--text-2) !important; }

    /* Multiselect chips (regenerate picker) */
    .stMultiSelect [data-baseweb="tag"] {
        background: var(--saffron-soft) !important;
        border: 1px solid rgba(242,160,61,0.4) !important;
    }
    .stMultiSelect [data-baseweb="tag"] span { color: var(--saffron) !important; }

    /* --- SLIDER --- */
    .stSlider [data-baseweb="slider"] [role="slider"] { background: var(--saffron) !important; }
    .stSlider [data-baseweb="slider"] > div > div { background: var(--saffron) !important; }
    .stSlider > div > div > div { color: var(--text) !important; }

    /* --- TABS (cost dialog) --- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px; border-bottom: 1px solid var(--border);
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--text-3) !important;
        font-weight: 600 !important; font-size: 0.86rem !important;
        background: transparent !important;
        padding: 0.5rem 0.9rem;
    }
    .stTabs [data-baseweb="tab"]:hover { color: var(--text) !important; }
    .stTabs [data-baseweb="tab"][aria-selected="true"] { color: var(--saffron) !important; }
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] { background: var(--saffron) !important; }

    /* --- METRICS (cost panel) --- */
    [data-testid="stMetric"] {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-md); padding: 0.8rem 1rem;
    }
    [data-testid="stMetricLabel"] p,
    [data-testid="stMetricLabel"] {
        color: var(--text-3) !important;
        font-size: 0.68rem !important; font-weight: 600 !important;
        text-transform: uppercase; letter-spacing: 0.05em;
    }
    [data-testid="stMetricValue"] {
        color: var(--text) !important;
        font-weight: 600 !important; font-size: 1.5rem !important;
        letter-spacing: -0.5px;
    }

    /* --- DIVIDER --- */
    hr, [data-testid="stDivider"] hr {
        border-color: var(--border) !important; opacity: 1;
    }

    /* --- EXPANDERS --- */
    .stExpander { border-color: var(--border) !important; }
    div[data-testid="stExpander"] details {
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-md) !important;
    }
    div[data-testid="stExpander"] summary span { color: var(--text-2) !important; font-weight: 600 !important; }
    div[data-testid="stExpander"] summary:hover span { color: var(--text) !important; }

    /* --- ALERTS  (st.error / warning / success / info) --- */
    .stAlert { border-radius: var(--radius-md) !important; border: 1px solid var(--border) !important; }
    .stAlert p, .stAlert div, .stAlert span { color: var(--text) !important; }

    /* --- DIALOG (Overall Estimated Cost modal) --- */
    div[role="dialog"], [data-testid="stDialog"] > div > div {
        background: var(--surface) !important;
        border: 1px solid var(--border-strong) !important;
        border-radius: var(--radius-lg) !important;
        box-shadow: var(--shadow-lg) !important;
    }
    div[role="dialog"] h1, div[role="dialog"] h2, div[role="dialog"] h3 {
        font-family: var(--font-display); color: var(--text); font-weight: 600;
    }

    /* --- CAPTIONS / SPINNER --- */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color: var(--text-3) !important;
    }
    .stSpinner > div { border-top-color: var(--saffron) !important; color: var(--saffron) !important; }
    .stToast { background: var(--elevated) !important; color: var(--text) !important; }

    /* ================================================================
       RESPONSIVE & MOTION
       ================================================================ */
    @media (max-width: 768px) {
        .metrics-grid { grid-template-columns: repeat(2, 1fr); }
        .block-container { padding: 3.5rem 1rem 1rem; }
        .menu-table { font-size: 0.75rem; }
        .page-title { font-size: 1.6rem; }
    }
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            animation-duration: 0.001ms !important;
            transition-duration: 0.001ms !important;
        }
    }
</style>
"""
