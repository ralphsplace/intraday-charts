"""Oscillators, each in its own pane: RSI, MACD, Stochastic, ATR, ADX, CCI, Williams %R, OBV, VZO."""
from __future__ import annotations

import math

from .. import indicators as ind
from .base import P, src_param, color, plot, study, ln, hl, bars_for, GRAY, PURPLE, TEAL, AMBER, ORANGE, BLUE, PINK, RED, GREEN, DIM


@study("rsi", "Relative Strength Index (RSI)", "Oscillators", "own",
       [P("length", "Length", "int", 14, min=2, max=100), src_param(),
        P("overbought", "Overbought", "int", 70, min=50, max=100), P("oversold", "Oversold", "int", 30, min=0, max=50)],
       lambda p: f"RSI ({p['length']})", "Momentum oscillator from 0 to 100 (Wilder smoothing).",
       plots=[plot("rsi", "RSI", PURPLE), plot("ob", "Overbought line", GRAY, 1, "dashed"),
              plot("mid", "Middle line (50)", DIM, 1, "dotted"), plot("os", "Oversold line", GRAY, 1, "dashed")],
       warmup=lambda p: p["length"] * 5)
def _rsi(ctx, p):
    w = bars_for(ctx, p["length"] * 5)
    return {"lines": [ln("rsi", "RSI", ctx.points(w, ind.rsi(ind.source(w, p["source"]), p["length"]), 2), last_value=True)],
            "hlines": [hl(p["overbought"], "ob"), hl(50, "mid"), hl(p["oversold"], "os")]}


@study("macd", "MACD", "Oscillators", "own",
       [P("fast", "Fast length", "int", 12, min=1, max=100), P("slow", "Slow length", "int", 26, min=2, max=200),
        P("signal", "Signal length", "int", 9, min=1, max=100), src_param(),
        color(GREEN, "hist_up", "Histogram above zero"), color(RED, "hist_down", "Histogram below zero")],
       lambda p: f"MACD ({p['fast']}, {p['slow']}, {p['signal']})", "Difference of two EMAs, its signal line and histogram.",
       plots=[plot("macd", "MACD", BLUE), plot("signal", "Signal", ORANGE), plot("zero", "Zero line", DIM, 1, "dotted")],
       warmup=lambda p: p["slow"] * 3)
def _macd(ctx, p):
    w = bars_for(ctx, p["slow"] * 3)
    line, sig, hist = ind.macd(ind.source(w, p["source"]), p["fast"], p["slow"], p["signal"])
    hdata, prev = [], None
    for t, cur, v in zip(w["ct"], w["current"], hist, strict=True):
        if cur and not math.isnan(v):
            growing = prev is None or abs(v) >= abs(prev)
            base = p["hist_up"] if v >= 0 else p["hist_down"]
            hdata.append({"time": int(t), "value": round(float(v), 4), "color": base + ("" if growing else "80")})
        prev = v if not math.isnan(v) else prev
    return {"histograms": [{"id": "hist", "title": "Histogram", "data": hdata}],
            "lines": [ln("macd", "MACD", ctx.points(w, line), last_value=True),
                      ln("signal", "Signal", ctx.points(w, sig), last_value=True)],
            "hlines": [hl(0, "zero")]}


@study("stoch", "Stochastic", "Oscillators", "own",
       [P("k", "%K length", "int", 14, min=1, max=100), P("smooth", "%K smoothing", "int", 3, min=1, max=20),
        P("d", "%D length", "int", 3, min=1, max=20), P("upper", "Upper band", "int", 80, min=50, max=100),
        P("lower", "Lower band", "int", 20, min=0, max=50)],
       lambda p: f"Stoch ({p['k']}, {p['smooth']}, {p['d']})", "Where the close sits within the recent range.",
       plots=[plot("k", "%K", BLUE), plot("d", "%D", ORANGE), plot("upper", "Upper band line", GRAY, 1, "dashed"),
              plot("lower", "Lower band line", GRAY, 1, "dashed")],
       warmup=lambda p: p["k"] + p["smooth"] + p["d"])
def _stoch(ctx, p):
    w = bars_for(ctx, p["k"] + p["smooth"] + p["d"])
    k, d = ind.stochastic(w, p["k"], p["smooth"], p["d"])
    return {"lines": [ln("k", "%K", ctx.points(w, k, 2), last_value=True), ln("d", "%D", ctx.points(w, d, 2))],
            "hlines": [hl(p["upper"], "upper"), hl(p["lower"], "lower")]}


@study("atr", "Average True Range (ATR)", "Oscillators", "own",
       [P("length", "Length", "int", 14, min=1, max=100)],
       lambda p: f"ATR ({p['length']})", "Average bar range on the chart timeframe (Wilder smoothing).",
       plots=[plot("atr", "ATR", ORANGE)], warmup=lambda p: p["length"] * 5)
def _atr(ctx, p):
    w = bars_for(ctx, p["length"] * 5)
    return {"lines": [ln("atr", "ATR", ctx.points(w, ind.atr(w, p["length"])), last_value=True)]}


@study("adx", "ADX / DMI", "Oscillators", "own",
       [P("length", "Length", "int", 14, min=2, max=100), P("threshold", "Trend threshold", "int", 25, min=5, max=60)],
       lambda p: f"ADX ({p['length']})", "Trend strength (ADX) with directional lines (+DI / -DI).",
       plots=[plot("adx", "ADX", AMBER, 2), plot("pdi", "+DI", GREEN), plot("mdi", "-DI", RED),
              plot("thr", "Threshold line", DIM, 1, "dotted")],
       warmup=lambda p: p["length"] * 6)
def _adx(ctx, p):
    w = bars_for(ctx, p["length"] * 6)
    a, pdi, mdi = ind.adx(w, p["length"])
    return {"lines": [ln("adx", "ADX", ctx.points(w, a, 2), last_value=True), ln("pdi", "+DI", ctx.points(w, pdi, 2)),
                      ln("mdi", "-DI", ctx.points(w, mdi, 2))],
            "hlines": [hl(p["threshold"], "thr")]}


@study("cci", "Commodity Channel Index (CCI)", "Oscillators", "own",
       [P("length", "Length", "int", 20, min=2, max=200)],
       lambda p: f"CCI ({p['length']})", "Distance of price from its average, scaled by mean deviation.",
       plots=[plot("cci", "CCI", PINK), plot("p100", "+100 line", GRAY, 1, "dashed"),
              plot("m100", "-100 line", GRAY, 1, "dashed")], warmup=lambda p: p["length"])
def _cci(ctx, p):
    w = bars_for(ctx, p["length"])
    return {"lines": [ln("cci", "CCI", ctx.points(w, ind.cci(w, p["length"]), 2), last_value=True)],
            "hlines": [hl(100, "p100"), hl(-100, "m100")]}


@study("willr", "Williams %R", "Oscillators", "own",
       [P("length", "Length", "int", 14, min=2, max=200)],
       lambda p: f"%R ({p['length']})", "Close relative to the recent high-low range, 0 to -100.",
       plots=[plot("wr", "%R", BLUE), plot("ob", "Overbought line (-20)", GRAY, 1, "dashed"),
              plot("os", "Oversold line (-80)", GRAY, 1, "dashed")], warmup=lambda p: p["length"])
def _willr(ctx, p):
    w = bars_for(ctx, p["length"])
    return {"lines": [ln("wr", "%R", ctx.points(w, ind.williams_r(w, p["length"]), 2), last_value=True)],
            "hlines": [hl(-20, "ob"), hl(-80, "os")]}


@study("obv", "On-Balance Volume (OBV)", "Oscillators", "own", [],
       lambda p: "OBV", "Running total of volume signed by bar direction (today's session).",
       plots=[plot("obv", "OBV", TEAL)])
def _obv(ctx, p):
    w = ctx.shown
    return {"lines": [ln("obv", "OBV", ctx.points(w, ind.obv(w), 0), last_value=True)]}


# ---------------------------------------------------------------- Volume Zone Oscillator
VZO_COLOR_MODES = ["Levels (thinkorswim STO_VZO)", "Zone (above/below +/-40)", "Slope (rising/falling)", "Single color"]


@study("vzo", "Volume Zone Oscillator (VZO)", "Oscillators", "own",
       [P("length", "Length", "int", 20, min=2, max=200),
        P("draw", "Draw as", "choice", "Dots", options=["Dots", "Line"]),
        P("color_mode", "Color by", "choice", VZO_COLOR_MODES[0], options=VZO_COLOR_MODES),
        P("green_above", "Levels: green above", "float", 15.0, min=-100, max=100),
        P("red_below", "Levels: red below", "float", -5.0, min=-100, max=100),
        P("signal", "Signal line (EMA of VZO, 0 = off)", "int", 0, min=0, max=100),
        P("bands", "Shade +/-40 to +/-60 zones", "bool", True),
        color("#3fbf4f", "up_color", "Bullish color"), color("#e6d450", "mid_color", "Neutral color"),
        color("#ef5350", "dn_color", "Bearish color")],
       lambda p: f"VZO ({p['length']})",
       "Direction-signed volume as a % of total volume (Khalil and Steckler). Coloured like thinkorswim's "
       "STO_VZO_Lower by default: green above +15, yellow, red below -5, with shaded zones from +/-40 to "
       "+/-60. An indicator only: it draws nothing on the price chart.",
       plots=[plot("vzo", "VZO", "#e6d450", 2), plot("sig", "Signal line", "#4d9de0", 1),
              plot("p60", "+60 line", "#3fbf4f", 1, "solid"), plot("p40", "+40 line", "#3fbf4f", 1, "dashed"),
              plot("zero", "Zero line", DIM, 1, "dotted"),
              plot("m40", "-40 line", "#ef5350", 1, "dashed"), plot("m60", "-60 line", "#ef5350", 1, "solid")],
       warmup=lambda p: p["length"] * 4)
def _vzo(ctx, p):
    w = bars_for(ctx, p["length"] * 4)
    v = ind.vzo(w, p["length"])
    pts = ctx.points(w, v, 2)
    mode = p["color_mode"]
    if not mode.startswith("Single"):
        prev = None
        for pt in pts:
            x = pt["value"]
            if mode.startswith("Levels"):
                pt["color"] = p["up_color"] if x > p["green_above"] else p["mid_color"] if x > p["red_below"] else p["dn_color"]
            elif mode.startswith("Zone"):
                pt["color"] = p["up_color"] if x >= 40 else p["dn_color"] if x <= -40 else p["mid_color"]
            else:
                pt["color"] = p["mid_color"] if prev is None else (p["up_color"] if x >= prev else p["dn_color"])
            prev = x
    lines = [ln("vzo", "VZO", pts, last_value=True, markers_only=p["draw"] == "Dots")]
    if p["signal"]:
        lines.append(ln("sig", "Signal", ctx.points(w, ind.ema(v, p["signal"]), 2)))
    out = {"lines": lines, "hlines": [hl(60, "p60"), hl(40, "p40"), hl(0, "zero"), hl(-40, "m40"), hl(-60, "m60")]}
    if p["bands"]:
        out["bands"] = [{"from": 40, "to": 60, "color": p["up_color"]}, {"from": -60, "to": -40, "color": p["dn_color"]}]
    return out
