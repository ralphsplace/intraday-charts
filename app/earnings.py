"""Earnings view: how a stock traded around its last earnings reports, each report as one line.

One job: daily bars and earnings dates in, aligned windows out. Each window covers some trading days before the
reaction day and some after (10 and 5 unless the page asks for others, up to MAX_DAYS each). Every point carries both views the page can switch between:
  price  the close, adjusted for splits (IBKR's daily bars already are; see window() for the safety net)
  pct    % change from the close of the day before the reaction day (day -1), so every quarter starts from 0%
         whatever the share price was then, and a re-rated stock doesn't spread the lines

Day 0 is the reaction day: the first regular session that trades on the news (the report day for reports before
the open or during the session; the next session for reports after the close).

Earnings dates come from data/earnings/<SYMBOL>.json, written by the TWS collector (SEC EDGAR, see
tools/earnings_sources.py), or by hand for companies that don't file with the SEC:
    {"symbol": "ASML", "source": "by hand", "fetched": 0, "status": "ok",
     "earnings": [{"date": "2026-07-15", "time": "07:00"}, ...]}       (US/Eastern time of the report)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from . import store

QUARTERS = 6               # earnings reports shown
BEFORE, AFTER = 10, 5      # trading days around the reaction day, unless the page asks for others
MAX_DAYS = 60              # the most either side (the collector keeps 2 years of daily prices)
OPEN, CLOSE = "09:30", "16:00"
CLUSTER_DAYS = 45          # Item 2.02 filings this close together are one report (e.g. a preliminary-results notice)
REFRESH_SECONDS = 3 * 86400
SPLIT_RATIOS = (2, 3, 4, 5, 10, 20)
SPLIT_TOLERANCE = 0.015


# ---------------------------------------------------------------- cache of earnings dates
def path(symbol: str) -> Path:
    return store.DATA_DIR / "earnings" / f"{symbol.upper()}.json"


def read(symbol: str) -> dict | None:
    try:
        d = json.loads(path(symbol).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def write(symbol: str, data: dict) -> None:
    p = path(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"symbol": symbol.upper(), **data}, indent=1))
    tmp.replace(p)


def is_stale(symbol: str, now: float | None = None) -> bool:
    """Time to look the dates up again: never looked up, older than REFRESH_SECONDS, or a failed lookup an
    hour ago. A file written by hand (no "fetched") is never replaced."""
    d = read(symbol)
    if d is None:
        return True
    if not d.get("fetched"):
        return False
    age = (now or time.time()) - float(d["fetched"])
    return age > (3600 if d.get("status") == "error" else REFRESH_SECONDS)


# ---------------------------------------------------------------- which reports, and their reaction days
def timing(t: str) -> str:
    return "before the open" if t < OPEN else ("during the session" if t < CLOSE else "after the close")


def reports(earnings: list[dict]) -> list[dict]:
    """Earnings reports newest first. Filings within CLUSTER_DAYS of each other count as one report, the latest
    of them (a preliminary-results notice comes before the full report)."""
    rows = sorted((e for e in earnings if e.get("date")), key=lambda e: (e["date"], e.get("time") or ""))
    kept: list[dict] = []
    for e in rows:
        if kept and (pd.Timestamp(e["date"]) - pd.Timestamp(kept[-1]["date"])).days < CLUSTER_DAYS:
            kept[-1] = e
        else:
            kept.append(e)
    return kept[::-1]


def reaction_index(dates: list[str], report: dict) -> int | None:
    """Row of the reaction day in the daily bars (dates are trading days, oldest first), or None if it hasn't
    traded yet."""
    after_close = (report.get("time") or "00:00") >= CLOSE
    for i, d in enumerate(dates):
        if d > report["date"] or (d == report["date"] and not after_close):
            return i
    return None


# ---------------------------------------------------------------- the windows
def split_factor(ratio: float) -> float | None:
    """The split a day-over-day close ratio looks like (e.g. 0.1 -> 10 for a 10:1 split), if any."""
    for k in SPLIT_RATIOS:
        for f in (k, 1 / k):
            if abs(ratio * f - 1) < SPLIT_TOLERANCE:
                return f
    return None


def window(daily: pd.DataFrame, i0: int, before: int = BEFORE, after: int = AFTER) -> dict | None:
    """Closes from `before` days before to `after` days after row i0: split-adjusted price, and % change from the
    close at i0 - 1. IBKR's daily bars are already split-adjusted; if one window still shows a jump the size of a
    split, the closes before it are adjusted (in both views) and the window says so."""
    if i0 < 1:
        return None
    lo, hi = max(0, i0 - before), min(len(daily) - 1, i0 + after)
    rows = daily.iloc[lo:hi + 1]
    closes = [float(c) for c in rows["close"]]
    splits = []
    for k in range(len(closes) - 1, 0, -1):       # adjust earlier closes for any split found
        f = split_factor(closes[k] / closes[k - 1]) if closes[k - 1] else None
        if f:
            splits.append({"date": str(rows["date"].iloc[k]), "ratio": f"{f:g}:1" if f >= 1 else f"1:{1 / f:g}"})
            closes[:k] = [c * (1 / f) for c in closes[:k]]
    base = closes[i0 - 1 - lo]
    if not base:
        return None
    points = [{"x": lo + n - i0, "date": str(d), "price": round(c, 4), "pct": round((c / base - 1) * 100, 3)}
              for n, (d, c) in enumerate(zip(rows["date"], closes, strict=True))]
    return {"points": points, "splits": splits[::-1]}


def view(symbol: str, quarters: int = QUARTERS, before: int = BEFORE, after: int = AFTER) -> dict:
    """The earnings view for one symbol: up to `quarters` windows of `before` trading days before day 0 and `after`
    after, newest first, or a status saying what's missing."""
    if not (1 <= before <= MAX_DAYS and 1 <= after <= MAX_DAYS):
        raise ValueError(f"days before and after must each be 1 to {MAX_DAYS}")
    symbol = symbol.upper()
    cache, daily = read(symbol), store.read_daily(symbol)
    out = {"symbol": symbol, "before": before, "after": after, "max_days": MAX_DAYS, "quarters": [],
           "source": (cache or {}).get("source"), "fetched": (cache or {}).get("fetched")}
    missing = [what for what, have in (("earnings dates", cache is not None), ("daily prices", not daily.empty)) if not have]
    if missing:
        return {**out, "status": "missing", "missing": missing}
    if cache.get("status") not in (None, "ok"):
        return {**out, "status": cache["status"], "message": cache.get("message", "")}
    dates = [str(d) for d in daily["date"]]
    for r in reports(cache.get("earnings") or []):
        if len(out["quarters"]) >= quarters:
            break
        i0 = reaction_index(dates, r)
        w = None if i0 is None else window(daily, i0, before, after)
        if not w:
            continue
        move = next((p["pct"] for p in w["points"] if p["x"] == 0), None)
        out["quarters"].append({"report_date": r["date"], "report_time": r.get("time") or "", "timing": timing(r.get("time") or "00:00"),
                                "day0": dates[i0], "move": move, **w})
    if not out["quarters"]:
        return {**out, "status": "no_earnings",
                "message": f"No earnings reports for {symbol} fall within the cached daily prices."
                if cache.get("earnings") else f"No earnings reports found for {symbol} (funds and ETFs don't report earnings)."}
    return {**out, "status": "ok"}
