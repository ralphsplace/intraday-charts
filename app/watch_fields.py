"""The columns a watch list can show, and their values per symbol: one registry for the server and the page.

One job: a symbol, a day (up to the Replay cursor) and the columns a tab shows in; the row of values out. Each
column belongs to a group, and only the groups the tab needs are worked out (a list without sparklines never
pays for them). No network: cached 1-minute and daily bars, the earnings and options caches, the market
calendar, and study values (study_values.py).

A column: id, label, kind (how the page writes or draws it), group (what computes it), lists (which lists
have it: "all", "holding" for the Holdings list, "finviz" for FinViz lists), tip (what it is), and for
graphical kinds a scale.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import earnings, engine, expected_move, option_chain, quotes, store, study_values
from .studies.levels import ATR_EXTS, ATR_FIBS, atr_ladder, ib_state

RTH_START, RTH_END = engine.RTH_START, engine.RTH_END
RVOL_SESSIONS = 10
SPARK_POINTS = 78
CALENDAR = Path(__file__).resolve().parent / "data" / "market_calendar.json"


def col(id, label, kind, group, tip="", lists="all", **kw):
    return {"id": id, "label": label, "kind": kind, "group": group, "tip": tip, "lists": lists, **kw}


# study columns: (id, label, spec). The value is the study's line at the cursor; "vs" is the last price's distance.
STUDIES = [
    ("sma20_5m", "SMA 20 (5m)", {"type": "sma", "params": {"length": 20}, "output": "sma", "tf": 5}),
    ("sma50_5m", "SMA 50 (5m)", {"type": "sma", "params": {"length": 50}, "output": "sma", "tf": 5}),
    ("sma200_5m", "SMA 200 (5m)", {"type": "sma", "params": {"length": 200}, "output": "sma", "tf": 5}),
    ("ema9_5m", "EMA 9 (5m)", {"type": "ema", "params": {"length": 9}, "output": "ema", "tf": 5}),
    ("ema21_5m", "EMA 21 (5m)", {"type": "ema", "params": {"length": 21}, "output": "ema", "tf": 5}),
]

COLUMNS = [
    col("symbol", "Symbol", "symbol", "quote"),
    col("last", "Last", "price", "quote", "The last price (up to the Replay cursor)"),
    col("change", "Chg", "signed", "quote", "Change from the prior day's close"),
    col("pct", "Chg %", "pct", "quote", "% change from the prior day's close", heat=True),
    col("volume", "Volume", "count", "quote", "Regular hours (premarket before 09:30)"),
    col("high", "High", "price", "quote", "Regular hours (premarket before 09:30)"),
    col("low", "Low", "price", "quote", "Regular hours (premarket before 09:30)"),
    col("prev_close", "Prev close", "price", "quote", "The prior session's close"),
    col("time", "Time", "time", "quote", "The time of the last bar"),
    # the day so far
    col("open", "Open", "price", "day", "The 09:30 open"),
    col("gap_pct", "Gap %", "pct", "day", "The open vs the prior close", heat=True),
    col("chg_open", "Chg open", "signed", "day", "Change from the open"),
    col("chg_open_pct", "Chg open %", "pct", "day", "% change from the open", heat=True),
    col("vwap", "VWAP", "price", "day", "Regular-hours VWAP"),
    col("vs_vwap_pct", "vs VWAP %", "pct", "day", "The last price's distance from VWAP", heat=True),
    col("day_range", "Day range", "range", "day",
        "Where the last price sits in the day's range, with ticks for the open, the prior close and VWAP"),
    col("spark", "Today", "spark", "spark", "The day's prices, the prior close dotted, extended hours dimmed"),
    col("rvol", "Rel vol", "ratio", "rvol",
        f"Volume so far vs the average by this time of day over the last {RVOL_SESSIONS} sessions", bar=3, heat=True),
    # daily history
    col("range_atr", "Range/ATR", "ratio", "daily", "The day's range so far as a share of the 14-day ATR", bar=1.5, heat=True),
    col("atr", "ATR", "price", "daily", "Average true range, 14 days"),
    col("hi52", "52w high", "price", "daily", "Highest high of the last 52 weeks (today included)"),
    col("lo52", "52w low", "price", "daily", "Lowest low of the last 52 weeks (today included)"),
    col("from_hi52_pct", "From 52w high %", "pct", "daily", "The last price's distance below the 52-week high"),
    col("range52", "52w range", "range52", "daily", "Where the last price sits in its 52-week range; the band is today's range"),
    col("avg_vol20", "Avg vol (20d)", "count", "daily", "Average daily volume, 20 sessions"),
    col("pdh", "Prior high", "price", "daily", "The prior session's high"),
    col("pdl", "Prior low", "price", "daily", "The prior session's low"),
    col("sma50_d", "SMA 50 (d)", "price", "daily", "50-day simple moving average, today's price included"),
    col("sma200_d", "SMA 200 (d)", "price", "daily", "200-day simple moving average, today's price included"),
    # states: descriptions of the day so far, never signals
    col("vwap_state", "vs VWAP", "state", "day", "Above, below or at VWAP (within 0.05%)"),
    col("ib_state", "Initial balance", "state", "day", "The first hour's range (09:30-10:30): building, inside, or extended"),
    col("atr_zone", "ATR zone", "state", "daily", "Between which ATR levels (Saty-style, from the prior close) the price is"),
    # events
    col("earnings", "Earnings", "date", "events",
        "The next report in the market calendar, or the last one found on SEC EDGAR (marked 'last')"),
    col("exp_move_pct", "Exp. move %", "pct", "events",
        "The front expiry's at-the-money straddle as a % of the price, when the options are cached"),
    # study values
    *[c for sid, label, _ in STUDIES for c in (
        col(f"st_{sid}", label, "price", f"study:{sid}", f"The {label} line at the cursor"),
        col(f"vs_st_{sid}", f"vs {label} %", "pct", f"study:{sid}", f"The last price's distance from the {label} line", heat=True))],
    # Holdings (app/positions.py)
    col("qty", "Qty", "qty", "holding", "Shares held, over all accounts (negative: short)", lists="holding"),
    col("avg_cost", "Avg cost", "price", "holding", "Average cost per share, as IBKR reports it", lists="holding"),
    col("cost", "Cost basis", "money", "holding", "Quantity × average cost", lists="holding"),
    col("market_value", "Mkt value", "money", "holding", "Quantity × the price on screen", lists="holding"),
    col("weight_pct", "Weight %", "pct", "holding", "The holding's share of the listed holdings' value", lists="holding", bar=100),
    col("unrealized", "Unrl P/L", "pnl", "holding", "Market value − cost basis", lists="holding"),
    col("unrealized_bar", "Unrl P/L bar", "pnlbar", "holding", "Unrealized P/L as a bar: gains right, losses left",
        lists="holding"),
    col("unrealized_pct", "Unrl P/L %", "pct", "holding", "Unrealized P/L as a % of the cost basis", lists="holding", heat=True),
    col("day_pnl", "Day P/L", "pnl", "holding", "Quantity × change from the prior close", lists="holding"),
    # FinViz lists: what FinViz's export sends, as it sends it
    col("company", "Company", "text", "finviz", "From FinViz", lists="finviz"),
    col("sector", "Sector", "text", "finviz", "From FinViz", lists="finviz"),
    col("industry", "Industry", "text", "finviz", "From FinViz", lists="finviz"),
    col("market_cap", "Mkt cap", "text", "finviz", "Market capitalization, as FinViz exports it", lists="finviz"),
    col("pe", "P/E", "text", "finviz", "From FinViz", lists="finviz"),
]
BY_ID = {c["id"]: c for c in COLUMNS}
DEFAULTS = {          # built in; the Config page can choose others (application config, "watch_columns")
    "quote": ["symbol", "last", "change", "pct", "volume", "high", "low"],
    "finviz": ["symbol", "last", "change", "pct", "volume", "sector", "market_cap"],
    "holding": ["symbol", "qty", "avg_cost", "last", "market_value", "unrealized", "unrealized_pct", "day_pnl", "pct"],
}
STUDY_SPECS = {sid: spec for sid, _, spec in STUDIES}


def lists_for(kind: str) -> tuple:
    return ("all", kind) if kind != "quote" else ("all",)


def check_columns(kind: str, ids) -> list[str]:
    """A list kind's columns as chosen on the Config page: known ones it can show, Symbol first, no repeats."""
    if kind not in DEFAULTS:
        raise ValueError(f"Unknown list kind: {kind}")
    ok = [c for c in dict.fromkeys(ids or []) if c in BY_ID and BY_ID[c]["lists"] in lists_for(kind) and c != "symbol"]
    if not ok:
        raise ValueError("Choose at least one column besides Symbol")
    return ["symbol", *ok]


def defaults() -> dict:
    """Each list kind's default columns: the Config page's choice, else the built-in set."""
    from . import app_config
    mine = app_config.section("watch_columns")
    out = {}
    for kind, factory in DEFAULTS.items():
        try:
            out[kind] = check_columns(kind, mine[kind]) if kind in mine else factory
        except ValueError:
            out[kind] = factory
    return out


def catalog() -> dict:
    """The registry, for the page: the columns, each list kind's defaults, and the built-in ones."""
    return {"columns": COLUMNS, "defaults": defaults(), "factory": DEFAULTS}


def groups_for(cols) -> set:
    return {BY_ID[c]["group"] for c in cols if c in BY_ID} - {"quote", "holding", "finviz"}


def _f(x, digits=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, digits) if math.isfinite(x) else None


def _pct(a, b):
    return _f((a - b) / b * 100, 3) if a is not None and b else None


# ---------------------------------------------------------------- groups
def _bars(symbol, day, cursor):
    df = store.read_day(symbol, day)
    m = engine.minute_of_day(df["time"]) if not df.empty else pd.Series(dtype=int)
    if cursor is not None and not df.empty:
        df, m = df[m < cursor], m[m < cursor]
    return df, m


def _day(symbol, day, cursor, r, out):
    df, m = _bars(symbol, day, cursor)
    rth = df[(m >= RTH_START) & (m < RTH_END)]
    if rth.empty:
        out.update(vwap_state="before 09:30", ib_state="before 09:30")
        return
    op = float(rth["open"].iloc[0])
    traded = float(rth["volume"].sum()) > 0                  # indexes (VIX) trade no volume: no VWAP
    vw = engine.vwap_frame(rth) if traded else pd.DataFrame()
    v = float(vw["vwap"].iloc[-1]) if not vw.empty and math.isfinite(float(vw["vwap"].iloc[-1])) else None
    last, pc = r["last"], r.get("prev_close")
    out.update(open=_f(op), gap_pct=_pct(op, pc), chg_open=_f(last - op), chg_open_pct=_pct(last, op),
               vwap=_f(v), vs_vwap_pct=_pct(last, v))
    out["vwap_state"] = (None if v is None else "at VWAP" if abs(last - v) / v < 0.0005
                         else "above VWAP" if last > v else "below VWAP")
    rm = engine.minute_of_day(rth["time"])
    ib = rth[rm < RTH_START + 60]
    hi, lo = float(ib["high"].max()), float(ib["low"].min())
    out["ib_state"] = ("IB building" if (cursor if cursor is not None else int(rm.iloc[-1]) + 1) < RTH_START + 60
                       else ib_state(hi, lo, float(rth["high"].max()), float(rth["low"].min()))
                       .replace(" so far", "").replace(" the IB range", ""))


def _spark(symbol, day, cursor, r, out):
    df, m = _bars(symbol, day, cursor)
    if df.empty:
        return
    closes = df["close"].to_numpy(dtype=float)
    mins = m.to_numpy()
    idx = np.unique(np.linspace(0, len(closes) - 1, min(SPARK_POINTS, len(closes))).round().astype(int))
    out["spark"] = {"p": [round(float(closes[i]), 4) for i in idx],
                    "pre": int((mins[idx] < RTH_START).sum()), "post": int((mins[idx] >= RTH_END).sum()),
                    "base": r.get("prev_close")}


@lru_cache(maxsize=4096)
def _cum_volume(symbol, d, mtime, data_dir):
    """Cumulative regular-hours volume by minute of the session (index 0 = 09:30)."""
    df = store.read_day(symbol, d)
    out = np.zeros(RTH_END - RTH_START)
    if df.empty:
        return out
    m = engine.minute_of_day(df["time"]).to_numpy()
    keep = (m >= RTH_START) & (m < RTH_END)
    np.add.at(out, m[keep] - RTH_START, df["volume"].to_numpy(dtype=float)[keep])
    return np.cumsum(out)


def _mtime(symbol, d):
    try:
        return store.day_path(symbol, d).stat().st_mtime
    except OSError:
        return 0.0


def _rvol(symbol, day, cursor, r, out):
    if r.get("volume") is None:
        return
    df, m = _bars(symbol, day, cursor)
    mins = m[(m >= RTH_START) & (m < RTH_END)]
    if mins.empty:
        return
    at = int(mins.iloc[-1]) - RTH_START                      # the last minute with a bar
    prior = [d for d in store.list_days(symbol) if d < day][-RVOL_SESSIONS:]
    past = [_cum_volume(symbol, d, _mtime(symbol, d), str(store.DATA_DIR))[at] for d in prior]
    past = [x for x in past if x > 0]
    today = _cum_volume(symbol, day, _mtime(symbol, day), str(store.DATA_DIR))
    now = float(df.loc[(m >= RTH_START) & (m < RTH_END), "volume"].sum()) if cursor is not None else today[at]
    if past:
        out["rvol"] = _f(now / (sum(past) / len(past)), 3)


def _daily(symbol, day, cursor, r, out):
    d = engine.prior_context(symbol, day, lookback=260)
    if d.empty:
        return
    last, hi, lo = r["last"], r.get("high"), r.get("low")
    year = d.tail(251)
    hi52 = max(float(year["high"].max()), hi or -math.inf)
    lo52 = min(float(year["low"].min()), lo or math.inf)
    atr, _ = engine.atr_from_daily(d)
    closes = d["close"].astype(float)
    sma = lambda n: _f((closes.tail(n - 1).sum() + last) / n) if len(closes) >= n - 1 else None  # noqa: E731
    out.update(hi52=_f(hi52), lo52=_f(lo52), from_hi52_pct=_pct(last, hi52), avg_vol20=_f(d["volume"].tail(20).mean(), 0),
               pdh=_f(d["high"].iloc[-1]), pdl=_f(d["low"].iloc[-1]), atr=_f(atr), sma50_d=sma(50), sma200_d=sma(200),
               range_atr=_f((hi - lo) / atr, 3) if atr and hi is not None else None)
    if atr:
        lad = atr_ladder(float(closes.iloc[-1]), float(atr))
        out["atr_zone"] = _atr_zone(lad, last)


def _name(k):
    if k == 0:
        return "PC"
    a = abs(k)
    tag = "1 ATR" if a == 1 else f"{a * 100:g}%" if a < 1 else f"{a:g} ATR"
    return ("+" if k > 0 else "−") + tag


def _atr_zone(lad: dict, price: float) -> str:
    keys = sorted(k for k in lad if abs(k) in (*ATR_FIBS, 1.0, *ATR_EXTS) or k == 0 or abs(k) < 0.3)
    below = [k for k in keys if lad[k] <= price]
    above = [k for k in keys if lad[k] > price]
    if not below:
        return f"below {_name(keys[0])}"
    if not above:
        return f"above {_name(keys[-1])}"
    return f"{_name(below[-1])} to {_name(above[0])}"


@lru_cache(maxsize=1)
def _calendar(mtime):
    try:
        return json.loads(CALENDAR.read_text()).get("events", [])
    except (OSError, ValueError):
        return []


def _events(symbol, day, cursor, r, out):
    cal = _calendar(CALENDAR.stat().st_mtime if CALENDAR.exists() else 0)
    nxt = sorted(e for e in ((e["date"], e.get("time", "")) for e in cal
                             if e.get("category") == "earnings" and e.get("label", "").split(" ")[0] == symbol)
                 if e[0] >= day)
    if nxt:
        out["earnings"] = {"date": nxt[0][0], "time": nxt[0][1], "days": (pd.Timestamp(nxt[0][0]) - pd.Timestamp(day)).days}
    else:
        rep = sorted(e["date"] for e in ((earnings.read(symbol) or {}).get("earnings") or []) if e.get("date", "") <= day)
        if rep:
            out["earnings"] = {"date": rep[-1], "last": True, "days": (pd.Timestamp(rep[-1]) - pd.Timestamp(day)).days}
    for read in (option_chain.read, expected_move.read):
        try:
            cache = read(symbol)
            if not cache or cache.get("error"):
                continue
            exps = cache.get("wanted") or cache.get("expirations") or list((cache.get("expiries") or {}).keys())
            exps = [e for e in exps if e >= day.replace("-", "")]
            s = expected_move.straddle_at(cache, exps[0], r["last"]) if exps else None
            if s:
                out["exp_move_pct"] = _f(s["value"] / r["last"] * 100, 3)
                return
        except (KeyError, TypeError, ValueError, IndexError):
            continue


def _study(sid):
    def run(symbol, day, cursor, r, out):
        v = study_values.value(symbol, day, STUDY_SPECS[sid], cursor)["value"]
        out[f"st_{sid}"] = v
        out[f"vs_st_{sid}"] = _pct(r["last"], v)
    return run


GROUPS = {"day": _day, "spark": _spark, "rvol": _rvol, "daily": _daily, "events": _events,
          **{f"study:{sid}": _study(sid) for sid in STUDY_SPECS}}


# market internals (breadth counts and volumes): only their own prices and shape mean something
INTERNAL_GROUPS = {"spark"}


def row(symbol: str, day: str, cursor: int | None, groups: set) -> dict:
    r = quotes.row(symbol, day, cursor)
    if r.get("status") != "ok" or not groups:
        return r
    if quotes.INTERNAL.match(symbol):
        groups = groups & INTERNAL_GROUPS
    out = dict(r)
    for g in sorted(groups):
        fn = GROUPS.get(g)
        if fn:
            try:
                fn(symbol, day, cursor, r, out)
            except (ValueError, KeyError, IndexError, ZeroDivisionError) as e:      # one bad group: the rest stay
                out.setdefault("notes", []).append(f"{g}: {e}")
    return out


def rows(symbols: list[str], day: str, cursor: int | None, cols) -> list[dict]:
    g = groups_for(cols or [])
    return [row(s, day, cursor, g) for s in symbols]
