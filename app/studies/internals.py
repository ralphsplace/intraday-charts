"""Market internals: NYSE TICK and cumulative TICK."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from .base import P, color, plot, study, ln, hl, DIM


# ---------------------------------------------------------------- market internals: NYSE TICK
TICK_SYMBOLS = ["TICK-NYSE", "TICK-NDX", "TICK-NASD"]


def _tick_minutes(one: pd.DataFrame) -> np.ndarray:
    return (one["time"].dt.hour * 60 + one["time"].dt.minute).to_numpy()


def _no_tick(sym):
    return f"no {sym} bars cached for these days (the collector fetches them with every stock request)"


@study("tick", "NYSE TICK (with extreme counter)", "Market internals", "own",
       [P("symbol", "Index", "choice", TICK_SYMBOLS[0], options=TICK_SYMBOLS),
        P("extreme", "Extreme level (+/-)", "int", 1000, min=100, max=3000),
        P("mid", "Reference level (+/-)", "int", 600, min=0, max=3000),
        P("window", "Recent count window (minutes)", "int", 120, min=10, max=390),
        color("#26a69a", "up_color", "Upticks (bar high)"), color("#ef5350", "dn_color", "Downticks (bar low)"),
        color("#f0f0f0", "extreme_bar_color", "Extreme bars")],
       lambda p: f"{p['symbol']} (+/-{p['extreme']})",
       "Each bar's TICK high (up) and low (down): how many NYSE stocks last traded on an uptick minus a downtick. "
       "Readings beyond +/-1000 are extreme. The legend counts today's extreme 1-minute readings, in total and "
       "in the recent window: per tosindicators, 3+ in one direction within 2 hours shows strong sentiment and "
       "5+ can mean exhaustion (their guidance, not a tested rule).",
       plots=[plot("close", "TICK close", "#8a8f98", 1), plot("ext", "Extreme lines", "#e6b450", 1, "dashed"),
              plot("ref", "Reference lines", "#5a6270", 1, "dotted"), plot("zero", "Zero line", DIM, 1, "dotted")], intraday=True)
def _tick(ctx, p):
    w = ctx.shown.reset_index(drop=True)
    sym = p["symbol"]
    t, one = ctx.companion(sym, w)
    out = {"hlines": [hl(p["extreme"], "ext"), hl(-p["extreme"], "ext"), hl(p["mid"], "ref"), hl(-p["mid"], "ref"),
                      hl(0, "zero")]}
    if one.empty:
        out["note"] = _no_tick(sym)
        out["lines"] = [ln("close", "TICK", [])]
        return out
    cts = w["ct"].to_numpy()
    hi, lo = (t[k].to_numpy(dtype=float) for k in ("high", "low"))
    ext = p["extreme"]
    up, dn = [], []
    for i in range(len(w)):
        if np.isnan(hi[i]):
            continue
        up.append({"time": int(cts[i]), "value": float(hi[i]),
                   "color": p["extreme_bar_color"] if hi[i] >= ext else p["up_color"]})
        dn.append({"time": int(cts[i]), "value": float(lo[i]),
                   "color": p["extreme_bar_color"] if lo[i] <= -ext else p["dn_color"]})
    out["histograms"] = [{"id": "up", "title": "TICK high", "data": up}, {"id": "dn", "title": "TICK low", "data": dn}]
    out["lines"] = [ln("close", "TICK close", ctx.points(w, t["close"], 0))]
    today = one[one["day"] == ctx.day]
    if not today.empty:
        m = _tick_minutes(today)
        rth = (m >= 570) & (m < 960)
        th, tl = today["high"].to_numpy()[rth], today["low"].to_numpy()[rth]
        recent = m[rth] >= ctx.cursor - p["window"]
        out["note"] = (f"today +{ext}: {int((th >= ext).sum())}, -{ext}: {int((tl <= -ext).sum())} | "
                       f"last {p['window']} min +{int((th[recent] >= ext).sum())} / -{int((tl[recent] <= -ext).sum())}")
    return out


@study("cum_tick", "Cumulative TICK", "Market internals", "own",
       [P("symbol", "Index", "choice", TICK_SYMBOLS[0], options=TICK_SYMBOLS),
        color("#00e5ff", "up_color", "Rising"), color("#8a8f98", "dn_color", "Falling or flat")],
       lambda p: f"Cumulative {p['symbol']}",
       "Running total of TICK's (high + low + close) / 3 for every 1-minute bar from 09:30, reset each day. Rising "
       "= more stocks trading on upticks through the session. Added up per minute, so the scale is the same on "
       "every chart timeframe. Cyan while rising, grey while falling.",
       plots=[plot("cum", "Cumulative TICK", "#00e5ff", 2), plot("zero", "Zero line", DIM, 1, "dotted")], intraday=True)
def _cum_tick(ctx, p):
    w = ctx.shown.reset_index(drop=True)
    sym = p["symbol"]
    _, one = ctx.companion(sym, w)
    if one.empty:
        return {"lines": [ln("cum", "Cumulative TICK", [])], "note": _no_tick(sym), "hlines": [hl(0, "zero")]}
    m = _tick_minutes(one)
    cum = ind.cumulative_tick(one["day"].to_numpy(), m, one["high"], one["low"], one["close"])
    bucket = 240 + ((m - 240) // ctx.tf) * ctx.tf
    per_bar = (pd.DataFrame({"day": one["day"], "bucket": bucket, "cum": cum}).dropna()
               .groupby(["day", "bucket"], sort=False)["cum"].last().reset_index())
    vals = w[["day", "bucket"]].merge(per_bar, on=["day", "bucket"], how="left")["cum"].to_numpy(dtype=float)
    pts, prev = [], None
    cts = w["ct"].to_numpy()
    days = w["day"].to_numpy()
    for i in range(len(w)):
        if np.isnan(vals[i]):
            prev = None if i == 0 or days[i] != days[i - 1] else prev
            continue
        rising = prev is not None and vals[i] > prev
        pts.append({"time": int(cts[i]), "value": round(float(vals[i]), 0),
                    "color": p["up_color"] if rising else p["dn_color"]})
        prev = vals[i]
    return {"lines": [ln("cum", "Cumulative TICK", pts, last_value=True)], "hlines": [hl(0, "zero")]}
