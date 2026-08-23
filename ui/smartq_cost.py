"""
SmartQ Costing tab.

Scales the overall cost per plate (from the vendor model) up to period totals
via the working days and pax/day, then breaks the operating cost into editable
lines — each a share of the selling amount — and sums them into the SmartQ
cost. The arithmetic lives in ``src.cost.smartq_cost``; this module renders it
and wires up the two-way percentage <-> rupee inputs (same pattern as the
vendor tab: percentage is the source of truth, callbacks keep the partner
field in sync, and a changed selling amount re-derives every rupee value).

The selling price is set either way round — as a markup over the overall
cost, or as a price per plate — because a deal is often discussed as a
round number per head rather than as a percentage. The two inputs are one
number with two faces, kept in step by the same callback pattern.

Profit also picks up SmartQ's share of the plate from the vendor tab
(``vc_smartq_share_pct``): the part of the buying price the vendor doesn't
need. It is a margin, so it is credited to profit rather than netted off
the cost lines.

Session-state keys are prefixed ``sq_``.
"""

import streamlit as st

from src.cost.smartq_cost import (
    DEFAULT_SELLING_MARKUP_PCT,
    MIN_MARKUP_PCT,
    DEFAULT_SELLING_PAX,
    DEFAULT_WORKING_DAYS,
    SMARTQ_COST_LINES,
    buying_amount,
    line_abs,
    line_pct,
    markup_pct_from_price,
    selling_amount,
    selling_price,
    smartq_cost,
    smartq_profit,
    smartq_profit_pct,
)
from src.cost.vendor_cost import share_amount
from ui import theme


def _cols(weights):
    """``st.columns`` with centered vertical alignment when supported."""
    try:
        return st.columns(weights, vertical_alignment="center")
    except TypeError:
        return st.columns(weights)


def _cadence_badge(cadence: str) -> str:
    """Small pill marking a line as monthly or yearly."""
    if cadence == "yearly":
        bg, fg = theme.WARNING_BG, theme.WARNING_FG
    else:
        bg, fg = theme.SUCCESS_BG, theme.SUCCESS_FG
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:99px;'
        f'font-size:0.62rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.04em;background:{bg};color:{fg};">{cadence}</span>'
    )


def _current_selling_price() -> float:
    """Selling price per plate implied by the markup currently in session."""
    ss = st.session_state
    return selling_price(
        ss.get("sq_overall_per_plate", 0.0),
        ss.get("sq_markup_pct", DEFAULT_SELLING_MARKUP_PCT),
    )


def _current_selling_amount() -> float:
    """Selling amount from the current session inputs — safe to call inside a
    widget callback, which runs before the script reruns."""
    ss = st.session_state
    pax = ss.get("sq_selling_pax", DEFAULT_SELLING_PAX)
    days = ss.get("sq_working_days", DEFAULT_WORKING_DAYS)
    return selling_amount(_current_selling_price(), pax, days)


def _on_markup_change() -> None:
    """Markup edited: re-derive the price per plate."""
    st.session_state.sq_selling_price = round(_current_selling_price(), 2)


def _on_price_change() -> None:
    """Price per plate edited: back out the markup it implies."""
    ss = st.session_state
    ss.sq_markup_pct = markup_pct_from_price(
        ss.sq_selling_price, ss.get("sq_overall_per_plate", 0.0),
    )


def _on_pct_change(key: str, divisor: int) -> None:
    st.session_state[f"sq_{key}_abs"] = line_abs(
        st.session_state[f"sq_{key}_pct"], _current_selling_amount(), divisor
    )


def _on_abs_change(key: str, divisor: int) -> None:
    st.session_state[f"sq_{key}_pct"] = line_pct(
        st.session_state[f"sq_{key}_abs"], _current_selling_amount(), divisor
    )


def _seed_state(overall_per_plate: float) -> None:
    """Seed the inputs and line shares once, then re-derive every rupee amount
    whenever the selling amount changes (overall cost, pax, or days), so a
    stale amount never lingers next to a fresh percentage."""
    ss = st.session_state
    ss.sq_overall_per_plate = overall_per_plate

    if "sq_working_days" not in ss:
        ss.sq_working_days = DEFAULT_WORKING_DAYS
        ss.sq_selling_pax = DEFAULT_SELLING_PAX
        ss.sq_markup_pct = DEFAULT_SELLING_MARKUP_PCT
        for key, _label, default, _cadence, _divisor in SMARTQ_COST_LINES:
            ss[f"sq_{key}_pct"] = default

    # The overall cost moves whenever the vendor tab's food share does, so
    # the price is re-derived from the (unchanged) markup — the markup is
    # the anchor, the price is the view of it.
    if ss.get("sq_seed_overall") != overall_per_plate:
        ss.sq_seed_overall = overall_per_plate
        ss.sq_selling_price = round(_current_selling_price(), 2)

    sell_amt = _current_selling_amount()
    if ss.get("sq_seed_selling_amount") != sell_amt:
        ss.sq_seed_selling_amount = sell_amt
        for key, _label, _default, _cadence, divisor in SMARTQ_COST_LINES:
            ss[f"sq_{key}_abs"] = line_abs(ss[f"sq_{key}_pct"], sell_amt, divisor)


def render_smartq_cost(overall_per_plate: float) -> None:
    """Render the SmartQ Costing tab for an overall cost per plate."""
    ss = st.session_state

    if overall_per_plate <= 0:
        st.warning(
            "This plan has no food-cost data, so the overall cost — and the "
            "SmartQ costing built on it — can't be estimated."
        )
        return

    _seed_state(overall_per_plate)

    st.caption(
        "Set the selling price either as a markup over the overall cost per "
        "plate or as the price itself — the two stay in step. Working days "
        "and pax/day scale it to period totals; each operating line below is "
        "a share of the selling amount."
    )

    in1, in2, in3, in4 = st.columns(4)
    in1.number_input(
        "Markup %", key="sq_markup_pct",
        min_value=MIN_MARKUP_PCT, step=1.0, format="%.2f",
        on_change=_on_markup_change,
        help="Percentage above the overall cost per plate. Negative means "
             "the plate sells for less than it costs.",
    )
    in2.number_input(
        "Selling price / plate", key="sq_selling_price",
        min_value=0.0, step=1.0, format="%.2f",
        on_change=_on_price_change,
        help="Set a round price per head and the markup follows.",
    )
    in3.number_input("Working days", key="sq_working_days", min_value=1, step=1)
    in4.number_input("Selling Pax / day", key="sq_selling_pax", min_value=1, step=1)

    sell_price = _current_selling_price()

    pax = ss.sq_selling_pax
    days = ss.sq_working_days
    buy_amt = buying_amount(overall_per_plate, pax, days)
    sell_amt = selling_amount(sell_price, pax, days)

    # A price under the overall cost is allowed — bids happen — but it must
    # not pass unremarked, because every figure below it is then a loss.
    # A paisa of rounding in the displayed price is not a loss, so compare
    # with a one-paisa tolerance.
    if sell_price < overall_per_plate - 0.01:
        st.warning(
            f"₹{sell_price:,.2f} per plate is below the overall cost of "
            f"₹{overall_per_plate:,.2f} — this plan sells at a loss."
        )

    m1, m2, m3 = st.columns(3)
    m1.metric("Selling Price / plate", f"₹{sell_price:,.2f}")
    m2.metric("Buying Amt", f"₹{buy_amt:,.2f}")
    m3.metric("Selling Amount", f"₹{sell_amt:,.2f}")

    st.divider()

    head = _cols([2.2, 1.0, 1.3, 0.9])
    head[0].markdown("**Cost line**")
    head[1].markdown("**Share %**")
    head[2].markdown("**Amount (₹)**")
    head[3].markdown("**Cadence**")

    for key, label, _default, cadence, divisor in SMARTQ_COST_LINES:
        row = _cols([2.2, 1.0, 1.3, 0.9])
        row[0].markdown(label)
        row[1].number_input(
            f"{label} share %", key=f"sq_{key}_pct",
            min_value=0.0, step=0.5, format="%.2f",
            label_visibility="collapsed",
            on_change=_on_pct_change, args=(key, divisor),
        )
        row[2].number_input(
            f"{label} amount", key=f"sq_{key}_abs",
            min_value=0.0, step=1.0, format="%.2f",
            label_visibility="collapsed",
            on_change=_on_abs_change, args=(key, divisor),
        )
        row[3].markdown(_cadence_badge(cadence), unsafe_allow_html=True)

    total = smartq_cost(
        ss[f"sq_{key}_abs"] for key, _l, _d, _c, _dv in SMARTQ_COST_LINES
    )
    # SmartQ's share of the plate, set in the vendor tab as the remainder
    # once the vendor's costs and profit are accounted for. A margin, not
    # a cost — so it is credited to profit.
    share_pct = ss.get("vc_smartq_share_pct", 0.0)
    vendor_share = share_amount(share_pct, overall_per_plate, pax, days)
    profit = smartq_profit(sell_amt, buy_amt, total, vendor_share)
    profit_margin = smartq_profit_pct(profit, sell_amt)

    st.divider()
    out1, out2, out3 = st.columns(3)
    out1.metric("SmartQ Cost", f"₹{total:,.2f}",
                help="Sum of every operating line above (monthly basis; the "
                     "yearly Food Licenses line is included at 1/12).")
    out2.metric("Vendor Share Credit", f"₹{vendor_share:,.2f}",
                delta=f"{share_pct:.2f}% of the plate", delta_color="off",
                help="The part of the buying price the vendor doesn't need, "
                     "set in the Vendor Cost tab. Added to profit, not to "
                     "cost.")
    out3.metric("SmartQ Profit", f"₹{profit:,.2f}", delta=f"{profit_margin:.2f}%",
                help="Selling amount − buying amount − SmartQ cost + vendor "
                     "share; the delta is profit as a % of the selling "
                     "amount.")
