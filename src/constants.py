"""
Shared constants for slot names, display labels, and other static config.

This module has zero heavy dependencies (no pandas, no ortools) so it can be
safely imported by lightweight layers like the UI without triggering the full
preprocessor import chain.
"""

from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Slot names
# ---------------------------------------------------------------------------

SLOT_SUFFIX_SEP = '__'

BASE_SLOT_NAMES: List[str] = [
    'welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
    'healthy_rice', 'curd_rice', 'dal', 'sambar', 'rasam', 'dal_sambar',
    'sambar_rasam', 'veg_gravy', 'veg_dry', 'nonveg_main', 'curd_side',
    'curd', 'dessert',
]

# Slots the ontology must be able to fill for *any* client. The combined
# and niche slots below are opt-in per counter, so an ontology without
# them is still usable — PoolBuilder warns instead of raising.
REQUIRED_POOL_SLOTS: List[str] = [
    'welcome_drink', 'soup', 'salad', 'starter', 'bread', 'rice',
    'healthy_rice', 'dal', 'sambar', 'rasam', 'veg_gravy', 'veg_dry',
    'nonveg_main', 'curd_side', 'dessert',
]

# The menu shape a new counter starts from: the most common stored
# client's category set (bread, rice, two vegetables, dal + sambar +
# rasam, curd side, dessert, salad, plus a non-veg main). Deliberately
# not REQUIRED_POOL_SLOTS — that list is "everything the ontology can
# always fill", which is more courses than any real client serves and
# lands a plate at ~1.28 kg, over MAX_PLATE_WEIGHT_KG before a single
# choice is made.
DEFAULT_COUNTER_SLOTS: List[str] = [
    'salad', 'bread', 'rice', 'veg_gravy', 'veg_dry', 'nonveg_main',
    'dal', 'sambar', 'rasam', 'curd_side', 'dessert',
]

# Slots that draw from the union of two other pools. Clients that merge
# two courses onto one serving line (e.g. "dal_sambar" — one ladle,
# either dish) declare the combined slot in their counter's categories.
COMBINED_SLOT_SOURCES: Dict[str, List[str]] = {
    'dal_sambar': ['dal', 'sambar'],
    'sambar_rasam': ['sambar', 'rasam'],
}

CONST_SLOTS: List[str] = ['white_rice', 'papad', 'pickle', 'chutney']

CONSTANT_ITEMS: Dict[str, str] = {
    'white_rice': 'steamed rice',
    'papad': 'Papad',
    'pickle': 'Pickle',
    'chutney': 'chutney',
}

EXEMPT_FROM_CUISINE: Set[str] = {
    'welcome_drink', 'dal', 'sambar', 'rasam', 'starter', 'soup', 'salad',
    'healthy_rice', 'dal_sambar', 'sambar_rasam', 'curd', 'curd_rice',
}

REPEATABLE_ITEM_BASES: Set[str] = {'curd'}

PULAO_SUBCATS: Set[str] = {
    'south_veg_pulao', 'north_simple_veg_pulao', 'north_rich_pulao',
    'millet_pulao', 'mixed_grain_pulao',
}

THEME_FALLBACK_SLOTS: Set[str] = {'starter', 'veg_dry'}

# Items that must never appear in a flavored-rice slot — plain/steamed rice
# variants belong in the CONST_SLOTS 'white_rice' slot instead.
RICE_EXCLUDE_ITEMS: Set[str] = {
    'steamed_rice', 'steamed rice',
    'white_rice', 'white rice',
    'steam rice',
    'plain_rice', 'plain rice',
}

# ---------------------------------------------------------------------------
# Serving weights
# ---------------------------------------------------------------------------

# Canonical serving weight (kg) for a whole course, applied by
# ``DataCleanser`` regardless of what the ontology says.
#
# ``cost_per_kg`` and ``grammage_per_serving`` in menu_items.xlsx are
# XLOOKUP formulas against a separate "Menu List" workbook, so the values
# the app reads are Excel's cached results and the file cannot be
# corrected in place — a re-export would reintroduce whatever upstream
# holds. Corrections therefore live here, where they survive a refresh.
#
# bread: upstream carried three conventions — 30–70 g for one piece
# (correct), 1000 g on 18 chapatti rows (a unit slip: a kilogram of
# chapatti is not a serving, and it outweighed the other fourteen
# categories combined), and 0 g on 2 continental loaves. One serving of
# bread is 60 g, so the whole course is normalised to it rather than only
# the outliers being patched — one convention is the point.
COURSE_SERVING_GRAMMAGE_KG: Dict[str, float] = {
    'bread': 0.06,
}

# ---------------------------------------------------------------------------
# Plate weight policy
# ---------------------------------------------------------------------------

# A plate may not exceed this total serving weight (grams), counting every
# item served that day including the constant accompaniments.
PLATE_CAP_GRAMS = 1000

# Themes that are allowed a heavier plate. A biryani day is a 300 g rice
# plus a 300 g non-veg biryani before anything else is served — the meal
# genuinely weighs more, so it gets its own ceiling rather than forcing
# the portions down to a number that suits a mixed day.
PLATE_CAP_GRAMS_BY_THEME: Dict[str, int] = {
    'biryani': 1100,
}

# A plate with more than this many items is exempt: a counter serving
# eighteen lines cannot fit the same total as one serving eleven, and
# trimming everything to make it would leave portions no one would serve.
PLATE_CAP_SLOT_EXEMPTION = 15

# When a plate can't be brought under its cap by choosing lighter items,
# portions are trimmed instead — in whole steps of this many grams, so
# the numbers stay round enough for a kitchen to work to.
PLATE_TRIM_STEP_GRAMS = 5

# No single portion may lose more than this share of itself. Keeps a trim
# spread across several items rather than gutting one of them, and
# guarantees no portion is ever reduced to nothing.
PLATE_TRIM_MAX_CUT_FRACTION = 0.25

# Backwards-compatible alias: the rule's own default cap, in kilograms.
MAX_PLATE_WEIGHT_KG = PLATE_CAP_GRAMS / 1000.0


def plate_cap_grams(day_type: str, slot_count: int) -> Optional[int]:
    """Serving-weight ceiling for one plate, or ``None`` when uncapped.

    Resolution order, most specific first:

    1. A plate with more than :data:`PLATE_CAP_SLOT_EXEMPTION` items is
       uncapped — more lines legitimately means more food.
    2. A theme listed in :data:`PLATE_CAP_GRAMS_BY_THEME` uses its own
       ceiling (biryani days are heavier by nature).
    3. Everything else gets :data:`PLATE_CAP_GRAMS`.
    """
    if slot_count > PLATE_CAP_SLOT_EXEMPTION:
        return None
    theme = canonical_theme(day_type or '')
    return PLATE_CAP_GRAMS_BY_THEME.get(theme, PLATE_CAP_GRAMS)


DISPLAY_SLOT_NAME: Dict[str, str] = {
    'rice': 'Flavor Rice',
    'healthy_rice': 'Healthy Rice',
    'curd_rice': 'Curd Rice',
    'white_rice': 'White Rice',
    'welcome_drink': 'Welcome Drink',
    'soup': 'Soup',
    'salad': 'Salad',
    'veg_gravy': 'Veg Gravy',
    'veg_dry': 'Veg Dry',
    'nonveg_main': 'Nonveg Main',
    'curd_side': 'Curd Side',
    'curd': 'Curd',
    'dal_sambar': 'Dal / Sambar',
    'sambar_rasam': 'Sambar / Rasam',
}

# ---------------------------------------------------------------------------
# Day themes
# ---------------------------------------------------------------------------

# Themes the solver's filters understand. Anything a client stores in its
# counter ``theme_map`` is normalised into one of these via THEME_ALIASES
# before it reaches the pool filters.
SOLVER_THEMES: List[str] = ['mix', 'chinese', 'biryani', 'south', 'north']

# Themes an admin may pick in the editor. Extended names map onto a
# solver theme; they exist because operations names a day's counter
# concept differently from the cuisine filter it implies.
AVAILABLE_THEMES: List[str] = SOLVER_THEMES + ['chinese_continental']

THEME_ALIASES: Dict[str, str] = {
    'chinese_continental': 'chinese',
    'continental': 'chinese',
    'pan_asian': 'chinese',
}


def canonical_theme(theme: str) -> str:
    """Return the solver-facing theme for a stored theme value.

    Counter theme maps may hold operations-facing names (e.g.
    ``chinese_continental``); every pool filter and rule compares against
    the canonical five (:data:`SOLVER_THEMES`), so all reads funnel
    through here. Unknown values pass through unchanged so a typo shows
    up as "no items matched this theme" rather than being silently
    rewritten to something that does match.
    """
    t = (theme or '').strip().lower()
    return THEME_ALIASES.get(t, t)


DEFAULT_THEME_MAP: Dict[str, str] = {
    'monday': 'mix',
    'tuesday': 'chinese',
    'wednesday': 'biryani',
    'thursday': 'south',
    'friday': 'north',
    'saturday': 'south',
    'sunday': 'north',
}

# Days a counter's theme map may key on. Saturday/Sunday only matter for
# clients with ``serve_weekends = true``.
WEEKDAY_NAMES: List[str] = [
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
]
WEEKEND_NAMES: List[str] = ['saturday', 'sunday']
ALL_DAY_NAMES: List[str] = WEEKDAY_NAMES + WEEKEND_NAMES

# Fallbacks for client settings that are NULL in the database.
DEFAULT_ITEM_COOLDOWN_DAYS = 20
DEFAULT_COUNTER_NAME = 'Counter 1'
