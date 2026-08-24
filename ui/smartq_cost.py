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

The plates are bought at the **buying price** the vendor tab publishes
(``vc_buying_price``) — the vendor's lines and profit — not at the full
overall cost. The gap between the two is SmartQ's margin
(``vc_smartq_margin_pct``), shown here as **Extra Margin** over the
period and added to profit as revenue.

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
from src.cost.vendor_cost import extra_margin_amount
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
        "plate or as the price itself — the two stay in step. Plates are "
        "bought at the vendor's buying price, not the full overall cost. "
        "Working days and pax/day scale both to period totals. The result "
        "is at the top; each operating line further down is a share of the "
        "selling amount."
    )

    in1, in2, in3, in4 = st.columns(4)
    in1.number_input(
        "Markup %", key="sq_markup_pct",
        min_value=MIN_MARKUP_PCT, step=1.0, format="%.1f",
        on_change=_on_markup_change,
        help="Percentage above the overall cost per plate. Negative means "
             "the plate sells for less than it costs.",
    )
    in2.number_input(
        "Selling price / plate", key="sq_selling_price",
        min_value=0.0, step=1.0, format="%.1f",
        on_change=_on_price_change,
        help="Set a round price per head and the markup follows.",
    )
    in3.number_input("Working days", key="sq_working_days", min_value=1, step=1)
    in4.number_input("Selling Pax / day", key="sq_selling_pax", min_value=1, step=1)

    sell_price = _current_selling_price()

    pax = ss.sq_selling_pax
    days = ss.sq_working_days
    # The vendor tab publishes what the vendor is actually paid. Falling
    # back to the overall cost keeps this tab finite if it is ever
    # rendered on its own, in which case SmartQ's margin is zero.
    buy_price = ss.get("vc_buying_price", overall_per_plate)
    buy_amt = buying_amount(buy_price, pax, days)
    sell_amt = selling_amount(sell_price, pax, days)

    # A price under cost is allowed — bids happen — but it must not pass
    # unremarked. There are two thresholds now and they mean different
    # things: under the buying price the plate loses money outright; between
    # that and the overall cost it pays the vendor but not the full loaded
    # cost. A paisa of display rounding is neither, hence the tolerance.
    if sell_price < buy_price - 0.01:
        st.error(
            f"₹{sell_price:,.1f} per plate is less than the ₹{buy_price:,.1f} "
            "paid to the vendor — every plate loses money before SmartQ's "
            "own costs."
        )
    elif sell_price < overall_per_plate - 0.01:
        st.warning(
            f"₹{sell_price:,.1f} per plate is under the ₹{overall_per_plate:,.1f} "
            "overall cost — it covers the vendor but not the fully-loaded cost."
        )

    # The results belong at the top — they are what the tab is for. The
    # figures depend on the cost lines rendered further down, so the space
    # is claimed here and written into once they are known.
    results = st.container()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Selling Price / plate", f"₹{sell_price:,.1f}")
    m2.metric("Buying Price / plate", f"₹{buy_price:,.1f}",
              help="What the vendor is paid per plate — the Vendor Cost "
                   "tab's total. The rest of the overall cost is SmartQ's "
                   "margin.")
    m3.metric("Buying Amt", f"₹{buy_amt:,.1f}")
    m4.metric("Selling Amount", f"₹{sell_amt:,.1f}")

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
            min_value=0.0, step=0.5, format="%.1f",
            label_visibility="collapsed",
            on_change=_on_pct_change, args=(key, divisor),
        )
        row[2].number_input(
            f"{label} amount", key=f"sq_{key}_abs",
            min_value=0.0, step=1.0, format="%.1f",
            label_visibility="collapsed",
            on_change=_on_abs_change, args=(key, divisor),
        )
        row[3].markdown(_cadence_badge(cadence), unsafe_allow_html=True)

    total = smartq_cost(
        ss[f"sq_{key}_abs"] for key, _l, _d, _c, _dv in SMARTQ_COST_LINES
    )
    # SmartQ's margin on the plate — the gap between what the vendor is
    # paid and the overall cost, set in the vendor tab. Revenue over the
    # period, so it is added to profit rather than netted off a cost.
    margin_pct = ss.get("vc_smartq_margin_pct", 0.0)
    extra_margin = extra_margin_amount(
        margin_pct, overall_per_plate, pax, days,
    )
    profit = smartq_profit(sell_amt, buy_amt, total, extra_margin)
    profit_margin = smartq_profit_pct(profit, sell_amt)

    with results:
        out1, out2, out3 = st.columns(3)
        out1.metric("Total SmartQ Profit", f"₹{profit:,.1f}",
                    delta=f"{profit_margin:.1f}% of the selling amount",
                    help="Selling amount − buying amount − SmartQ cost + "
                         "extra margin.")
        out2.metric("Extra Margin", f"₹{extra_margin:,.1f}",
                    delta=f"{margin_pct:.1f}% of the plate x {pax} pax x {days} days",
                    delta_color="off",
                    help="SmartQ's profit per plate from the Vendor Cost tab, "
                         "over the whole period. Revenue — it is added to "
                         "profit, not to cost.")
        out3.metric("SmartQ Cost", f"₹{total:,.1f}", delta_color="off",
                    help="Sum of every operating line below (monthly basis; "
                         "the yearly Food Licenses line is included at 1/12).")
        st.divider()
