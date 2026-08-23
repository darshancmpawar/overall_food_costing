"""Plate weight rule: cap the total serving weight of one day's plate.

A plate is what one person is served on one day: every solver-chosen item
plus the constant accompaniments (papad, pickle, …). Without a ceiling
the solver has no reason to prefer a 120 g rice over a 300 g biryani in
every slot at once, and the plate drifts into portions no one eats — and
that nobody costed for.

CP-SAT phase rule. Weights are converted to whole grams because CP-SAT
works in integers; a kilogram is 1000 g, so nothing is lost.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ortools.sat.python import cp_model

from src.constants import BASE_SLOT_NAMES, MAX_PLATE_WEIGHT_KG
from .base_menu_rule import (
    BaseMenuRule,
    Diagnostic,
    DiagnosticPhase,
    DiagnosticSeverity,
    DiagnoseContext,
    MenuRuleType,
)

_GRAMS_PER_KG = 1000


def _grams(value) -> int:
    """Serving weight in whole grams. Unreadable or missing reads as 0.

    A row with no weight contributes nothing to the cap rather than
    failing the solve — the same forgiveness the cost lookup applies, so
    an ontology with partial weight data still plans.
    """
    try:
        grams = float(value) * _GRAMS_PER_KG
    except (TypeError, ValueError):
        return 0
    if grams != grams or grams < 0:  # NaN or negative
        return 0
    return int(round(grams))


def _pool_min_grams(pool) -> int:
    """Lightest serving in a pool, in grams (0 when nothing has a weight)."""
    if pool is None or len(pool) == 0 or 'grammage_per_serving' not in pool.columns:
        return 0
    weights = [g for g in (_grams(v) for v in pool['grammage_per_serving']) if g > 0]
    return min(weights) if weights else 0


def _pool_median_grams(pool) -> int:
    """Median serving in a pool, in grams (0 when nothing has a weight)."""
    if pool is None or len(pool) == 0 or 'grammage_per_serving' not in pool.columns:
        return 0
    weights = sorted(g for g in (_grams(v) for v in pool['grammage_per_serving']) if g > 0)
    if not weights:
        return 0
    return weights[len(weights) // 2]


class PlateWeightMenuRule(BaseMenuRule):
    """
    Config:
    {
        "type": "plate_weight",
        "name": "plate_max_1kg",
        "max_kg": 1.0
    }

    Hard by default: a plate over the cap is one the operation cannot
    actually serve, so silently dropping the constraint would produce a
    plan that looks fine and isn't.
    """

    def __init__(self, rule_config: Dict[str, Any]):
        super().__init__(rule_config)
        self.rule_type = MenuRuleType.PLATE_WEIGHT
        self.max_kg = float(rule_config.get('max_kg', MAX_PLATE_WEIGHT_KG))

    @property
    def max_grams(self) -> int:
        return int(round(self.max_kg * _GRAMS_PER_KG))

    def validate_config(self) -> bool:
        return not self._collect_errors()

    def validation_errors(self) -> List[str]:
        return self._collect_errors()

    def _collect_errors(self) -> List[str]:
        if self.max_kg <= 0:
            return [f"max_kg must be > 0 (got {self.max_kg})"]
        return []

    @staticmethod
    def _const_grams(context: Dict[str, Any]) -> int:
        """Weight of the constant accompaniments, from the solver config.

        The solver never models the constant slots — papad and pickle are
        stamped onto every day after the solve — but they are on the plate
        and they are in the "Qty / Plate" total the UI shows. Counting
        them keeps the cap and the displayed figure measuring the same
        thing; a cap that ignored them would let the visible total sit
        above the limit.
        """
        cfg = context.get('cfg')
        return int(getattr(cfg, 'const_slot_grams', 0) or 0)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        if not cells or not dates:
            return

        budget = self.max_grams - self._const_grams(context)
        if budget <= 0:
            raise ValueError(
                f"plate weight cap of {self.max_kg:.2f} kg leaves nothing for "
                f"the menu once the constant accompaniments "
                f"({self._const_grams(context)} g) are counted"
            )

        by_day: Dict[int, List] = {}
        for cell in cells:
            for var, row in zip(cell.x_vars, cell.cand_rows):
                grams = _grams(row.get('grammage_per_serving'))
                if grams:
                    by_day.setdefault(cell.d_idx, []).append(var * grams)

        for terms in by_day.values():
            if terms:
                model.Add(sum(terms) <= budget)

    def _themed_floor(self, ctx: DiagnoseContext, date, day_type: str,
                      base_slots, slot_counts):
        """Lightest plate buildable on one day, in grams, plus a breakdown.

        Projects the sibling rules' pre-filters first, because they are
        what makes a themed day heavy: the theme filter narrows a biryani
        Wednesday's rice pool to biryanis, whose lightest serving is
        300 g against 80 g unfiltered. Measuring the unfiltered pool
        would call a plan feasible that the solver then fails on — which
        is precisely the opaque failure this diagnostic exists to
        prevent.
        """
        filter_ctx = {
            'cfg': ctx.cfg,
            'banned_by_date': ctx.banned_by_date or {},
            'ricebread_ban_day': ctx.ricebread_ban_day or {},
            'pools': ctx.pools,
            'slot_num': None,
        }
        siblings = [r for r in (ctx.rules or []) if r is not self]

        total = int(getattr(ctx.cfg, 'const_slot_grams', 0) or 0)
        breakdown = []
        for base in base_slots:
            if (date, base) in (ctx.skip_cells or set()):
                continue
            pool = ctx.pools.get(base)
            if pool is None or len(pool) == 0:
                continue
            count = int(slot_counts.get(base, 1) or 1)
            if count <= 0:
                continue
            filtered = pool
            for rule in siblings:
                filtered = rule.pre_filter_pool(
                    filtered, date, base, day_type, filter_ctx,
                )
            lightest = _pool_min_grams(filtered if len(filtered) else pool)
            if not lightest:
                continue
            total += lightest * count
            breakdown.append((base, lightest * count))
        return total, breakdown

    def diagnose(self, ctx: DiagnoseContext) -> List[Diagnostic]:
        """Check the cap against the lightest plate each day can build.

        The lightest surviving item in every slot is a true lower bound —
        the solver cannot do better — so a bound above the cap is a
        guaranteed infeasibility, reported as an ERROR before the solver
        spends its budget. Reported per *theme* rather than per date:
        every biryani Wednesday in a plan fails for the same reason, and
        one message naming the theme is more useful than five naming
        dates.
        """
        diags: List[Diagnostic] = []
        base_slots = ctx.active_base_slots or list(BASE_SLOT_NAMES)
        slot_counts = (
            dict(getattr(ctx.client_cfg, 'slot_counts', {}) or {})
            if ctx.client_cfg is not None else {}
        )
        cap = self.max_grams

        seen_themes = {}
        for date in ctx.dates:
            day_type = ctx.day_types.get(date, '') or 'normal'
            if day_type in seen_themes:
                continue
            seen_themes[day_type] = (
                date, *self._themed_floor(ctx, date, day_type, base_slots, slot_counts)
            )

        for day_type, (date, floor, breakdown) in sorted(seen_themes.items()):
            if not breakdown or floor <= cap:
                continue
            heaviest = ", ".join(
                f"{b.replace('_', ' ')} {g} g"
                for b, g in sorted(breakdown, key=lambda x: -x[1])[:3]
            )
            over = floor - cap
            diags.append(Diagnostic(
                rule=self.name,
                rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.ERROR,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"{day_type.capitalize()} days can't meet the "
                    f"{cap} g plate cap: the lightest plate these "
                    f"{len(breakdown)} categories can build is {floor} g, "
                    f"{over} g over. Heaviest: {heaviest}."
                ),
                suggestion=(
                    f"Raise the cap to {(floor + 49) // 50 * 50} g, drop a "
                    f"category from this counter, or reduce the serving "
                    f"weight of the heaviest items above."
                ),
                affected={
                    'day_type': day_type,
                    'date': date.isoformat(),
                    'min_plate_grams': floor,
                    'max_plate_grams': cap,
                    'over_by_grams': over,
                    'const_slot_grams': int(
                        getattr(ctx.cfg, 'const_slot_grams', 0) or 0
                    ),
                    'heaviest': [
                        {'slot': b, 'grams': g}
                        for b, g in sorted(breakdown, key=lambda x: -x[1])[:5]
                    ],
                },
            ))
        return diags
