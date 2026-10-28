"""Price levels: prior day, support/resistance, session levels, ATR levels, events."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import engine as en
from .. import indicators as ind
from .base import P, color, plot, study, level, GRAY, PURPLE, TEAL, AMBER, ORANGE, RED, GREEN


FIB_RATIOS = (0.382, 0.5, 0.618)


def session_profile(rth: pd.DataFrame, bin_size: float) -> dict | None:
    """POC / VAH / VAL of today's regular hours, each bar's volume at its typical price (Session levels' option;
    the Volume profile study has its own row settings)."""
    if rth.empty or rth["volume"].sum() <= 0:
        return None
    tp = (rth["high"] + rth["low"] + rth["close"]) / 3
    prof = rth.assign(bin=np.round(tp / bin_size) * bin_size).groupby("bin")["volume"].sum().sort_index()
    poc, i, j = ind.value_area(prof.to_numpy())
    prices = prof.index
    return {"poc": float(prices[poc]), "vah": float(prices[j]), "val": float(prices[i])}


LADDER_METHODS = ["Fibonacci extension (1.272 / 1.618)", "ATR extension (0.5 / 1.0 ATR)", "Classic pivots"]


def ladder(method, H, L, C, anchor_hi, anchor_lo, atr):
    """Pivot plus R1/R2 above and S1/S2 below. The extension methods guarantee R2 > R1 > anchor high and
    S2 < S1 < anchor low; classic pivot formulas don't (R1 can sit below the prior high)."""
    piv = (H + L + C) / 3
    rng = H - L
    if method.startswith("ATR") and atr:
        r1, r2, s1, s2 = anchor_hi + 0.5 * atr, anchor_hi + atr, anchor_lo - 0.5 * atr, anchor_lo - atr
    elif method.startswith("Classic"):
        r1, r2, s1, s2 = 2 * piv - L, piv + rng, 2 * piv - H, piv - rng
    else:
        r1, r2, s1, s2 = anchor_hi + 0.272 * rng, anchor_hi + 0.618 * rng, anchor_lo - 0.272 * rng, anchor_lo - 0.618 * rng
    return piv, r1, r2, s1, s2


def near_filter(ctx, p, levels):
    if not p.get("near_only"):
        return levels
    near = (ctx.atr or ctx.price * 0.02) * p["near_atr"]
    return [lv for lv in levels if abs(lv["price"] - ctx.price) <= near]


NEAR_PARAMS = [P("near_only", "Only levels near price", "bool", False, section="Display"),
               P("near_atr", "Near = within N x ATR", "float", 1.0, min=0.2, max=5, step=0.1, section="Display"),
               P("flip_closes", "5-min closes to mark a flip (0 = off)", "int", 2, min=0, max=6, section="Display")]


@study("prior_day", "Prior day levels (PH, PL, PC, PO)", "Levels", "price",
       [P("ph", "PH: prior-day high", "bool", True), P("pl", "PL: prior-day low", "bool", True),
        P("pc", "PC: prior-day close", "bool", True), P("po", "PO: prior-day open", "bool", True),
        P("pw", "Prior week high / low", "bool", False), P("fibs", "Prior-day Fibonacci (38.2 / 50 / 61.8)", "bool", False),
        *NEAR_PARAMS],
       lambda p: "Prior day (" + ", ".join(k.upper() for k in ("ph", "pl", "pc", "po") if p[k]) + ")",
       "Prior-day high, low, close and open, with optional prior-week range and Fibonacci retracements.",
       plots=[plot("ph", "PH", GRAY, 1), plot("pl", "PL", GRAY, 1), plot("pc", "PC", GRAY, 1, "dashed"),
              plot("po", "PO", GRAY, 1, "dotted"), plot("pw", "Prior week", GRAY, 1, "large_dashed"),
              plot("fib", "Fibonacci", GRAY, 1, "sparse_dotted")], intraday=True)
def _prior_day(ctx, p):
    row = ctx.pd_row
    if row is None:
        return {"levels": [], "note": "no prior day cached"}
    O, H, L, C = (float(row[k]) for k in ("open", "high", "low", "close"))
    f = p["flip_closes"]
    lv = [level(p, k, v, k.upper(), ctx, f) for k, v in (("ph", H), ("pl", L), ("pc", C), ("po", O)) if p[k]]
    if p["pw"]:
        d = ctx.daily
        cur_week = pd.Timestamp(ctx.day).isocalendar()[:2]
        wk = d.assign(wk=[tuple(pd.Timestamp(x).isocalendar()[:2]) for x in d["date"]])
        prev = wk[wk["wk"] < cur_week]
        if not prev.empty:
            w = prev[prev["wk"] == prev["wk"].iloc[-1]]
            lv += [level(p, "pw", w["high"].max(), "PW high", ctx, f), level(p, "pw", w["low"].min(), "PW low", ctx, f)]
    if p["fibs"]:
        lv += [level(p, "fib", L + r * (H - L), f"PD fib {r * 100:g}") for r in FIB_RATIOS]
    return {"levels": near_filter(ctx, p, lv)}


@study("sr_ladder", "Support / resistance (Pivot, R1-R2, S1-S2)", "Levels", "price",
       [P("method", "Method", "choice", LADDER_METHODS[0], options=LADDER_METHODS),
        P("dynamic", "Dynamic: move R up past today's high, S down past today's low", "bool", True),
        P("pivot", "Show pivot", "bool", True), P("resistance", "Show R1 / R2", "bool", True),
        P("support", "Show S1 / S2", "bool", True), *NEAR_PARAMS],
       lambda p: "S/R (" + p["method"].split(" (")[0] + (", dynamic" if p["dynamic"] and not p["method"].startswith("Classic") else "") + ")",
       "Pivot with R2 > R1 > prior high and S2 < S1 < prior low (extension methods), optionally moving with today's range.",
       plots=[plot("pivot", "Pivot", AMBER), plot("r1", "R1", RED), plot("r2", "R2", RED, 2),
              plot("s1", "S1", GREEN), plot("s2", "S2", GREEN, 2)], intraday=True)
def _sr_ladder(ctx, p):
    row = ctx.pd_row
    if row is None:
        return {"levels": [], "note": "no prior day cached"}
    H, L, C = (float(row[k]) for k in ("high", "low", "close"))
    hod, lod = ctx.hod_lod
    dynamic = p["dynamic"] and not p["method"].startswith("Classic") and hod is not None
    hi = max(H, hod) if dynamic else H
    lo = min(L, lod) if dynamic else L
    piv, r1, r2, s1, s2 = ladder(p["method"], H, L, C, hi, lo, ctx.atr)
    f = p["flip_closes"]
    lv = []
    if p["pivot"]:
        lv.append(level(p, "pivot", piv, "Pivot", ctx, f))
    if p["resistance"]:
        moved = dynamic and hi > H
        lv += [level(p, "r1", r1, "R1", ctx, f, moved), level(p, "r2", r2, "R2", ctx, f, moved)]
    if p["support"]:
        moved = dynamic and lo < L
        lv += [level(p, "s1", s1, "S1", ctx, f, moved), level(p, "s2", s2, "S2", ctx, f, moved)]
    return {"levels": near_filter(ctx, p, lv)}


@study("session_levels", "Session levels (premarket, opening range, HOD/LOD, profile)", "Levels", "price",
       [P("premarket", "Premarket high / low", "bool", True),
        P("opening_range", "Opening range levels", "bool", True), P("or_box", "Opening range box", "bool", True),
        P("or_minutes", "Opening range length", "choice", "15", options=["5", "15", "30"]),
        P("hod_lod", "High / low of day", "bool", True),
        P("profile", "Volume profile (POC, VAH, VAL)", "bool", False),
        P("day_fibs", "Day Fibonacci (once range is 40% of ATR)", "bool", False),
        P("projection", "Remaining expected range (ATR)", "bool", True), *NEAR_PARAMS],
       lambda p: "Session levels",
       "Levels built during today's session: premarket range, opening range, high/low of day, volume profile, "
       "day Fibonacci and the remaining expected range.",
       plots=[plot("pm", "Premarket", PURPLE), plot("orl", "Opening range", PURPLE, 1, "dashed"),
              plot("hl", "High / low of day", TEAL, 1, "dotted"), plot("vp", "Volume profile", TEAL, 1, "sparse_dotted"),
              plot("dfib", "Day Fibonacci", TEAL, 1, "dotted"), plot("proj", "Expected range", TEAL, 1, "large_dashed"),
              plot("box", "Opening range box", PURPLE, 1, "solid")], intraday=True)
def _session_levels(ctx, p):
    f = p["flip_closes"]
    lv = []
    if p["premarket"] and not ctx.pre.empty:
        tag = "" if ctx.cursor >= en.RTH_START else " (building)"
        lv += [level(p, "pm", ctx.pre["high"].max(), "PM high" + tag, ctx, f),
               level(p, "pm", ctx.pre["low"].min(), "PM low" + tag, ctx, f)]
    orr = ctx.opening_range(int(p["or_minutes"]))
    if orr and p["opening_range"]:
        tag = "" if orr["complete"] else " (building)"
        lv += [level(p, "orl", orr["high"], "OR high" + tag), level(p, "orl", orr["low"], "OR low" + tag)]
    hod, lod = ctx.hod_lod
    if hod is not None:
        if p["hod_lod"]:
            lv += [level(p, "hl", hod, "HOD"), level(p, "hl", lod, "LOD")]
        if p["profile"]:
            prof = session_profile(ctx.rth, max(0.01, round((ctx.atr or ctx.price * 0.01) / 80, 2)))
            if prof:
                lv += [level(p, "vp", prof["poc"], "POC"), level(p, "vp", prof["vah"], "VAH"), level(p, "vp", prof["val"], "VAL")]
        if p["day_fibs"] and ctx.atr and (hod - lod) >= 0.4 * ctx.atr:
            up_swing = ctx.rth["high"].idxmax() > ctx.rth["low"].idxmin()
            lv += [level(p, "dfib", hod - r * (hod - lod) if up_swing else lod + r * (hod - lod), f"Day fib {r * 100:g}")
                   for r in FIB_RATIOS]
    out = {"levels": near_filter(ctx, p, lv)}
    if p["projection"] and ctx.projection:
        pr = ctx.projection
        out["levels"] += [level(p, "proj", pr["up"], "Range max \u2191"), level(p, "proj", pr["down"], "Range max \u2193")]
    if orr and p["or_box"]:
        out["box"] = {**orr, "plot": "box",
                      "label": f"Opening range ({orr['minutes']}m)" + ("" if orr["complete"] else ", building")}
    return out



# ---------------------------------------------------------------- Initial Balance
IB_EXTENSIONS = {"Off": (), "1x and 2x": (1.0, 2.0), "0.5x steps to 2x": (0.5, 1.0, 1.5, 2.0),
                 "1x, 1.5x, 2x, 3x": (1.0, 1.5, 2.0, 3.0)}


def ib_state(high: float, low: float, day_high: float, day_low: float) -> str:
    """How far the session has traded beyond the Initial Balance: inside it, out one side (by how many IB ranges)
    or out both sides. A description of the day so far, not a signal."""
    rng = high - low
    up, down = day_high > high, day_low < low
    if up and down:
        return "traded out both sides"
    if not (up or down) or rng <= 0:
        return "inside the IB so far"
    beyond = (day_high - high) if up else (low - day_low)
    return f"extended {'up' if up else 'down'} {beyond / rng:.1f}x the IB range"


@study("initial_balance", "Initial Balance", "Levels", "price",
       [P("minutes", "Initial Balance length (minutes from 09:30)", "choice", "60", options=["30", "60", "90"]),
        P("mid", "IB midpoint", "bool", True),
        P("extensions", "Range extensions (multiples of the IB range)", "choice", "1x and 2x", options=list(IB_EXTENSIONS)),
        P("box", "Shade the IB period", "bool", True)],
       lambda p: f"Initial Balance ({p['minutes']}m)",
       "The high and low of the first hour of regular trading (09:30-10:30 by default), its midpoint, and range "
       "extensions at multiples of the IB range above the high and below the low. The legend says whether the "
       "session has stayed inside the IB or extended beyond it, and how far.",
       plots=[plot("ib", "IB high / low", AMBER, 2), plot("mid", "IB midpoint", AMBER, 1, "dotted"),
              plot("ext", "Range extensions", AMBER, 1, "dashed"), plot("box", "IB box", AMBER, 1, "solid")],
       intraday=True)
def _initial_balance(ctx, p):
    ib = ctx.opening_range(int(p["minutes"]))
    if not ib:
        return {"levels": [], "note": "starts at 09:30"}
    hi, lo, rng = ib["high"], ib["low"], ib["high"] - ib["low"]
    tag = "" if ib["complete"] else " (building)"
    lv = [level(p, "ib", hi, "IB high" + tag, ctx), level(p, "ib", lo, "IB low" + tag, ctx)]
    if p["mid"]:
        lv.append(level(p, "mid", (hi + lo) / 2, "IB mid" + tag, ctx))
    if ib["complete"] and rng > 0:
        for k in IB_EXTENSIONS[p["extensions"]]:
            lv += [level(p, "ext", hi + k * rng, f"IB +{k:g}x", ctx), level(p, "ext", lo - k * rng, f"IB \u2212{k:g}x", ctx)]
    out = {"levels": lv}
    if p["box"]:
        out["box"] = {**ib, "plot": "box", "label": f"Initial Balance ({ib['minutes']}m)" + ("" if ib["complete"] else ", building")}
    hod, lod = ctx.hod_lod
    out["note"] = (f"range {rng:.2f}, building" if not ib["complete"]
                   else f"range {rng:.2f}, {ib_state(hi, lo, hod, lod)}")
    return out

# ---------------------------------------------------------------- Saty ATR levels
ATR_FIBS = (0.382, 0.5, 0.618, 0.786)
ATR_EXTS = (1.236, 1.382, 1.5, 1.618, 1.786, 2.0)


def atr_ladder(pc: float, atr: float, trigger_pct: float = 23.6) -> dict:
    """Price of each ATR level, keyed by its fraction of ATR (negative = below the prior close)."""
    t = round(trigger_pct / 100, 6)
    out = {0: pc, t: pc + t * atr, -t: pc - t * atr}
    for r in (*ATR_FIBS, 1.0, *ATR_EXTS):
        out[r], out[-r] = pc + r * atr, pc - r * atr
    return out


@study("saty_atr", "ATR levels (Saty-style)", "Levels", "price",
       [P("atr_length", "Daily ATR length", "int", 14, min=2, max=100),
        P("trigger", "Trigger % of ATR", "float", 23.6, min=1, max=100, step=0.1),
        P("fibs", "Show 38.2 / 50 / 61.8 / 78.6% levels", "bool", True),
        P("extensions", "Show extensions to 2 ATR", "bool", True),
        P("range_session", "Day range measured on", "choice", "Regular hours", options=["Regular hours", "All sessions"]),
        P("labels", "Show info labels", "bool", True),
        color("#d32f2f", "header_bg", "Header label"), color("#f9d65c", "range_bg", "Day range label"),
        P("near_only", "Only levels near price", "bool", False, section="Display"),
        P("near_atr", "Near = within N x ATR", "float", 1.0, min=0.2, max=5, step=0.1, section="Display")],
       lambda p: f"ATR levels ({p['atr_length']}, {p['trigger']:g}%)",
       "Levels at fractions of the daily ATR above and below the prior close, as in Saty Mahajan's ATR Levels: "
       "the trigger (23.6%), Fibonacci steps, plus/minus 1 ATR and optional extensions to 2 ATR.",
       plots=[plot("close", "Prior close", "#e53935", 2), plot("calls", "Calls trigger", "#26c6da", 2),
              plot("puts", "Puts trigger", "#f9a825", 2), plot("fib", "Fibonacci steps", "#9e9e9e", 1),
              plot("atr_up", "+1 ATR", "#ff9800", 2), plot("atr_dn", "-1 ATR", "#ff9800", 2),
              plot("ext", "Extensions", "#9e9e9e", 1, "dashed")], intraday=True)
def _saty_atr(ctx, p):
    d = ctx.daily
    if len(d) < 2:
        return {"levels": [], "note": "needs prior daily bars"}
    atr = float(ind.atr(d.astype({"high": float, "low": float, "close": float}).reset_index(drop=True),
                        p["atr_length"]).iloc[-1]) if len(d) >= p["atr_length"] else None
    if atr is None or math.isnan(atr):
        return {"levels": [], "note": f"needs {p['atr_length']} daily bars, have {len(d)}"}
    pc = float(d["close"].iloc[-1])
    t = round(p["trigger"] / 100, 6)
    lad = atr_ladder(pc, atr, p["trigger"])
    lv = [level(p, "close", lad[0], "Prior close"),
          level(p, "calls", lad[t], f"Calls > ({p['trigger']:g}%)"),
          level(p, "puts", lad[-t], f"Puts < ({p['trigger']:g}%)"),
          level(p, "atr_up", lad[1.0], "+1 ATR"), level(p, "atr_dn", lad[-1.0], "-1 ATR")]
    if p["fibs"]:
        for r in ATR_FIBS:
            lv += [level(p, "fib", lad[r], f"+{r * 100:g}%"), level(p, "fib", lad[-r], f"-{r * 100:g}%")]
    if p["extensions"]:
        for r in ATR_EXTS:
            lv += [level(p, "ext", lad[r], f"+{r:g} ATR"), level(p, "ext", lad[-r], f"-{r:g} ATR")]
    out = {"levels": near_filter(ctx, p, lv) if p["near_only"] else lv}
    if p["labels"]:
        if p["range_session"] == "Regular hours":
            hi, lo = ctx.hod_lod
        else:
            hi, lo = float(ctx.cut["high"].max()), float(ctx.cut["low"].min())
        labels = [{"text": "ATR Levels", "bg": p["header_bg"]}]
        if hi is not None:
            rng = hi - lo
            labels.append({"text": f"Day Range (${rng:.2f}) is {rng / atr * 100:.0f}% of ATR (${atr:.2f})", "bg": p["range_bg"]})
        else:
            labels.append({"text": f"ATR ${atr:.2f}; day range starts at 09:30", "bg": p["range_bg"]})
        labels += [{"text": f"Calls > ${pc + t * atr:.2f} | +1 ATR: ${pc + atr:.2f}", "bg": p["calls_color"]},
                   {"text": f"Puts < ${pc - t * atr:.2f} | -1 ATR: ${pc - atr:.2f}", "bg": p["puts_color"]}]
        out["labels"] = labels
    return out


@study("events", "Events", "Levels", "price",
       [P("scheduled", "Scheduled events", "bool", True), P("headlines", "Headlines", "bool", True),
        P("moves", "Significant moves (tools/market_events.py)", "bool", True)],
       lambda p: "Events", "Vertical lines for entries in data/events.json, drawn into the future too. "
       "tools/market_events.py adds scheduled releases and the day's significant moves with their likely cause.",
       plots=[plot("scheduled", "Scheduled event lines", PURPLE, 1, "dashed"),
              plot("headline", "Headline lines", PURPLE, 1, "dotted"),
              plot("move", "Significant move lines", ORANGE, 1, "solid")], intraday=True)
def _events(ctx, p):
    keep = {k for k, on in (("scheduled", p["scheduled"]), ("headline", p["headlines"]), ("move", p["moves"])) if on}
    out = []
    for e in ctx.events:
        kind = e.get("kind", "scheduled")
        if kind in keep:
            out.append({"time": e["chart_time"], "label": f"{e['time']} {e['label']}", "kind": kind, "plot": kind})
    return {"verticals": out}
