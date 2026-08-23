"""Cost and serving weight, taken from the Menu List workbook.

``data/raw/menu_items.xlsx`` (the ontology) used to hold ``cost_per_kg``
and ``grammage_per_serving`` as XLOOKUP formulas pointing at a separate
"Menu List" workbook, so the values pandas read were whatever Excel last
cached — stale the moment prices moved.

``data/raw/menu_prices.xlsx`` is that Menu List. Its numbers are now baked
into the ontology by ``scripts/bake_price_list.py``, and this module
re-applies them on every read, so a price refresh takes effect as a file
drop with no need to open Excel or re-bake.

Matching is by normalised item name, which is the same key the XLOOKUP
used, with a short alias map for items whose ontology name is a base form
of the list's. Items the list doesn't mention keep whatever the ontology
holds, so a partial price list degrades instead of blanking out costs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .column_mapper import _norm_str, pick_col

logger = logging.getLogger(__name__)

# The sheet holding one row per item. Falls back to the first sheet.
PRICE_SHEET_NAME = "Menu List"

_ITEM_ALIASES = ["item", "menu_items", "menu_item"]
_COST_ALIASES = ["cost per KG", "cost_per_kg", "cost per kg", "costperkg"]
_GRAM_ALIASES = [
    "grammage per serving", "grammage_per_serving", "grammage", "serving",
]

# Two ontology items carry a base name where the Menu List spells out the
# variant. Both resolve to the plain, default variant — the premium ones
# are separate offerings the ontology lists separately, and the priced
# rice the app means by "steamed rice" is Sona Masoori. Keys and values
# are compared after :func:`_norm_str`.
_ITEM_NAME_ALIASES = {
    "myos": "myos regular",
    "steamed_rice": "steamed_rice - sona masoori",
}


def _match_key(name) -> str:
    """Normalised item name, resolved through :data:`_ITEM_NAME_ALIASES`."""
    key = _norm_str(name)
    return _ITEM_NAME_ALIASES.get(key, key)


def load_price_list(path: str | Path) -> pd.DataFrame:
    """Return ``[key, cost_per_kg, grammage_per_serving]`` from the workbook.

    ``key`` is the normalised item name. Rows without a usable name are
    dropped, and a repeated name keeps its first occurrence so the join
    below can't fan out into duplicate menu rows.

    Raises:
        FileNotFoundError: when *path* doesn't exist.
        ValueError: when the sheet lacks an item, cost or grammage column
            — a price list missing any of the three can't be applied, and
            failing loudly beats silently importing nothing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Price list not found: {path}")

    try:
        raw = pd.read_excel(path, sheet_name=PRICE_SHEET_NAME)
    except ValueError:
        # Sheet renamed or absent — the first sheet is the usual layout.
        raw = pd.read_excel(path, sheet_name=0)

    item_col = pick_col(raw, _ITEM_ALIASES)
    cost_col = pick_col(raw, _COST_ALIASES)
    gram_col = pick_col(raw, _GRAM_ALIASES)
    missing = [
        name for name, col in (
            ("item", item_col), ("cost per KG", cost_col),
            ("grammage per serving", gram_col),
        ) if col is None
    ]
    if missing:
        raise ValueError(
            f"Price list {path.name} is missing column(s): "
            f"{', '.join(missing)}. Found: {list(raw.columns)[:8]}"
        )

    out = pd.DataFrame({
        "key": raw[item_col].map(_norm_str),
        "cost_per_kg": pd.to_numeric(raw[cost_col], errors="coerce"),
        "grammage_per_serving": pd.to_numeric(raw[gram_col], errors="coerce"),
    })
    out = out[out["key"] != ""]
    return out.drop_duplicates("key", keep="first").reset_index(drop=True)


def apply_price_list(
    df: pd.DataFrame, path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Overlay the price list's cost and serving weight onto *df*.

    A no-op when *path* is None or the file is absent — the ontology's
    cached values then stand, which is what a deployment without the
    Menu List should fall back to rather than losing costing entirely.

    Only cells the list actually has a number for are overwritten, so a
    blank in the list can't wipe a cached value.
    """
    if path is None:
        return df
    try:
        prices = load_price_list(path)
    except FileNotFoundError:
        logger.warning(
            "Price list %s not found; using the cost values cached in the "
            "ontology. Costs may be out of date.", path,
        )
        return df
    except ValueError as exc:
        logger.error("Price list unusable (%s); keeping cached costs.", exc)
        return df

    if "item" not in df.columns:
        return df

    keys = df["item"].map(_match_key)
    lookup = prices.set_index("key")
    matched = keys.isin(lookup.index)

    for column in ("cost_per_kg", "grammage_per_serving"):
        incoming = keys.map(lookup[column])
        if column not in df.columns:
            df[column] = incoming
        else:
            # Keep the cached value wherever the list has no number.
            df[column] = incoming.where(incoming.notna(), df[column])

    logger.info(
        "Applied price list %s: %d of %d items matched, %d unmatched "
        "(keeping their cached cost).",
        Path(path).name, int(matched.sum()), len(df), int((~matched).sum()),
    )
    if not matched.all():
        unmatched = df.loc[~matched, "item"].astype(str).head(5).tolist()
        logger.info("Unmatched examples: %s", ", ".join(unmatched))
    return df
