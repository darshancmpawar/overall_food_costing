"""
Pool builder: maps normalized DataFrame rows into per-slot item pools.

Each pool is a DataFrame containing only the items eligible for that slot.
Handles sambar/rasam splitting, welcome_drink mapping, combined slots
(dal_sambar / sambar_rasam), per-client source-pool scoping, and slot
expansion.
"""

import logging
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd

from .column_mapper import _norm_str
from src.constants import (
    SLOT_SUFFIX_SEP, COMBINED_SLOT_SOURCES, REQUIRED_POOL_SLOTS,
)

logger = logging.getLogger(__name__)

# course_type -> slot mapping for simple 1:1 cases
_SIMPLE_MAPPING: Dict[str, Set[str]] = {
    'welcome_drink': {'welcome_drink', 'infused_water'},
    'soup': {'soup'},
    'salad': {'salad'},
    'starter': {'starter'},
    'bread': {'bread'},
    'rice': {'rice'},
    'healthy_rice': {'healthy_rice', 'healthy rice', 'healthy-rice'},
    'dal': {'dal'},
    'veg_gravy': {'veg_gravy'},
    'veg_dry': {'veg_dry'},
    'nonveg_main': {'nonveg_main'},
    'curd_side': {'curd_side'},
    'dessert': {'dessert'},
}

# Pool values that every client can draw from regardless of the
# ``source_pools`` it declares — the shared/base ontology.
SHARED_SOURCE_POOL_VALUES: Set[str] = {
    '', 'common', 'shared', 'default', 'base', 'all', 'core',
}


# ---------------------------------------------------------------------------
# Slot helpers
# ---------------------------------------------------------------------------

def _base_slot(slot_id: str) -> str:
    s = _norm_str(slot_id)
    if SLOT_SUFFIX_SEP in s:
        left, right = s.rsplit(SLOT_SUFFIX_SEP, 1)
        if right.isdigit():
            return left
    return s


def _slot_num(slot_id: str) -> Optional[int]:
    s = _norm_str(slot_id)
    if SLOT_SUFFIX_SEP in s:
        _, right = s.rsplit(SLOT_SUFFIX_SEP, 1)
        if right.isdigit():
            return int(right)
    return None


def _expand_slots_in_order(base_slots: List[str], slot_counts: Dict[str, int]) -> List[str]:
    """Expand base slot names into numbered instances based on slot_counts."""
    out: List[str] = []
    for s in base_slots:
        n = int(slot_counts.get(s, 1))
        if n <= 0:
            continue
        if n == 1:
            out.append(s)
        else:
            out.extend(f'{s}{SLOT_SUFFIX_SEP}{i}' for i in range(1, n + 1))
    return out


# ---------------------------------------------------------------------------
# PoolBuilder
# ---------------------------------------------------------------------------

def scope_to_source_pools(
    df: pd.DataFrame, source_pools: Optional[Iterable[str]],
) -> pd.DataFrame:
    """Return *df* limited to the shared ontology plus *source_pools*.

    ``clients.source_pools`` names the extra item collections a client is
    allowed to draw from (a site-specific menu book, a co-branded vendor
    list). Items carry their collection in the ``source_pool`` column;
    rows with no value — or one of :data:`SHARED_SOURCE_POOL_VALUES` —
    belong to the shared ontology and are always in scope.

    An ontology without a ``source_pool`` column is treated as entirely
    shared: filtering is skipped and the full frame is returned. That is
    the safe direction — the alternative (empty pools for every client
    that declares a source pool) would take the planner down the moment
    someone sets the field.
    """
    wanted = {
        _norm_str(p) for p in (source_pools or []) if _norm_str(p)
    }
    if 'source_pool' not in df.columns:
        if wanted:
            logger.info(
                "Client declares source_pools %s but the ontology has no "
                "source_pool column; using the full item set.",
                sorted(wanted),
            )
        return df
    col = df['source_pool'].map(_norm_str)
    keep = col.isin(SHARED_SOURCE_POOL_VALUES) | col.isin(wanted)
    scoped = df[keep]
    logger.info(
        "Scoped ontology to source_pools %s: %d of %d items in play.",
        sorted(wanted) or ['<shared only>'], len(scoped), len(df),
    )
    return scoped


class PoolBuilder:
    """
    Builds per-slot item pools from a normalized DataFrame.

    Usage:
        pools = PoolBuilder.build_pools(df)
        pools = PoolBuilder.build_pools(df, source_pools=['amadeus'])
    """

    @staticmethod
    def build_pools(
        df: pd.DataFrame,
        source_pools: Optional[Iterable[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Build pools dict mapping each base slot name to the eligible items.

        Handles sambar/rasam splitting where course_type='sambar/rasam' is
        split by item name containing 'rasam', the plain-curd and
        curd-rice slots, and the combined dal_sambar / sambar_rasam
        lines.

        *source_pools* scopes the ontology to a client's declared item
        collections before any slot mapping happens — see
        :func:`scope_to_source_pools`.
        """
        df = scope_to_source_pools(df, source_pools)
        pools: Dict[str, pd.DataFrame] = {}

        # Simple 1:1 course_type -> slot mappings
        for slot, course_types in _SIMPLE_MAPPING.items():
            pools[slot] = df[df['course_type'].isin(course_types)].copy()

        # Special handling: sambar/rasam split
        is_rasam_text = df['item'].str.contains('rasam', na=False)
        pools['rasam'] = df[
            (df['course_type'] == 'rasam') |
            ((df['course_type'] == 'sambar/rasam') & is_rasam_text)
        ].copy()
        pools['sambar'] = df[
            (df['course_type'] == 'sambar') |
            ((df['course_type'] == 'sambar/rasam') & ~is_rasam_text)
        ].copy()

        # Plain curd — a dedicated serving line for clients that list
        # "curd" separately from the raita-style "curd_side".
        curd_side = pools.get('curd_side')
        if curd_side is not None and 'is_plain_curd' in curd_side.columns:
            pools['curd'] = curd_side[curd_side['is_plain_curd'] == 1].copy()
        else:
            pools['curd'] = df[df['item'] == 'curd'].copy()

        # Curd rice — carved out of the flavoured-rice pool by flag.
        rice = pools.get('rice')
        if rice is not None and 'is_curd_rice' in rice.columns:
            pools['curd_rice'] = rice[rice['is_curd_rice'] == 1].copy()
        else:
            pools['curd_rice'] = rice.iloc[0:0].copy() if rice is not None else df.iloc[0:0].copy()

        # Combined lines draw from the union of their source pools.
        for slot, sources in COMBINED_SLOT_SOURCES.items():
            frames = [pools[s] for s in sources if s in pools and len(pools[s])]
            if frames:
                pools[slot] = (
                    pd.concat(frames, ignore_index=False)
                    .drop_duplicates(subset='item')
                    .copy()
                )
            else:
                pools[slot] = df.iloc[0:0].copy()

        # Slots every client needs must be non-empty; the rest are opt-in
        # per counter, so a thin ontology only earns a warning.
        for slot in REQUIRED_POOL_SLOTS:
            if slot not in pools or len(pools[slot]) == 0:
                raise ValueError(f"Slot '{slot}' has 0 items after mapping.")
        for slot in pools:
            if slot not in REQUIRED_POOL_SLOTS and len(pools[slot]) == 0:
                logger.warning(
                    "Slot '%s' has 0 items after mapping; counters that use "
                    "it will fail pre-flight diagnostics.", slot,
                )

        return pools
