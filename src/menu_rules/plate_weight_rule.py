"""Plate weight rule: cap the total serving weight of one day's plate.

A plate is what one person is served on one day: every solver-chosen item
plus the constant accompaniments (papad, pickle, …). Without a ceiling
the solver has no reason to prefer a 120 g rice over a 300 g biryani in
every slot at once, and the plate drifts into portions no one eats — and
that nobody costed for.

The cap is per day and comes from :func:`src.constants.plate_cap_grams`:
1000 g normally, 1100 g on a biryani day (a 300 g rice plus a 300 g
non-veg biryani is genuinely a heavier meal), and no cap at all once a
plate carries more than fifteen items.

Where the cap is reachable the constraint does the work — the solver
builds a plate that fits while obeying every other rule. Where it isn't,
the day is left unconstrained and its portions are trimmed instead, by
:func:`src.cost.plate_adjust.trim_portions`. That split matters: forcing
the constraint on an unreachable day would fail the whole plan, and
trimming a day that could have fitted would shrink portions for no
reason.

CP-SAT phase rule. Weights are converted to whole grams because CP-SAT
works in integers; a kilogram is 1000 g, so nothing is lost.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ortools.sat.python import cp_model

from src.constants import BASE_SLOT_NAMES, plate_cap_grams
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
        # An explicit max_kg overrides the whole policy — same ceiling on
        # every day, however many slots. Left unset, per-day caps come
        # from src.constants.plate_cap_grams.
        self.max_kg = (
            float(rule_config['max_kg']) if rule_config.get('max_kg') is not None
            else None
        )

    @property
    def max_grams(self) -> Optional[int]:
        """The override cap in grams, or None when the policy applies."""
        if self.max_kg is None:
            return None
        return int(round(self.max_kg * _GRAMS_PER_KG))

    def cap_for(self, day_type: str, slot_count: int) -> Optional[int]:
        """Cap in grams for one plate — the override if set, else policy."""
        if self.max_kg is not None:
            return self.max_grams
        return plate_cap_grams(day_type, slot_count)

    def validate_config(self) -> bool:
        return not self._collect_errors()

    def validation_errors(self) -> List[str]:
        return self._collect_errors()

    def _collect_errors(self) -> List[str]:
        if self.max_kg is not None and self.max_kg <= 0:
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

    @staticmethod
    def _const_slot_count(context: Dict[str, Any]) -> int:
        """How many constant slots this counter serves.

        They count towards the "more than fifteen items" exemption
        because they are items on the plate, even though the solver
        never chooses them.
        """
        cfg = context.get('cfg')
        return int(getattr(cfg, 'const_slot_count', 0) or 0)

    def apply(self, model: cp_model.CpModel, variables: Dict[str, Any],
              menu_data: Any, context: Dict[str, Any]) -> None:
        """Constrain each day's plate, but only where the cap is reachable.

        The lightest candidate in every cell is the lightest plate the
        solver could possibly build that day. If that already exceeds the
        cap, constraining the day would make the whole plan infeasible —
        so the day is skipped and left to portion trimming. Nothing is
        ever blocked by this rule.
        """
        cells = context.get('cells', [])
        dates = context.get('dates', [])
        day_types = context.get('day_types', [])
        if not cells or not dates:
            return

        const_grams = self._const_grams(context)
        const_slot_count = self._const_slot_count(context)

        per_day: Dict[int, List] = {}
        lightest: Dict[int, int] = {}
        cell_count: Dict[int, int] = {}
        for cell in cells:
            options = []
            for var, row in zip(cell.x_vars, cell.cand_rows):
                grams = _grams(row.get('grammage_per_serving'))
                if grams:
                    options.append((var, grams))
            cell_count[cell.d_idx] = cell_count.get(cell.d_idx, 0) + 1
            if not options:
                continue
            per_day.setdefault(cell.d_idx, []).extend(
                var * grams for var, grams in options
            )
            lightest[cell.d_idx] = lightest.get(cell.d_idx, 0) + min(
                g for _v, g in options
            )

        for d_idx, terms in per_day.items():
            day_type = (
                day_types[d_idx] if d_idx < len(day_types) else ''
            )
            slot_count = cell_count.get(d_idx, 0) + const_slot_count
            cap = self.cap_for(day_type or '', slot_count)
            if cap is None:
                continue
            budget = cap - const_grams
            # Unreachable: leave the day alone so trimming can handle it.
            if budget <= 0 or lightest.get(d_idx, 0) > budget:
                continue
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
        """Report which themes will need their portions trimmed.

        Nothing here blocks a plan: a day the solver can't fit under its
        cap has its portions trimmed instead, so the worst case is
        smaller servings rather than no menu. What the operator needs to
        know is *which* days that happens on and by how much, since it
        changes both the plate and its cost.

        Measured after projecting the other rules' pre-filters, because
        those are what make a themed day heavy — unfiltered, a rice pool
        starts at 80 g, but the theme filter narrows a biryani Wednesday
        to biryanis starting at 300 g.
        """
        diags: List[Diagnostic] = []
        base_slots = ctx.active_base_slots or list(BASE_SLOT_NAMES)
        slot_counts = (
            dict(getattr(ctx.client_cfg, 'slot_counts', {}) or {})
            if ctx.client_cfg is not None else {}
        )
        const_slots = int(getattr(ctx.cfg, 'const_slot_count', 0) or 0)

        seen = {}
        for date in ctx.dates:
            day_type = ctx.day_types.get(date, '') or 'normal'
            if day_type in seen:
                continue
            floor, breakdown = self._themed_floor(
                ctx, date, day_type, base_slots, slot_counts,
            )
            seen[day_type] = (date, floor, breakdown)

        for day_type, (date, floor, breakdown) in sorted(seen.items()):
            if not breakdown:
                continue
            served = sum(
                int(slot_counts.get(b, 1) or 1) for b, _g in breakdown
            ) + const_slots
            cap = self.cap_for(day_type, served)
            if cap is None or floor <= cap:
                continue
            heaviest = ", ".join(
                f"{b.replace('_', ' ')} {g} g"
                for b, g in sorted(breakdown, key=lambda x: -x[1])[:3]
            )
            over = floor - cap
            diags.append(Diagnostic(
                rule=self.name,
                rule_type=self.rule_type.value,
                severity=DiagnosticSeverity.WARNING,
                phase=DiagnosticPhase.APPLY,
                message=(
                    f"{day_type.capitalize()} days can't fit the {cap} g "
                    f"plate cap by choosing lighter items — the lightest "
                    f"plate is {floor} g — so about {over} g will be "
                    f"trimmed from the largest portions "
                    f"(5 g at a time, no portion losing more than a "
                    f"quarter). Heaviest: {heaviest}."
                ),
                suggestion=(
                    "No action needed — the plan and its costs reflect the "
                    "trimmed portions. Drop a category or raise the cap for "
                    "this theme if you would rather keep full portions."
                ),
                affected={
                    'day_type': day_type,
                    'date': date.isoformat(),
                    'min_plate_grams': floor,
                    'max_plate_grams': cap,
                    'over_by_grams': over,
                    'slots_on_plate': served,
                    'heaviest': [
                        {'slot': b, 'grams': g}
                        for b, g in sorted(breakdown, key=lambda x: -x[1])[:5]
                    ],
                },
            ))
        return diags
