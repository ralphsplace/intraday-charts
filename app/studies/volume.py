"""Volume studies: volume bars and the volume profile."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import engine as en
from .. import indicators as ind
from .base import P, color, plot, study, ln, bars_for, level, AMBER, RED, GREEN


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


# ---------------------------------------------------------------- volume profile
VP_ROW_MODES = ["Number of rows", "Tick size", "Custom price per row"]
VP_MAX_ROWS = 1500


@study("volume_profile", "Volume profile", "Volume", "price",
       [P("range", "Range", "choice", "Today, all sessions",
          options=["Today, all sessions", "Today, regular hours", "All shown days"]),
        P("row_mode", "Row height", "choice", VP_ROW_MODES[0], options=VP_ROW_MODES),
        P("rows", "Rows (Number of rows)", "int", 60, min=10, max=200),
        P("ticks", "Ticks per row (Tick size)", "int", 1, min=1, max=500),
        P("tick_size", "Tick size $", "float", 0.01, min=0.0001, max=10, step=0.01),
        P("row_price", "Price per row $ (Custom)", "float", 0.05, min=0.001, max=50, step=0.01),
        P("va_pct", "Value area %", "int", 70, min=10, max=95),
        P("side", "Side", "choice", "Left", options=["Left", "Right"]),
        P("width_pct", "Width (% of chart)", "int", 25, min=5, max=60),
        P("lines", "Show POC / VAH / VAL lines", "bool", True),
        color("#26a69a", "va_color", "Value area bars"), color("#5f6b7a", "out_color", "Other bars"),
        P("opacity", "Bar opacity %", "int", 45, min=5, max=100, section="Style")],
       lambda p: (f"Volume profile ({p['range'].split(',')[0].lower()}{', RTH' if 'regular' in p['range'] else ''}"
                  + {"Tick size": f", {p['ticks']} tick{'s' if p['ticks'] > 1 else ''}/row",
                     "Custom price per row": f", ${p['row_price']:g}/row"}.get(p["row_mode"], "") + ")"),
       "Volume traded at each price as a horizontal histogram, with point of control and value area. Row height: "
       "a fixed number of rows across the range, one row per price tick (QQQ: $0.01) or a few ticks, or a "
       "custom price per row, like thinkorswim's row-height modes. Each bar's volume is spread evenly over "
       "the rows between its low and high.",
       plots=[plot("poc_line", "POC line", "#ef5350", 2, "dotted"), plot("va_lines", "VAH / VAL lines", "#e6b450", 1, "dashed")], intraday=True)
def _volume_profile(ctx, p):
    if p["range"] == "All shown days":
        frames = [ctx.minute_bars(d) for d in ctx.shown_prior_days] + [ctx.cut]
        bars = pd.concat(frames, ignore_index=True)
    elif p["range"] == "Today, regular hours":
        bars = ctx.rth
    else:
        bars = ctx.cut
    if bars.empty or bars["volume"].sum() <= 0:
        return {"note": "no volume yet"}
    lo, hi = float(bars["low"].min()), float(bars["high"].max())
    if hi <= lo:
        return {"note": "no price range yet"}
    note = None
    if p["row_mode"] == "Number of rows":
        n = p["rows"]
        step = (hi - lo) / n
        base = lo                                   # rows [lo + k*step, lo + (k+1)*step)
        idx = lambda x: np.minimum(((x - base) / step).astype(int), n - 1)  # noqa: E731
        mid = lambda k: base + (k + 0.5) * step     # noqa: E731
    else:
        step = p["ticks"] * p["tick_size"] if p["row_mode"] == "Tick size" else p["row_price"]
        if (hi - lo) / step + 1 > VP_MAX_ROWS:      # keep the drawing light on wide ranges
            mult = int(np.ceil((hi - lo) / step / VP_MAX_ROWS))
            step *= mult
            note = f"rows widened to ${step:g} to stay under {VP_MAX_ROWS} rows"
        base = np.floor(lo / step + 0.5) * step     # rows centred on price multiples of the row height
        n = int(np.floor(hi / step + 0.5) - np.floor(lo / step + 0.5)) + 1
        idx = lambda x: np.clip(np.floor((x - base) / step + 0.5).astype(int), 0, n - 1)  # noqa: E731
        mid = lambda k: base + k * step             # noqa: E731
    i0 = idx(bars["low"].to_numpy(dtype=float))
    i1 = idx(bars["high"].to_numpy(dtype=float))
    share = bars["volume"].to_numpy(dtype=float) / (i1 - i0 + 1)
    diff = np.zeros(n + 1)
    np.add.at(diff, i0, share)
    np.add.at(diff, i1 + 1, -share)
    vol = np.cumsum(diff)[:n]
    poc_i, i, j = ind.value_area(vol, p["va_pct"] / 100)
    edge_lo = lambda k: mid(k) - step / 2           # noqa: E731
    profile = {"bins": [{"lo": round(float(edge_lo(k)), 4), "hi": round(float(edge_lo(k) + step), 4),
                         "vol": round(float(vol[k]), 1), "va": i <= k <= j} for k in range(n) if vol[k] > 0 or n <= 400],
               "side": p["side"].lower(), "width_pct": p["width_pct"], "va_color": p["va_color"],
               "out_color": p["out_color"], "opacity": p["opacity"] / 100}
    out = {"profile": profile}
    if note:
        out["note"] = note
    if p["lines"]:
        by_rows = p["row_mode"] == "Number of rows"     # row edges; otherwise the rows' own prices
        vah = edge_lo(j) + step if by_rows else mid(j)
        val = edge_lo(i) if by_rows else mid(i)
        out["levels"] = [level(p, "poc_line", round(float(mid(poc_i)), 4), "POC"),
                         level(p, "va_lines", round(float(vah), 4), "VAH"),
                         level(p, "va_lines", round(float(val), 4), "VAL")]
    return out
