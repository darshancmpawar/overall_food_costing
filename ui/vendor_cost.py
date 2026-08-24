"""
Vendor Cost tab.

Scales the average plate food cost up to a fully-loaded operating cost and
breaks it into lines — the vendor's operating costs and its profit. Those
lines total to the **buying price**: what SmartQ pays the vendor per plate.
What is left between that total and the overall cost is **SmartQ's
profit**, shown below the total and deliberately outside it.

The layout is three blocks, in the order the numbers are read:

1. **KPIs** — the four figures that summarise the tab.
2. **Cost build-up** — the editable lines, food first, ending in the
   buying-price total.
3. **Result** — SmartQ's profit and the checks on it.

Manpower is not typed in. It comes from a roster of roles (units x monthly
salary, in an expander on its own row) divided by 30 and then by the head
count — see ``src.cost.manpower``. Its share of the plate is therefore an
*output*, and it moves when the pax does: the same team costs more per
plate when it serves fewer covers.

Two-way sync for the rest, Streamlit-style: the percentage is the single
source of truth. Each editable line keeps a ``..._pct`` and a ``..._abs``
widget; their ``on_change`` callbacks convert one into the other and write
the partner widget's value *before* the rerun re-instantiates it (the
supported pattern). The overall cost is anchored by the food-cost share, so
editing a line's rupee amount moves that line's percentage while leaving
the overall total fixed.

Session-state keys are prefixed ``vc_``.
"""

import streamlit as st

from src.cost.manpower import (
    MANPOWER_ROLES,
    daily_wage_bill,
    monthly_wage_bill,
    per_plate_cost,
)
from src.cost.overall_cost import (
    DEFAULT_FOOD_COST_PCT,
    abs_to_pct,
    overall_food_cost,
    pct_to_abs,
)
from src.cost.vendor_cost import (
    DEFAULT_VENDOR_PROFIT_PCT,
    VENDOR_COST_LINES,
    buying_share_pct,
    margin_status,
    profit_status,
    smartq_margin_pct,
)
from ui import theme as t
from ui.cards import card_header, inject_card_css
from ui.kpi import kpi_grid, tone_for_amount

# The vendor's profit is edited exactly like an operating cost line, so it
# reuses the same two-way percentage/rupee machinery. Its key follows the
# same ``vc_<key>_pct`` / ``vc_<key>_abs`` convention.
_PROFIT_KEY = "profit"

# Column weights for the cost-line rows. One tuple so the header and every
# row line up without repeating the numbers.
_ROW = [2.4, 1.1, 1.4]


def _cols(weights=None):
    """``st.columns`` with centered vertical alignment when the installed
    Streamlit supports it (>=1.36), falling back gracefully otherwise."""
    weights = _ROW if weights is None else weights
    try:
        return st.columns(weights, vertical_alignment="center")
    except TypeError:
        return st.columns(weights)


def _current_overall() -> float:
    """Overall cost from the current session inputs — safe to call inside a
    widget callback, which runs before the script reruns."""
    ss = st.session_state
    return overall_food_cost(
        ss.get("vc_avg_food_cost", 0.0),
        ss.get("vc_food_cost_pct", DEFAULT_FOOD_COST_PCT),
    )


def _editable_keys():
    """Keys of every row whose percentage the user types — the operating
    lines plus the vendor's profit.

    Manpower is not among them: its rupee amount comes from the roster, so
    a change in the overall cost moves its *share*, not its amount.
    """
    return [key for key, _label, _default in VENDOR_COST_LINES] + [_PROFIT_KEY]


def _on_food_pct_change() -> None:
    # Food share moves the overall total, so every typed line's rupee
    # amount has to be re-derived from its (unchanged) percentage.
    overall = _current_overall()
    for key in _editable_keys():
        st.session_state[f"vc_{key}_abs"] = pct_to_abs(
            st.session_state[f"vc_{key}_pct"], overall
        )


def _on_pct_change(key: str) -> None:
    st.session_state[f"vc_{key}_abs"] = pct_to_abs(
        st.session_state[f"vc_{key}_pct"], _current_overall()
    )


def _on_abs_change(key: str) -> None:
    st.session_state[f"vc_{key}_pct"] = abs_to_pct(
        st.session_state[f"vc_{key}_abs"], _current_overall()
    )


def _seed_state(avg: float) -> None:
    """Seed the widget values once, and re-derive the rupee amounts whenever
    the average food cost changes (e.g. after a regenerate) so a stale amount
    never lingers next to a fresh percentage."""
    ss = st.session_state
    ss.vc_avg_food_cost = avg

    # Each key is seeded on its own rather than behind a single "have I
    # run?" flag: one value arriving from somewhere else (a restored
    # session, a caller pre-setting a share) would otherwise skip the rest
    # and leave the tab reading keys that were never written.
    ss.setdefault("vc_food_cost_pct", DEFAULT_FOOD_COST_PCT)
    for key, _label, default in VENDOR_COST_LINES:
        ss.setdefault(f"vc_{key}_pct", default)
    ss.setdefault(f"vc_{_PROFIT_KEY}_pct", DEFAULT_VENDOR_PROFIT_PCT)
    for key, _label, units, salary in MANPOWER_ROLES:
        ss.setdefault(f"vc_mp_{key}_units", units)
        ss.setdefault(f"vc_mp_{key}_salary", salary)
    for key in _editable_keys():
        ss.setdefault(
            f"vc_{key}_abs",
            pct_to_abs(ss[f"vc_{key}_pct"],
                       overall_food_cost(avg, ss.vc_food_cost_pct)),
        )

    if ss.get("vc_seed_avg") != avg:
        ss.vc_seed_avg = avg
        overall = overall_food_cost(avg, ss.vc_food_cost_pct)
        for key in _editable_keys():
            ss[f"vc_{key}_abs"] = pct_to_abs(ss[f"vc_{key}_pct"], overall)


def _roster():
    """Current roster as ``{key: (units, monthly_salary)}``."""
    ss = st.session_state
    return {
        key: (ss[f"vc_mp_{key}_units"], ss[f"vc_mp_{key}_salary"])
        for key, _label, _u, _s in MANPOWER_ROLES
    }


def _render_manpower_roster(pax: int) -> float:
    """The roster editor, on the Manpower row. Returns the per-plate cost.

    Rendered inside an expander so the row stays a single line until
    someone wants the detail, and closes with the three figures of the
    chain — monthly, per day, per plate — because the two divisions are
    where the number stops being obvious.
    """
    with st.expander("Team & salaries — units x monthly salary", expanded=False):
        head = _cols([1.6, 1.0, 1.3, 1.3])
        head[0].markdown("**Role**")
        head[1].markdown("**Units**")
        head[2].markdown("**Monthly salary (₹)**")
        head[3].markdown("**Monthly cost (₹)**")

        for key, label, _u, _s in MANPOWER_ROLES:
            row = _cols([1.6, 1.0, 1.3, 1.3])
            row[0].markdown(label)
            units = row[1].number_input(
                f"{label} units", key=f"vc_mp_{key}_units",
                min_value=0, step=1, label_visibility="collapsed",
            )
            salary = row[2].number_input(
                f"{label} monthly salary", key=f"vc_mp_{key}_salary",
                min_value=0.0, step=1000.0, format="%.1f",
                label_visibility="collapsed",
            )
            row[3].markdown(f"₹{units * salary:,.1f}")

        monthly = monthly_wage_bill(_roster())
        daily = daily_wage_bill(monthly)
        per_plate = per_plate_cost(daily, pax)

        st.divider()
        kpi_grid([
            ("Wage bill / month", f"₹{monthly:,.1f}", "units x salary",
             "neutral"),
            ("Per day", f"₹{daily:,.1f}", "÷ 30 days", "neutral"),
            ("Per plate", f"₹{per_plate:,.1f}", f"÷ {pax} pax/day", "cost"),
        ])
        st.caption(
            "Salaries are monthly, so the month is 30 days — staff are paid "
            "for the month, not for the days the cafeteria opens. The daily "
            f"bill is what the team costs the site; split across {pax} plates "
            "a day it becomes the per-plate figure on the Manpower row."
        )
    return per_plate


def _line_row(label: str, key: str, *, bold: bool = False) -> None:
    """One typed cost line: label, share %, rupee amount."""
    row = _cols()
    row[0].markdown(f"**{label}**" if bold else label)
    row[1].number_input(
        f"{label} share %", key=f"vc_{key}_pct",
        min_value=0.0, step=0.5, format="%.1f",
        label_visibility="collapsed",
        on_change=_on_pct_change, args=(key,),
    )
    row[2].number_input(
        f"{label} amount", key=f"vc_{key}_abs",
        min_value=0.0, step=1.0, format="%.1f",
        label_visibility="collapsed",
        on_change=_on_abs_change, args=(key,),
    )


def _total_row(label: str, pct: float, amount: float,
               colour: str = t.TEXT) -> None:
    """A bold summary row. *colour* tints the figures — used for SmartQ's
    profit, where a negative is the one number that must not read like
    every other one."""
    row = _cols()
    row[0].markdown(f"**{label}**")
    row[1].markdown(
        f"<span style='font-weight:700;color:{colour}'>{pct:.1f}%</span>",
        unsafe_allow_html=True,
    )
    row[2].markdown(
        f"<span style='font-weight:700;color:{colour}'>₹{amount:,.1f}</span>",
        unsafe_allow_html=True,
    )


def render_vendor_cost(avg: float, pax: int) -> None:
    """Render the Vendor Cost tab.

    *avg* is the average plate food cost from the generated plan; *pax* is
    the head count per day, which the manpower roster is divided by.
    """
    ss = st.session_state

    if avg <= 0:
        st.warning(
            "This plan has no food-cost data (the source sheet is missing the "
            "cost columns), so the overall cost can't be estimated."
        )
        return

    inject_card_css()
    _seed_state(avg)
    overall = overall_food_cost(avg, ss.vc_food_cost_pct)

    # --- KPIs ------------------------------------------------------------
    # Claimed before the build-up, filled after it: the buying price and
    # SmartQ's profit are only known once manpower has been costed.
    kpis = st.container()

    # --- Cost build-up ---------------------------------------------------
    with st.container(border=True):
        card_header(
            "Cost build-up — per plate",
            "Food cost is scaled up from its share to the fully-loaded "
            "overall cost, then allocated. Everything down to the total is "
            "money the vendor is paid.",
        )

        head = _cols()
        head[0].markdown("**Cost line**")
        head[1].markdown("**Share %**")
        head[2].markdown("**Amount (₹)**")

        # Food cost: the share is editable (it's the scaling anchor); the
        # rupee amount is fixed — it's the average plate cost the menu
        # actually produced.
        food = _cols()
        food[0].markdown("**Food Cost**")
        food[1].number_input(
            "Food cost share %", key="vc_food_cost_pct",
            min_value=1.0, max_value=100.0, step=1.0, format="%.1f",
            label_visibility="collapsed", on_change=_on_food_pct_change,
        )
        food[2].markdown(f"**₹{avg:,.1f}**")

        st.divider()

        # Manpower: computed from the roster, so both cells are read-only.
        # The row is claimed before the roster expander and filled after
        # it, so the line reads first and its detail opens underneath —
        # the same order as every other row on the tab.
        mp_row = st.container()
        manpower_abs = _render_manpower_roster(pax)
        manpower_pct = abs_to_pct(manpower_abs, overall)
        with mp_row:
            mp = _cols()
            mp[0].markdown(
                "Manpower &nbsp;<span class='status-pill info'>from roster"
                "</span>", unsafe_allow_html=True,
            )
            mp[1].markdown(f"{manpower_pct:.1f}%")
            mp[2].markdown(f"₹{manpower_abs:,.1f}")

        for key, label, _default in VENDOR_COST_LINES:
            _line_row(label, key)

        st.divider()

        # The vendor's profit: an input like the lines above it, not a
        # leftover. A vendor negotiates a margin; it doesn't accept
        # whatever happens to remain.
        _line_row("Vendor Profit", _PROFIT_KEY, bold=True)

        vendor_pcts = {
            key: ss[f"vc_{key}_pct"] for key, _l, _d in VENDOR_COST_LINES
        }
        vendor_pcts["manpower"] = manpower_pct
        vendor_profit = ss[f"vc_{_PROFIT_KEY}_pct"]
        buying_pct = buying_share_pct(
            ss.vc_food_cost_pct, vendor_pcts, vendor_profit,
        )
        buying_abs = pct_to_abs(buying_pct, overall)
        margin_pct = smartq_margin_pct(
            ss.vc_food_cost_pct, vendor_pcts, vendor_profit,
        )
        margin_abs = pct_to_abs(margin_pct, overall)

        _total_row("Total — Buying Price / plate", buying_pct, buying_abs)

    # Published for the SmartQ tab: it buys at this price and turns the
    # margin into money over the period.
    ss.vc_buying_price = buying_abs
    ss.vc_smartq_margin_pct = margin_pct
    ss.vc_manpower_per_plate = manpower_abs

    # --- Result ----------------------------------------------------------
    with st.container(border=True):
        card_header(
            "Result — what SmartQ keeps",
            "Whatever the vendor isn't paid. A margin, not a cost, so it "
            "sits outside the total above and is added to profit in SmartQ "
            "Costing.",
        )
        _total_row(
            "SmartQ Profit / plate", margin_pct, margin_abs,
            colour=t.SUCCESS_FG if margin_abs > 0 else (
                t.ERROR_FG if margin_abs < 0 else t.TEXT
            ),
        )
        ref = _cols()
        ref[0].caption("Overall Cost / plate")
        ref[1].caption("100.0%")
        ref[2].caption(f"₹{overall:,.1f}")

        # Two things can be wrong here, and they're different problems: the
        # inputs can over-allocate the plate (arithmetic), or the vendor's
        # margin can be unrealistic (judgement). Show the first always, the
        # second only when it needs saying.
        status = margin_status(margin_pct)
        {"error": st.error, "warning": st.warning, "ok": st.success}[
            status.level
        ](status.message)
        profit_verdict = profit_status(vendor_profit)
        if profit_verdict.level != "ok":
            {"error": st.error, "warning": st.warning}[profit_verdict.level](
                profit_verdict.message
            )

    with kpis:
        kpi_grid([
            ("Avg Food Cost / plate", f"₹{avg:,.1f}",
             "from the generated plan", "neutral"),
            ("Overall Cost / plate", f"₹{overall:,.1f}",
             f"food at {ss.vc_food_cost_pct:.1f}%", "neutral"),
            ("Buying Price / plate", f"₹{buying_abs:,.1f}",
             f"{buying_pct:.1f}% — paid to the vendor", "cost"),
            ("SmartQ Profit / plate", f"₹{margin_abs:,.1f}",
             f"{margin_pct:.1f}% of the plate", tone_for_amount(margin_abs)),
        ])
