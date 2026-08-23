"""Pulse / OP Lens design tokens — the single source of truth for colour.

``ui.styles`` mirrors these values into CSS custom properties for the
stylesheet; every module that has to build an inline ``style="…"`` string
(status badges, day-theme tags, colour pills, the editor cards) imports
them from here instead of hard-coding a hex. Retheming is then one file.

Palette summary (see docs/UI_THEMING_2 for the full guide):

* Light theme only — light-grey canvas, white cards, dark table headers.
* **Brand yellow** ``#FEBF34`` is the primary action colour, on dark text.
* **Brand blue** ``#0D6EFD`` carries links, information, and selection.
* **Purple** ``#6F42C1`` is reserved for special emphasis, never actions.
* Status colours always mean the same thing: green positive, orange
  caution, red negative.
* **Figtree** is the typeface at every size and weight.

Pairing rule: the ``*_BG`` tints are page-surface backgrounds, and each
one has a matching ``*_FG`` that is dark enough to read on it (the raw
brand hues — ``#FEBF34``, ``#1AA45B``, ``#FA1024`` — are for filled
buttons and solid badges with white/dark text, not for text on a tint).
"""

# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------
BRAND_YELLOW = "#FEBF34"
BRAND_YELLOW_HOVER = "#EDAD1C"
BRAND_YELLOW_BG = "#FFF6E3"
BRAND_YELLOW_FG = "#8A5A00"  # readable amber for text on the yellow tint

BRAND_BLUE = "#0D6EFD"
BRAND_BLUE_HOVER = "#0A58CA"
BRAND_BLUE_BG = "#EBF3FF"
BRAND_BLUE_FG = "#0A58CA"

PURPLE = "#6F42C1"
PURPLE_BG = "#F1EAFB"
PURPLE_FG = "#5A34A3"

NAV_DEEP = "#031633"
NAV_MID = "#084298"

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
SUCCESS = "#1AA45B"
SUCCESS_BG = "#E5FFF1"
SUCCESS_FG = "#0F7A42"

WARNING = "#F78D00"
WARNING_ALT = "#FF9E1D"
WARNING_BG = "#FFF5E8"
WARNING_FG = "#B35F00"

ERROR = "#FA1024"
ERROR_BG = "#FFE7E9"
ERROR_FG = "#B3121F"

INFO = BRAND_BLUE
INFO_BG = BRAND_BLUE_BG
INFO_FG = BRAND_BLUE_FG

# ---------------------------------------------------------------------------
# Neutrals — text, surfaces, borders
# ---------------------------------------------------------------------------
TEXT = "#131313"
TEXT_2 = "#414141"
TEXT_3 = "#777777"
TEXT_DISABLED = "#AEAEAE"
TEXT_ON_DARK = "#FFFFFF"

PAGE_BG = "#F5F5F5"
CARD_BG = "#FFFFFF"
ROW_ALT_BG = "#F9F9F9"
DISABLED_BG = "#E5E5E5"

BORDER = "#E5E5E5"
BORDER_SUBTLE = "#AEAEAE"
BORDER_ACTIVE = "#131313"

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
FONT_FAMILY = (
    "'Figtree', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "'Helvetica Neue', sans-serif"
)

# ---------------------------------------------------------------------------
# Semantic maps consumed by the render layer
# ---------------------------------------------------------------------------

# Day-theme tag: theme name -> (background tint, text colour).
THEME_TAG_COLORS = {
    "mix": (BRAND_BLUE_BG, BRAND_BLUE_FG),
    "chinese": (PURPLE_BG, PURPLE_FG),
    "biryani": (BRAND_YELLOW_BG, BRAND_YELLOW_FG),
    "south": (SUCCESS_BG, SUCCESS_FG),
    "north": (WARNING_BG, WARNING_FG),
    # Extended theme name a counter may store; canonicalised to 'chinese'
    # before it reaches the solver, but the editor renders the raw value.
    "chinese_continental": (PURPLE_BG, PURPLE_FG),
}

# Fallback for an unknown / empty theme.
TAG_NEUTRAL = (DISABLED_BG, TEXT_2)

# Item colour pill: ontology colour initial -> (label, background, text).
ITEM_COLOR_PILLS = {
    "R": ("Red", ERROR_BG, ERROR_FG),
    "G": ("Green", SUCCESS_BG, SUCCESS_FG),
    "B": ("Brown", "#F5EDE3", "#7A4E1D"),
    "Y": ("Yellow", BRAND_YELLOW_BG, BRAND_YELLOW_FG),
    "W": ("White", PAGE_BG, TEXT_2),
    "O": ("Orange", WARNING_BG, WARNING_FG),
    "K": ("Black", DISABLED_BG, TEXT),
}

# Diagnostic severity -> (background tint, text colour, display label).
SEVERITY_STYLES = {
    "error": (ERROR_BG, ERROR_FG, "Error"),
    "warning": (WARNING_BG, WARNING_FG, "Warning"),
    "info": (INFO_BG, INFO_FG, "Info"),
}
