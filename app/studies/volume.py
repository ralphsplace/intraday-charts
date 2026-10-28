"""Volume studies: volume bars, relative volume by time of day, and an estimate of cumulative volume delta
(the profiles are in profiles.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import engine as en
from .. import indicators as ind
from .base import P, color, plot, study, ln, hl, bars_for, AMBER, GRAY, RED, GREEN


@study("volume", "Volume", "Volume", "volume",
       [P("ma", "Show moving average", "bool", True), P("ma_length", "MA length", "int", 20, min=2, max=200),
        color(GREEN, "up_color", "Up bars"), color(RED, "down_color", "Down bars")],
       lambda p: "Volume" + (f" (MA {p['ma_length']})" if p["ma"] else ""), "Bar volume, dimmed outside regular hours.",
       plots=[plot("ma", "Moving average", AMBER)], warmup=lambda p: p["ma_length"])
def _volume(ctx, p):
    w = bars_for(ctx, p["ma_length"])
    hist = []
    for r in w[w["current"]].itertuples():
        rth = en.RTH_START <= r.bucket < en.RTH_END
        col = (p["up_color"] if r.close >= r.open else p["down_color"]) + ("73" if rth else "33")
        hist.append({"time": int(r.ct), "value": float(r.volume), "color": col})
    out = {"histograms": [{"id": "vol", "title": "Volume", "data": hist}]}
    if p["ma"]:
        out["lines"] = [ln("ma", f"Vol MA {p['ma_length']}", ctx.points(w, ind.sma(w["volume"], p["ma_length"]), 0))]
    return out



# ---------------------------------------------------------------- relative volume by time of day
@study("rvol", "Relative volume (time of day)", "Volume", "own",
       [P("sessions", "Sessions averaged", "int", 10, min=2, max=30),
        P("high", "Strong at or above (x)", "float", 2.0, min=1, max=10, step=0.1),
        P("low", "Weak below (x)", "float", 0.5, min=0.05, max=1, step=0.05),
        color(GREEN, "high_color", "Strong bars"), color("#8a8f98", "mid_color", "Normal bars"),
        color("#4a525e", "low_color", "Weak bars")],
       lambda p: f"RVOL ({p['sessions']} sessions)",
       "Each bar's volume divided by the average volume of the same time slot (e.g. 09:30-09:33) over the last "
       "N sessions, so the busy open and the quiet lunch are each compared with their own normal. 1.0 is a normal "
       "bar for that time of day. The bar still forming is compared with a full slot, so it reads low until it ends.",
       plots=[plot("one", "1.0 line", GRAY, 1, "dashed")], intraday=True)
def _rvol(ctx, p):
    n = p["sessions"]
    days = [*ctx.prior_days, ctx.day]
    w = ctx.shown
    norms, have = {}, n
    for d in sorted(set(w["day"])):
        before = [x for x in days if x < d][-n:]
        have = min(have, len(before))
        frames = [ctx.tf_bars(x)[["bucket", "volume"]] for x in before]
        norms[d] = (pd.concat(frames).groupby("bucket")["volume"].mean() if frames else pd.Series(dtype=float))
    hist = []
    for r in w.itertuples():
        avg = norms[r.day].get(r.bucket, np.nan)
        if not avg or np.isnan(avg) or avg <= 0:
            continue
        x = float(r.volume) / float(avg)
        col = p["high_color"] if x >= p["high"] else p["low_color"] if x < p["low"] else p["mid_color"]
        hist.append({"time": int(r.ct), "value": round(x, 3), "color": col})
    out = {"histograms": [{"id": "rvol", "title": "RVOL", "data": hist}], "hlines": [hl(1.0, "one")]}
    if have < n:
        out["note"] = f"averaged over {have} cached session{'s' if have != 1 else ''}" if have else "needs earlier cached days"
    return out


# ---------------------------------------------------------------- cumulative volume delta, estimated from bars
CVD_METHODS = ["Close location", "Close vs open"]
CVD_SESSIONS = ["Regular hours", "Extended (from 04:00)"]


def bar_delta(bars: pd.DataFrame, method: str) -> pd.Series:
    """Each 1-minute bar's volume, signed as an estimate of buying minus selling.
    Close location: volume x ((close - low) - (high - close)) / (high - low), from -volume (closed on the low)
    to +volume (closed on the high). Close vs open: +volume on an up bar, -volume on a down bar, 0 if flat."""
    v = bars["volume"].clip(lower=0)
    if method == CVD_METHODS[1]:
        return v * np.sign(bars["close"] - bars["open"])
    rng = (bars["high"] - bars["low"]).replace(0, np.nan)
    return (v * ((bars["close"] - bars["low"]) - (bars["high"] - bars["close"])) / rng).fillna(0.0)


@study("cvd_estimate", "Cumulative volume delta (estimate)", "Volume", "own",
       [P("method", "Estimated from", "choice", CVD_METHODS[0], options=CVD_METHODS),
        P("session", "Session (resets each day)", "choice", CVD_SESSIONS[0], options=CVD_SESSIONS)],
       lambda p: f"CVD estimate ({p['method'].lower()})",
       "An ESTIMATE of cumulative volume delta, rebuilt from 1-minute bars (how each minute closed within its "
       "range), not exchange-reported order flow: true delta needs every trade matched against the bid and ask, "
       "which this app doesn't record. Read it as a volume-weighted running total of where price closed, reset "
       "at the start of each day. On QQQ it tends to track OBV and VZO.",
       plots=[plot("cvd", "CVD estimate", "#4d9de0", 2), plot("zero", "Zero line", GRAY, 1, "dotted")], intraday=True)
def _cvd_estimate(ctx, p):
    rth = p["session"] == CVD_SESSIONS[0]
    start, end = (en.RTH_START, en.RTH_END) if rth else (en.PRE_START, en.POST_END)
    parts = []
    for d in [*ctx.shown_prior_days, ctx.day]:
        b = ctx.cut if d == ctx.day else ctx.minute_bars(d)
        m = en.minute_of_day(b["time"])
        b = b[(m >= start) & (m < end)]
        if not b.empty:
            parts.append(pd.DataFrame({"time": b["time"], "cvd": bar_delta(b, p["method"]).cumsum()}))
    if not parts:
        return {"note": "estimate starts at 09:30" if rth else "no bars yet"}
    v = ctx.on_chart(pd.concat(parts, ignore_index=True), ["cvd"])
    return {"lines": [ln("cvd", "CVD est.", ctx.points(v, v["cvd"], 0), last_value=True, format="volume")],
            "hlines": [hl(0, "zero")],
            "note": "estimated from 1-minute bars, not exchange order flow"}
