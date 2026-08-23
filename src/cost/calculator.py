"""
Per-item and per-day plate cost calculations.

Formula: cost_per_person = cost_per_kg * grammage_per_serving
Grammage is stored in kg (e.g. 0.06 = 60 g, 0.13 = 130 g).
"""

import math
from typing import Any, Callable, Dict, Optional

import pandas as pd

from .plate_adjust import trim_portions


def _fmt_qty(qty_kg: float) -> str:
    """Auto g/kg: grams when total < 1000 g, otherwise kg."""
    grams = qty_kg * 1000
    if grams < 1000:
        return f"{grams:.0f} g"
    return f"{qty_kg:.2f} kg"


def build_cost_lookup(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Return ``{normalised_item_name: {cost_per_kg, cost_per_person, grammage_kg}}``.

    ``cost_per_kg`` is carried through so a trimmed portion can be
    re-priced exactly, rather than scaled from a rounded per-person
    figure.

    Returns an empty dict when the required columns are absent so all
    downstream callers degrade gracefully without branching.
    """
    if "cost_per_kg" not in df.columns or "grammage_per_serving" not in df.columns:
        return {}

    lookup: Dict[str, Dict[str, float]] = {}
    for _, row in df.iterrows():
        item_name = str(row.get("item", "")).strip().lower()
        if not item_name:
            continue
        try:
            cpk = float(row["cost_per_kg"])
            gps = float(row["grammage_per_serving"])
        except (TypeError, ValueError):
            continue
        if math.isnan(cpk) or math.isnan(gps):
            continue
        lookup[item_name] = {
            "cost_per_kg": cpk,
            "cost_per_person": round(cpk * gps, 2),
            "grammage_kg": gps,
        }
    return lookup


def enrich_solution_with_costs(
    solution: Dict[str, Any],
    cost_lookup: Dict[str, Dict[str, float]],
    cap_fn: Optional[Callable[[str, int], Optional[int]]] = None,
) -> Dict[str, Any]:
    """Attach cost fields to every item and day-level totals.

    Adds to each item dict:
        cost_per_person        float | None
        cost_per_person_display  "₹12.50" | None
        grammage_kg            float | None
        grammage_display       "60 g" | None
        portion_trimmed_g      int    (only when this portion was reduced)

    Adds to each day dict:
        day_cost_total         float  (sum of all item costs)
        day_cost_display       "₹148.50"
        day_qty_total_kg       float  (sum of all grammages)
        day_qty_display        "850 g" | "1.15 kg"
        day_qty_cap_g          int | None  (the plate cap that applied)
        day_qty_trimmed_g      int    (grams removed to meet the cap)

    *cap_fn* takes ``(day_type, slot_count)`` and returns the plate's
    weight ceiling in grams, or ``None`` for uncapped. When given, a day
    over its ceiling has its portions trimmed by
    :func:`src.cost.plate_adjust.trim_portions` **before** costs are
    computed, so the money and the weights describe the same plate — the
    whole point of trimming is that you're serving (and paying for) less
    food. Omitting it leaves portions exactly as the ontology has them.

    When cost_lookup is empty (Excel has no cost columns), returns the
    solution unchanged so the UI just skips the cost footer rows.
    """
    if not cost_lookup:
        return solution

    enriched: Dict[str, Any] = {}
    for day_key, day_data in solution.items():
        items = day_data.get("items", {})

        # Portions as the ontology has them, in whole grams — the unit
        # the trimmer works in and the kitchen serves in.
        base_grams: Dict[str, int] = {}
        for slot_id, item_data in items.items():
            info = cost_lookup.get(
                item_data.get("item_base", "").strip().lower()
            )
            if info:
                base_grams[slot_id] = int(round(info["grammage_kg"] * 1000))

        cap = None
        trimmed_grams = dict(base_grams)
        removed = 0
        if cap_fn is not None and base_grams:
            cap = cap_fn(day_data.get("day_type", "") or "", len(items))
            trimmed_grams, removed = trim_portions(base_grams, cap)

        new_items: Dict[str, Any] = {}
        day_cost = 0.0
        day_qty = 0.0

        for slot_id, item_data in items.items():
            item_base = item_data.get("item_base", "").strip().lower()
            info = cost_lookup.get(item_base)
            new_item = dict(item_data)

            if info:
                grams = trimmed_grams.get(slot_id, base_grams.get(slot_id, 0))
                gkg = grams / 1000.0
                # Cost tracks the portion actually served, so a trimmed
                # plate costs less rather than being priced as if the
                # full portion went out. Priced from the per-kg rate so
                # the arithmetic doesn't compound a rounded figure.
                rate = info.get("cost_per_kg")
                if rate is None:
                    rate = (
                        info["cost_per_person"] / info["grammage_kg"]
                        if info.get("grammage_kg") else 0.0
                    )
                cpp = round(rate * gkg, 2)
                new_item["cost_per_person"] = cpp
                new_item["cost_per_person_display"] = f"₹{cpp:.2f}"
                new_item["grammage_kg"] = round(gkg, 4)
                new_item["grammage_display"] = _fmt_qty(gkg)
                cut = base_grams.get(slot_id, grams) - grams
                if cut > 0:
                    new_item["portion_trimmed_g"] = cut
                day_cost += cpp
                day_qty += gkg
            else:
                new_item["cost_per_person"] = None
                new_item["cost_per_person_display"] = None
                new_item["grammage_kg"] = None
                new_item["grammage_display"] = None

            new_items[slot_id] = new_item

        new_day = dict(day_data)
        new_day["items"] = new_items
        new_day["day_cost_total"] = round(day_cost, 2)
        new_day["day_cost_display"] = f"₹{day_cost:.2f}"
        new_day["day_qty_total_kg"] = round(day_qty, 4)
        new_day["day_qty_display"] = _fmt_qty(day_qty)
        new_day["day_qty_cap_g"] = cap
        new_day["day_qty_trimmed_g"] = removed
        enriched[day_key] = new_day

    return enriched
