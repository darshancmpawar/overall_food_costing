"""Trim a plate's portions down to its weight cap.

The solver's first job is to build a plate that fits its cap by choosing
lighter items — see ``src.menu_rules.plate_weight_rule``. On some days no
combination fits: a biryani Wednesday starts at a 300 g rice plus a 300 g
non-veg biryani, and there is no lighter biryani to pick. Rather than
refuse to plan the day, the portions themselves come down.

How the trim is shaped, and why:

* **In steps of 5 g.** A kitchen works to round numbers; 218 g of rice is
  not a portion anyone can serve.
* **Off the heaviest portion each time.** Taking from the biggest is what
  makes the result balanced: two 300 g items shed weight together and
  stay level, instead of one being gutted while the other is untouched.
* **No portion loses more than a quarter of itself.** A trim is meant to
  be slight, and this forces it to spread across several items rather
  than concentrating on one.
* **No portion reaches zero.** A slot with nothing in it isn't a smaller
  portion, it's a missing course.

Pure module — no Streamlit, no I/O, no pandas — so the arithmetic is
unit-testable on plain dicts. ``src.cost.calculator`` applies it while
enriching a solution, so the costs and the displayed weights both reflect
the trimmed plate.
"""

from __future__ import annotations

import math
from typing import Dict, Mapping, Optional, Tuple

from src.constants import PLATE_TRIM_MAX_CUT_FRACTION, PLATE_TRIM_STEP_GRAMS


def _floor_for(grams: int, step: int, max_cut_fraction: float) -> int:
    """Smallest weight a portion may be trimmed to.

    Rounded *up* to a step so the floor is itself servable, and never
    below one step, so nothing can reach zero. A portion already at or
    under a single step has no room and is returned unchanged.
    """
    if grams <= step:
        return grams
    keep = grams * (1.0 - max_cut_fraction)
    floored = int(math.ceil(keep / step)) * step
    return max(step, min(grams, floored))


def trim_portions(
    portions: Mapping[str, int],
    cap: Optional[int],
    *,
    step: int = PLATE_TRIM_STEP_GRAMS,
    max_cut_fraction: float = PLATE_TRIM_MAX_CUT_FRACTION,
) -> Tuple[Dict[str, int], int]:
    """Bring ``sum(portions)`` down to *cap*, in grams.

    Returns ``(trimmed, grams_removed)``. The input is returned untouched
    when *cap* is ``None`` (uncapped plate) or already met.

    When the cap cannot be reached without breaking one of the rules
    above, as much as the rules allow is trimmed and the shortfall is
    left visible in the total rather than silently forcing a portion
    below its floor — an unservable plan is worse than a heavy one, and
    the caller can surface the difference.
    """
    current = {k: int(v) for k, v in portions.items() if int(v) > 0}
    total = sum(current.values())
    if cap is None or total <= cap:
        return dict(portions), 0

    floors = {
        slot: _floor_for(grams, step, max_cut_fraction)
        for slot, grams in current.items()
    }

    removed = 0
    while total - removed > cap:
        # Heaviest portion with room left. Ties break on slot name so the
        # same plate always trims the same way.
        candidates = [
            slot for slot, grams in current.items()
            if grams - step >= floors[slot]
        ]
        if not candidates:
            break
        slot = max(candidates, key=lambda s: (current[s], s))
        current[slot] -= step
        removed += step

    trimmed = dict(portions)
    trimmed.update(current)
    return trimmed, removed
