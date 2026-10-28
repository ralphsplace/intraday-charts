"""Market internals and context: NYSE TICK, cumulative TICK, relative strength, heavyweights."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import control, holdings, store
from .. import engine as en
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


# ---------------------------------------------------------------- relative strength against another symbol
RS_FROM = ["Today's open", "First bar shown"]


@study("relative_strength", "Relative strength (vs SPY)", "Market internals", "own",
       [P("symbol", "Compared with", "text", "SPY"), P("start", "Measured from", "choice", RS_FROM[0], options=RS_FROM)],
       lambda p: f"Relative strength vs {(p['symbol'] or 'SPY').upper()}",
       "How much better or worse this chart's symbol has done than another (SPY by default) since today's open "
       "or since the first bar on the chart, in %: (this / this at the start) / (other / other at the start) - 1. "
       "Above zero, it's stronger. The other symbol's bars are fetched (or streamed in Live) automatically.",
       plots=[plot("rs", "Relative strength", "#4d9de0", 2), plot("zero", "Zero line", DIM, 1, "dotted")], intraday=True)
def _relative_strength(ctx, p):
    other = control.clean_symbol(p["symbol"] or "SPY")
    if not other:
        return {"note": f"'{p['symbol']}' isn't a symbol"}
    if other == ctx.symbol:
        return {"note": "compare with a different symbol"}
    w = ctx.shown.reset_index(drop=True)
    cmp, _ = ctx.companion(other, w)
    both = cmp["close"].notna().to_numpy()
    if not both.any():
        return {"note": f"waiting for {other} bars", "needs": [other]}
    if p["start"] == RS_FROM[0]:
        today = ((w["day"] == ctx.day) & (w["bucket"] >= en.RTH_START)).to_numpy() & both
        if not today.any():
            return {"note": "starts at 09:30", "needs": [other]}
        i = int(np.argmax(today))
        b_self, b_other = float(w["open"].iloc[i]), float(cmp["open"].iloc[i])
    else:
        i = int(np.argmax(both))
        b_self, b_other = float(w["close"].iloc[i]), float(cmp["close"].iloc[i])
    rs = (w["close"] / b_self) / (cmp["close"] / b_other) * 100 - 100
    last = rs.dropna()
    since = "09:30" if p["start"] == RS_FROM[0] else "the first bar"
    note = f"{ctx.symbol} vs {other}: {last.iloc[-1]:+.2f}% since {since}" if len(last) else None
    out = {"lines": [ln("rs", f"RS vs {other}", ctx.points(w, rs, 3), last_value=True)], "hlines": [hl(0, "zero")],
           "needs": [other]}
    if note:
        out["note"] = note
    return out


# ---------------------------------------------------------------- heavyweights: which holdings move the fund
HW_FROM = ["Prior close", "Today's open"]


def _change(symbol: str, day: str, cursor: int, base: str) -> float | None:
    """% change of a symbol at the replay time on `day`, from the prior regular-hours close or today's 09:30 open."""
    df = store.read_day(symbol, day)
    if df.empty:
        return None
    m = en.minute_of_day(df["time"])
    cut = df[m < cursor]
    if cut.empty:
        return None
    now = float(cut["close"].iloc[-1])
    if base == HW_FROM[1]:
        rth = cut[en.minute_of_day(cut["time"]) >= en.RTH_START]
        ref = float(rth["open"].iloc[0]) if not rth.empty else None
    else:
        prior = en.prior_context(symbol, day, lookback=1)
        ref = float(prior["close"].iloc[-1]) if not prior.empty else None
    return (now / ref - 1) * 100 if ref else None


@study("heavyweights", "Heavyweights (QQQ top holdings)", "Market internals", "price",
       [P("fund", "Fund", "text", "QQQ"), P("count", "Holdings shown", "int", 10, min=1, max=30),
        P("start", "Moves measured from", "choice", HW_FROM[0], options=HW_FROM),
        color("#1f6f5f", "up_bg", "Adding to the fund"), color("#7a2e2e", "down_bg", "Taking from the fund"),
        color("#3a4150", "wait_bg", "No bars yet")],
       lambda p: f"Heavyweights ({(p['fund'] or 'QQQ').upper()} top {p['count']})",
       "The fund's largest holdings with each one's move and its contribution to the fund's move (move x weight, "
       "in percentage points), so you can see which names are moving QQQ right now. The first box adds up the "
       "holdings shown. Weights are a dated snapshot (app/heavyweights.json; your own in data/heavyweights.json). "
       "The holdings' bars are fetched, or streamed in Live, automatically.",
       intraday=True)
def _heavyweights(ctx, p):
    name = (p["fund"] or "QQQ").upper()
    f = holdings.fund(name)
    if not f:
        return {"note": f"no holdings listed for {name} (app/heavyweights.json)"}
    top = list(f["weights"].items())[:p["count"]]
    boxes, total, have = [], 0.0, 0
    for sym, w in top:
        chg = _change(sym, ctx.day, ctx.cursor, p["start"])
        if chg is None:
            boxes.append({"text": f"{sym} \u2026", "bg": p["wait_bg"]})
            continue
        part = chg * w / 100
        total, have = total + part, have + 1
        boxes.append({"text": f"{sym} {chg:+.2f}% ({part:+.2f})", "bg": p["up_bg"] if part >= 0 else p["down_bg"]})
    fund_chg = _change(name, ctx.day, ctx.cursor, p["start"])
    head = f"Top {len(top)}: {total:+.2f}" + (f" of {name} {fund_chg:+.2f}%" if fund_chg is not None else "")
    head_bg = p["wait_bg"] if not have else p["up_bg"] if total >= 0 else p["down_bg"]
    out = {"labels": [{"text": head, "bg": head_bg}, *boxes],
           "needs": [s for s, _ in top], "note": f"weights as of {f['as_of']}"}
    if have < len(top):
        out["note"] += f"; waiting for {len(top) - have} of {len(top)}"
    return out
