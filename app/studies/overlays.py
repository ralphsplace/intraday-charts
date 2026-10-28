"""Studies drawn over the price: moving averages, VWAP, bands and channels, Parabolic SAR, moving average cloud."""
from __future__ import annotations

import pandas as pd

from .. import engine as en
from .. import indicators as ind
from .base import P, src_param, color, plot, with_alpha, study, ln, bars_for, level, TEAL, AMBER, ORANGE, BLUE, PINK, RED, GREEN


@study("sma", "Simple moving average (SMA)", "Overlays", "price",
       [P("length", "Length", "int", 50, min=1, max=500), src_param()],
       lambda p: f"SMA ({p['length']}, {p['source']})", "Average of the last N bars on the chart timeframe.",
       plots=[plot("sma", "SMA", BLUE)], warmup=lambda p: p["length"])
def _sma(ctx, p):
    w = bars_for(ctx, p["length"])
    return {"lines": [ln("sma", f"SMA {p['length']}", ctx.points(w, ind.sma(ind.source(w, p["source"]), p["length"])))]}


@study("ema", "Exponential moving average (EMA)", "Overlays", "price",
       [P("length", "Length", "int", 9, min=1, max=500), src_param()],
       lambda p: f"EMA ({p['length']}, {p['source']})", "Moving average weighted toward recent bars.",
       plots=[plot("ema", "EMA", AMBER)], warmup=lambda p: p["length"] * 3)
def _ema(ctx, p):
    w = bars_for(ctx, p["length"] * 3)
    return {"lines": [ln("ema", f"EMA {p['length']}", ctx.points(w, ind.ema(ind.source(w, p["source"]), p["length"])))]}


@study("wma", "Weighted moving average (WMA)", "Overlays", "price",
       [P("length", "Length", "int", 20, min=1, max=500), src_param()],
       lambda p: f"WMA ({p['length']}, {p['source']})", "Linearly weighted moving average.",
       plots=[plot("wma", "WMA", PINK)])
def _wma(ctx, p):
    w = bars_for(ctx, p["length"])
    return {"lines": [ln("wma", f"WMA {p['length']}", ctx.points(w, ind.wma(ind.source(w, p["source"]), p["length"])))]}


@study("vwap", "VWAP", "Overlays", "price",
       [P("session", "Session", "choice", "Regular hours", options=["Regular hours", "Extended (from 04:00)"]),
        P("bands", "Show bands", "bool", True),
        P("band1", "Band 1 (std devs)", "float", 1.0, min=0.1, max=5, step=0.1),
        P("band2", "Band 2 (std devs)", "float", 2.0, min=0.1, max=5, step=0.1)],
       lambda p: f"VWAP ({'RTH' if p['session'] == 'Regular hours' else 'ETH'})",
       "Volume-weighted average price for the session, with standard-deviation bands.",
       plots=[plot("vwap", "VWAP", TEAL, 2), plot("band1", "Band 1", TEAL, 1, "dotted"),
              plot("band2", "Band 2", TEAL, 1, "sparse_dotted")], intraday=True)
def _vwap(ctx, p):
    v = ctx.vwap_tf("rth" if p["session"] == "Regular hours" else "all", shown=True)
    lines = [ln("vwap", "VWAP", ctx.points(v, v["vwap"]), last_value=True)]
    if p["bands"]:
        for name, k in (("band1", p["band1"]), ("band2", p["band2"])):
            lines.append(ln(f"{name}_up", "", ctx.points(v, v["vwap"] + k * v["sd"])))
            lines.append(ln(f"{name}_dn", "", ctx.points(v, v["vwap"] - k * v["sd"])))
    return {"lines": lines}


# ---------------------------------------------------------------- anchored VWAP
AVWAP_ANCHORS = ["Chosen time", "High of day", "Low of day", "Prior day high", "Prior day low", "Latest event today"]
AVWAP_MAX_DAYS = 15          # how far back an anchor can be (cached 1-minute days)


def _extreme_time(bars: pd.DataFrame, col: str) -> pd.Timestamp | None:
    """Time of the regular-hours bar with the highest high (col="high") or lowest low (col="low")."""
    m = en.minute_of_day(bars["time"]) if not bars.empty else None
    rth = bars[(m >= en.RTH_START) & (m < en.RTH_END)] if m is not None else bars
    if rth.empty:
        return None
    i = rth[col].idxmax() if col == "high" else rth[col].idxmin()
    return rth.loc[i, "time"]


def avwap_anchor(ctx, p) -> tuple[pd.Timestamp | None, str]:
    """Where the VWAP starts (a 1-minute bar's time), and why; None with the reason when it can't."""
    mode = p["anchor"]
    if mode == "Chosen time":
        text = (p["at"] or "").strip() or f"{ctx.day} 09:30"
        try:
            t = pd.Timestamp(text)
        except (ValueError, TypeError):
            return None, f"can't read the anchor time '{text}' (use YYYY-MM-DD HH:MM)"
        return t.tz_localize(ctx.day0.tz) if t.tzinfo is None else t.tz_convert(ctx.day0.tz), text
    if mode in ("High of day", "Low of day"):
        t = _extreme_time(ctx.cut, "high" if mode == "High of day" else "low")
        return (t, f"{mode.lower()} {t:%H:%M}") if t is not None else (None, "no regular-hours bars yet")
    if mode in ("Prior day high", "Prior day low"):
        if not ctx.prior_days:
            return None, "no prior day cached"
        d = ctx.prior_days[-1]
        t = _extreme_time(ctx.minute_bars(d), "high" if mode == "Prior day high" else "low")
        return (t, f"{mode.lower()} {d} {t:%H:%M}") if t is not None else (None, f"no bars for {d}")
    seen = [e for e in ctx.events if e["minute"] < ctx.cursor]
    if not seen:
        return None, "no event yet today (data/events.json)"
    e = seen[-1]
    return ctx.day0 + pd.Timedelta(minutes=e["minute"]), f"{e['label']} {e['time']}"


@study("anchored_vwap", "Anchored VWAP", "Overlays", "price",
       [P("anchor", "Anchor", "choice", AVWAP_ANCHORS[0], options=AVWAP_ANCHORS),
        P("at", "Chosen time (YYYY-MM-DD HH:MM, ET)", "text", ""),
        P("extended", "Include extended hours", "bool", False),
        P("bands", "Show bands", "bool", True),
        P("band1", "Band 1 (std devs)", "float", 1.0, min=0.1, max=5, step=0.1),
        P("band2", "Band 2 (std devs)", "float", 2.0, min=0.1, max=5, step=0.1)],
       lambda p: "Anchored VWAP (" + (p["at"] or "09:30" if p["anchor"] == "Chosen time" else p["anchor"].lower()) + ")",
       "VWAP that starts at a bar you choose instead of the session open: a time (click the chart with the VWAP "
       "button in the header), the high or low of today or of the prior day, or the latest event in "
       "data/events.json. The bands are measured from the anchor, so they start tight and widen. It carries on "
       "across days, up to 15 days back.",
       plots=[plot("vwap", "Anchored VWAP", ORANGE, 2), plot("band1", "Band 1", ORANGE, 1, "dotted"),
              plot("band2", "Band 2", ORANGE, 1, "sparse_dotted"), plot("anchor", "Anchor line", ORANGE, 1, "dotted")],
       intraday=True)
def _anchored_vwap(ctx, p):
    start, why = avwap_anchor(ctx, p)
    if start is None:
        return {"lines": [], "note": why}
    now = ctx.day0 + pd.Timedelta(minutes=ctx.cursor)
    if start >= now:
        return {"lines": [], "note": f"anchor {why} is after the replay time"}
    day = start.strftime("%Y-%m-%d")
    days = [d for d in ctx.prior_days if d >= day][-AVWAP_MAX_DAYS:]
    if day < ctx.day and (not days or days[0] != day):
        return {"lines": [], "note": f"no 1-minute bars cached for {day}"}
    bars = pd.concat([*(ctx.minute_bars(d) for d in days), ctx.cut], ignore_index=True)
    bars = bars[bars["time"] >= start]
    if not p["extended"]:
        m = en.minute_of_day(bars["time"])
        bars = bars[(m >= en.RTH_START) & (m < en.RTH_END)]
    if bars.empty:
        return {"lines": [], "note": f"no bars after the anchor ({why})"}
    v = ctx.on_chart(en.vwap_frame(bars), ["vwap", "sd"])
    lines = [ln("vwap", "AVWAP", ctx.points(v, v["vwap"]), last_value=True)]
    if p["bands"]:
        for name, k in (("band1", p["band1"]), ("band2", p["band2"])):
            lines.append(ln(f"{name}_up", "", ctx.points(v, v["vwap"] + k * v["sd"])))
            lines.append(ln(f"{name}_dn", "", ctx.points(v, v["vwap"] - k * v["sd"])))
    out = {"lines": lines, "note": f"from {why}"}
    upto = v[v["time"] <= start]                     # the candle holding the anchor, when it's on the chart
    if not upto.empty:
        out["verticals"] = [{"time": int(upto["ct"].iloc[-1]), "label": "AVWAP anchor", "plot": "anchor"}]
    return out


@study("bollinger", "Bollinger Bands", "Overlays", "price",
       [P("length", "Length", "int", 20, min=2, max=300), P("mult", "Std devs", "float", 2.0, min=0.5, max=5, step=0.1),
        src_param()],
       lambda p: f"BB ({p['length']}, {p['mult']:g})", "SMA with bands N standard deviations away.",
       plots=[plot("upper", "Upper", BLUE), plot("basis", "Basis", BLUE, 1, "dashed"), plot("lower", "Lower", BLUE)],
       warmup=lambda p: p["length"])
def _bb(ctx, p):
    w = bars_for(ctx, p["length"])
    mid, up, lo = ind.bollinger(ind.source(w, p["source"]), p["length"], p["mult"])
    return {"lines": [ln("upper", "BB upper", ctx.points(w, up)), ln("basis", "BB basis", ctx.points(w, mid)),
                      ln("lower", "BB lower", ctx.points(w, lo))]}


@study("keltner", "Keltner Channels", "Overlays", "price",
       [P("length", "Length", "int", 20, min=2, max=300), P("mult", "ATR multiplier", "float", 1.5, min=0.5, max=5, step=0.1)],
       lambda p: f"KC ({p['length']}, {p['mult']:g})", "EMA with bands a multiple of ATR away.",
       plots=[plot("upper", "Upper", ORANGE), plot("basis", "Basis", ORANGE, 1, "dashed"), plot("lower", "Lower", ORANGE)],
       warmup=lambda p: p["length"] * 3)
def _kc(ctx, p):
    w = bars_for(ctx, p["length"] * 3)
    mid, up, lo = ind.keltner(w, p["length"], p["mult"])
    return {"lines": [ln("upper", "KC upper", ctx.points(w, up)), ln("basis", "KC basis", ctx.points(w, mid)),
                      ln("lower", "KC lower", ctx.points(w, lo))]}


@study("donchian", "Donchian Channels", "Overlays", "price",
       [P("length", "Length", "int", 20, min=2, max=300)],
       lambda p: f"DC ({p['length']})", "Highest high and lowest low of the last N bars.",
       plots=[plot("upper", "Upper", PINK), plot("mid", "Middle", PINK, 1, "dotted"), plot("lower", "Lower", PINK)],
       warmup=lambda p: p["length"])
def _dc(ctx, p):
    w = bars_for(ctx, p["length"])
    mid, up, lo = ind.donchian(w, p["length"])
    return {"lines": [ln("upper", "DC upper", ctx.points(w, up)), ln("mid", "DC mid", ctx.points(w, mid)),
                      ln("lower", "DC lower", ctx.points(w, lo))]}


@study("psar", "Parabolic SAR", "Overlays", "price",
       [P("step", "Step", "float", 0.02, min=0.001, max=0.2, step=0.001),
        P("max", "Maximum", "float", 0.2, min=0.01, max=1, step=0.01),
        P("draw", "Draw as", "choice", "Dots", options=["Dots", "Line"])],
       lambda p: f"SAR ({p['step']:g}, {p['max']:g})",
       "Trailing stop-and-reverse. Drawn as dots (thickness sets dot size) or as a line (line type applies).",
       plots=[plot("sar", "Dots", AMBER, 2)], warmup=lambda p: 50)
def _psar(ctx, p):
    w = bars_for(ctx, 50)
    return {"lines": [ln("sar", "SAR", ctx.points(w, ind.psar(w, p["step"], p["max"])), markers_only=p["draw"] == "Dots")]}


MA_TYPES = ["SMA", "EMA"]
MA_TIMEFRAMES = ["Chart timeframe", "Daily"]


def ma(series: pd.Series, kind: str, n: int) -> pd.Series:
    return ind.sma(series, n) if kind == "SMA" else ind.ema(series, n)


@study("ma_cloud", "Moving average cloud", "Overlays", "price",
       [P("timeframe", "Timeframe", "choice", MA_TIMEFRAMES[0], options=MA_TIMEFRAMES),
        P("type1", "MA 1 type", "choice", "EMA", options=MA_TYPES),
        P("len1", "MA 1 length", "int", 9, min=1, max=400),
        P("type2", "MA 2 type", "choice", "EMA", options=MA_TYPES),
        P("len2", "MA 2 length", "int", 21, min=1, max=400),
        src_param(),
        P("cloud", "Fill between the two lines", "bool", True, section="Cloud"),
        color(GREEN, "up_color", "MA 1 above MA 2", section="Cloud"),
        P("up_transp", "MA 1 above MA 2: transparency %", "int", 75, min=0, max=100, section="Cloud"),
        color(RED, "down_color", "MA 2 above MA 1", section="Cloud"),
        P("down_transp", "MA 2 above MA 1: transparency %", "int", 75, min=0, max=100, section="Cloud")],
       lambda p: f"MA cloud ({p['type1']} {p['len1']} / {p['type2']} {p['len2']}"
                 + (", daily)" if p["timeframe"] == "Daily" else ")"),
       "Two moving averages (SMA or EMA each) with the space between them filled: one colour while MA 1 is "
       "above MA 2, another while MA 2 is above MA 1. On the chart's timeframe, or from daily closes "
       "(drawn as today's levels; long lengths need daily history from the fetch's --daily-years).",
       plots=[plot("ma1", "MA 1", AMBER, 2), plot("ma2", "MA 2", BLUE, 2)],
       warmup=lambda p: max(p["len1"], p["len2"]) * 3)
def _ma_cloud(ctx, p):
    up = with_alpha(p["up_color"], p["up_transp"])
    down = with_alpha(p["down_color"], p["down_transp"])
    if p["timeframe"] == "Daily":
        closes = ctx.daily["close"].astype(float).reset_index(drop=True)
        vals, missing = {}, []
        for key, kind, n in (("ma1", p["type1"], p["len1"]), ("ma2", p["type2"], p["len2"])):
            if len(closes) < n:
                missing.append(f"{n}-day needs {n} days, have {len(closes)}")
            else:
                vals[key] = float(ma(closes, kind, n).iloc[-1])
        names = {"ma1": f"D{p['type1']} {p['len1']}", "ma2": f"D{p['type2']} {p['len2']}"}
        out = {"levels": [level(p, k, v, names[k]) for k, v in vals.items()]}
        if p["cloud"] and len(vals) == 2:
            out["cloud"] = {"points": [{"time": int(t), "a": round(vals["ma1"], 4), "b": round(vals["ma2"], 4)}
                                       for t in ctx.shown["ct"]], "up": up, "down": down}
        # levels don't stretch the price scale, so show the values in the legend too
        notes = [f"{names[k]}: {v:.2f}" for k, v in vals.items()] + missing
        if notes:
            out["note"] = " · ".join(notes)
        return out
    w = bars_for(ctx, max(p["len1"], p["len2"]) * 3)
    src = ind.source(w, p["source"])
    m1, m2 = ma(src, p["type1"], p["len1"]), ma(src, p["type2"], p["len2"])
    out = {"lines": [ln("ma1", f"{p['type1']} {p['len1']}", ctx.points(w, m1), last_value=True),
                     ln("ma2", f"{p['type2']} {p['len2']}", ctx.points(w, m2), last_value=True)]}
    if p["cloud"]:
        keep = w["current"].to_numpy(dtype=bool) & m1.notna().to_numpy() & m2.notna().to_numpy()
        out["cloud"] = {"points": [{"time": int(t), "a": round(float(a), 4), "b": round(float(b), 4)}
                                   for t, a, b in zip(w["ct"].to_numpy()[keep], m1.to_numpy()[keep], m2.to_numpy()[keep], strict=True)],
                        "up": up, "down": down}
    return out
