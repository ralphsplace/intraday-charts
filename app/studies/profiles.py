"""Price profiles: the volume profile (how much traded at each price) and the TPO / Market Profile (how long price
spent at each price). Both share the row settings (rows across the range, ticks, or a price per row), the value
area, the POC / VAH / VAL lines and the chart's profile drawing; they differ only in what each row counts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import engine as en
from .. import indicators as ind
from .base import P, color, plot, study, level, PINK, PURPLE

ROW_MODES = ["Number of rows", "Tick size", "Custom price per row"]
MAX_ROWS = 1500
VP_ROW_MODES, VP_MAX_ROWS = ROW_MODES, MAX_ROWS          # the names the volume profile has always used


def row_params(side: str, va_color: str, out_color: str) -> list[dict]:
    """The settings every profile has: row height, value area, where and how it's drawn."""
    return [P("row_mode", "Row height", "choice", ROW_MODES[0], options=ROW_MODES),
            P("rows", "Rows (Number of rows)", "int", 60, min=10, max=200),
            P("ticks", "Ticks per row (Tick size)", "int", 1, min=1, max=500),
            P("tick_size", "Tick size $", "float", 0.01, min=0.0001, max=10, step=0.01),
            P("row_price", "Price per row $ (Custom)", "float", 0.05, min=0.001, max=50, step=0.01),
            P("va_pct", "Value area %", "int", 70, min=10, max=95),
            P("side", "Side", "choice", side, options=["Left", "Right"]),
            P("width_pct", "Width (% of chart)", "int", 25, min=5, max=60),
            P("lines", "Show POC / VAH / VAL lines", "bool", True),
            color(va_color, "va_color", "Value area bars"), color(out_color, "out_color", "Other bars"),
            P("opacity", "Bar opacity %", "int", 45, min=5, max=100, section="Style")]


def rows_label(p) -> str:
    return {"Tick size": f", {p['ticks']} tick{'s' if p['ticks'] > 1 else ''}/row",
            "Custom price per row": f", ${p['row_price']:g}/row"}.get(p["row_mode"], "")


class Rows:
    """The price rows of one profile between lo and hi, as the row settings ask."""

    def __init__(self, lo: float, hi: float, p: dict):
        self.note = None
        self.by_rows = p["row_mode"] == "Number of rows"
        if self.by_rows:
            self.n = p["rows"]
            self.step = (hi - lo) / self.n
            self.base = lo                                   # rows [lo + k*step, lo + (k+1)*step)
        else:
            step = p["ticks"] * p["tick_size"] if p["row_mode"] == "Tick size" else p["row_price"]
            if (hi - lo) / step + 1 > MAX_ROWS:              # keep the drawing light on wide ranges
                step *= int(np.ceil((hi - lo) / step / MAX_ROWS))
                self.note = f"rows widened to ${step:g} to stay under {MAX_ROWS} rows"
            self.step = step
            self.base = np.floor(lo / step + 0.5) * step     # rows centred on price multiples of the row height
            self.n = int(np.floor(hi / step + 0.5) - np.floor(lo / step + 0.5)) + 1

    def index(self, x: np.ndarray) -> np.ndarray:
        if self.by_rows:
            return np.minimum(((x - self.base) / self.step).astype(int), self.n - 1)
        return np.clip(np.floor((x - self.base) / self.step + 0.5).astype(int), 0, self.n - 1)

    def mid(self, k) -> float:
        return self.base + (k + 0.5) * self.step if self.by_rows else self.base + k * self.step

    def edge_lo(self, k) -> float:
        return self.mid(k) - self.step / 2

    def spread(self, lows: np.ndarray, highs: np.ndarray, amounts: np.ndarray) -> np.ndarray:
        """Each amount spread evenly over the rows between its low and high (amount per row, summed)."""
        i0, i1 = self.index(lows), self.index(highs)
        share = amounts / (i1 - i0 + 1)
        diff = np.zeros(self.n + 1)
        np.add.at(diff, i0, share)
        np.add.at(diff, i1 + 1, -share)
        return np.cumsum(diff)[:self.n]

    def value_lines(self, counts: np.ndarray, va_pct: float) -> tuple[float, float, float, int, int]:
        """POC, VAH, VAL prices, and the value area's first and last rows."""
        poc_i, i, j = ind.value_area(counts, va_pct / 100)
        vah = self.edge_lo(j) + self.step if self.by_rows else self.mid(j)   # row edges; otherwise the rows' prices
        val = self.edge_lo(i) if self.by_rows else self.mid(i)
        return float(self.mid(poc_i)), float(vah), float(val), i, j


def profile_output(p: dict, rows: Rows, counts: np.ndarray, names=("POC", "VAH", "VAL")) -> dict:
    """The chart's profile drawing, plus POC / VAH / VAL lines when switched on."""
    poc, vah, val, i, j = rows.value_lines(counts, p["va_pct"])
    out = {"profile": {"bins": [{"lo": round(float(rows.edge_lo(k)), 4), "hi": round(float(rows.edge_lo(k) + rows.step), 4),
                                 "vol": round(float(counts[k]), 1), "va": bool(i <= k <= j)}
                                for k in range(rows.n) if counts[k] > 0 or rows.n <= 400],
                       "side": p["side"].lower(), "width_pct": p["width_pct"], "va_color": p["va_color"],
                       "out_color": p["out_color"], "opacity": p["opacity"] / 100}}
    if rows.note:
        out["note"] = rows.note
    if p["lines"]:
        out["levels"] = [level(p, "poc_line", round(poc, 4), names[0]), level(p, "va_lines", round(vah, 4), names[1]),
                         level(p, "va_lines", round(val, 4), names[2])]
    return out


def range_bars(ctx, choice: str) -> pd.DataFrame:
    """The 1-minute bars a profile covers: today (all sessions or regular hours) or every shown day."""
    if choice == "All shown days":
        return pd.concat([ctx.minute_bars(d) for d in ctx.shown_prior_days] + [ctx.cut], ignore_index=True)
    return ctx.rth if choice == "Today, regular hours" else ctx.cut


# ---------------------------------------------------------------- volume profile
@study("volume_profile", "Volume profile", "Profiles", "price",
       [P("range", "Range", "choice", "Today, all sessions",
          options=["Today, all sessions", "Today, regular hours", "All shown days"]),
        *row_params("Left", "#26a69a", "#5f6b7a")],
       lambda p: (f"Volume profile ({p['range'].split(',')[0].lower()}{', RTH' if 'regular' in p['range'] else ''}"
                  + rows_label(p) + ")"),
       "Volume traded at each price as a horizontal histogram, with point of control and value area. Row height: "
       "a fixed number of rows across the range, one row per price tick (QQQ: $0.01) or a few ticks, or a "
       "custom price per row, like thinkorswim's row-height modes. Each bar's volume is spread evenly over "
       "the rows between its low and high.",
       plots=[plot("poc_line", "POC line", "#ef5350", 2, "dotted"), plot("va_lines", "VAH / VAL lines", "#e6b450", 1, "dashed")],
       intraday=True)
def _volume_profile(ctx, p):
    bars = range_bars(ctx, p["range"])
    if bars.empty or bars["volume"].sum() <= 0:
        return {"note": "no volume yet"}
    lo, hi = float(bars["low"].min()), float(bars["high"].max())
    if hi <= lo:
        return {"note": "no price range yet"}
    rows = Rows(lo, hi, p)
    vol = rows.spread(bars["low"].to_numpy(dtype=float), bars["high"].to_numpy(dtype=float),
                      bars["volume"].to_numpy(dtype=float))
    return profile_output(p, rows, vol)


# ---------------------------------------------------------------- TPO / Market Profile
TPO_RANGES = ["Today, regular hours", "Today, all sessions", "All shown days"]


def tpo_counts(bars: pd.DataFrame, rows: Rows, period: int, start: int) -> np.ndarray:
    """Time at price: for every period (e.g. 30 minutes from `start`) each row its range touched counts 1."""
    m = en.minute_of_day(bars["time"])
    key = bars["time"].dt.strftime("%Y%m%d").astype("int64").to_numpy() * 10_000 + ((m - start) // period).to_numpy()
    g = bars.assign(k=key).groupby("k").agg(low=("low", "min"), high=("high", "max"))
    i0, i1 = rows.index(g["low"].to_numpy(dtype=float)), rows.index(g["high"].to_numpy(dtype=float))
    diff = np.zeros(rows.n + 1)
    np.add.at(diff, i0, 1.0)
    np.add.at(diff, i1 + 1, -1.0)
    return np.cumsum(diff)[:rows.n]


def tpo_of(bars: pd.DataFrame, p: dict, start: int):
    """(rows, counts) of a TPO profile of these bars, or None when they have no range."""
    if bars.empty:
        return None
    lo, hi = float(bars["low"].min()), float(bars["high"].max())
    if hi <= lo:
        return None
    rows = Rows(lo, hi, p)
    return rows, tpo_counts(bars, rows, int(p["period"]), start)


def rth_of(bars: pd.DataFrame) -> pd.DataFrame:
    m = en.minute_of_day(bars["time"])
    return bars[(m >= en.RTH_START) & (m < en.RTH_END)]


@study("tpo", "TPO / Market Profile", "Profiles", "price",
       [P("range", "Range", "choice", TPO_RANGES[0], options=TPO_RANGES),
        P("period", "Period (minutes per TPO)", "choice", "30", options=["5", "15", "30", "60"]),
        P("prior", "Prior day POC / VAH / VAL", "bool", True),
        P("naked", "Naked POCs from the last N days (0 = off)", "int", 5, min=0, max=20),
        *row_params("Right", "#9b8cff", "#4a4f66")],
       lambda p: f"TPO ({p['range'].split(',')[0].lower()}{', RTH' if 'regular' in p['range'] else ''}, {p['period']}m"
                 + rows_label(p) + ")",
       "Market Profile: how many periods (30 minutes by default) price spent at each price, as a horizontal "
       "histogram with its own POC and value area. The volume profile shows how much traded at a price; this "
       "shows how long price stayed there. Drawn on the right by default, so both fit side by side. The prior "
       "day's regular-hours POC, VAH and VAL carry forward, and naked POCs are earlier days' POCs that price "
       "hasn't traded through since.",
       plots=[plot("poc_line", "POC line", PURPLE, 2, "dotted"), plot("va_lines", "VAH / VAL lines", PURPLE, 1, "dashed"),
              plot("prior", "Prior day POC / VAH / VAL", PURPLE, 1, "large_dashed"), plot("naked", "Naked POCs", PINK, 1, "dotted")],
       intraday=True)
def _tpo(ctx, p):
    start = en.RTH_START if p["range"] == "Today, regular hours" else en.PRE_START
    today = tpo_of(range_bars(ctx, p["range"]), p, start)
    out = profile_output(p, *today, names=("TPO POC", "TPO VAH", "TPO VAL")) if today else {"note": "no price range yet"}
    lv = out.setdefault("levels", [])
    days = ctx.prior_days[-max(int(p["naked"]), 1):]
    prof = {d: tpo_of(rth_of(ctx.minute_bars(d)), p, en.RTH_START) for d in days}
    if p["prior"] and days and prof[days[-1]]:
        poc, vah, val, _, _ = prof[days[-1]][0].value_lines(prof[days[-1]][1], p["va_pct"])
        lv += [level(p, "prior", poc, "pPOC", ctx), level(p, "prior", vah, "pVAH", ctx), level(p, "prior", val, "pVAL", ctx)]
    if p["naked"]:
        later = {d: rth_of(ctx.minute_bars(d)) for d in days}
        for n, d in enumerate(days):
            if not prof[d] or (p["prior"] and d == days[-1]):   # the prior day's POC is drawn as pPOC
                continue
            poc = prof[d][0].value_lines(prof[d][1], p["va_pct"])[0]
            after = [later[x] for x in days[n + 1:]] + [ctx.rth]
            if not any(((b["low"] <= poc) & (b["high"] >= poc)).any() for b in after if not b.empty):
                lv.append(level(p, "naked", poc, f"nPOC {d[5:]}", ctx))
    return out
