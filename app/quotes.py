"""Watch list rows: each symbol's last price, change from the prior close, volume, and the day's high and low, from
the cached 1-minute bars of one day. In Replay only bars that started before the cursor count, like the charts.

One job: cached bars in, one row per symbol out. No network: symbols not cached for the day say so, and the page
can ask the collector for them.
"""
from __future__ import annotations

import math
import re

from . import engine, store

RTH_START, RTH_END = 9 * 60 + 30, 16 * 60
# market internals (breadth counts and volumes): a % change from their prior close means nothing, and they trade no volume
INTERNAL = re.compile(r"^(TICK|TRIN|AD|VOL|ADD|VOLD)-(NYSE|NASD|NDX)$")


def _f(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, 4) if math.isfinite(x) else None


def row(symbol: str, day: str, cursor: int | None = None) -> dict:
    df = store.read_day(symbol, day)
    if df.empty:
        return {"symbol": symbol, "status": "missing"}
    m = engine.minute_of_day(df["time"])
    if cursor is not None:
        df, m = df[m < cursor], m[m < cursor]
    if df.empty:
        return {"symbol": symbol, "status": "none yet"}            # replaying before its first bar
    rth = df[(m >= RTH_START) & (m < RTH_END)]
    session = rth if not rth.empty else df                        # premarket only so far: those bars
    last = float(df["close"].iloc[-1])
    prior = engine.prior_context(symbol, day, lookback=1)
    prev = float(prior["close"].iloc[-1]) if not prior.empty else None
    change = last - prev if prev else None
    internal = bool(INTERNAL.match(symbol))
    volume = float(session["volume"].sum())
    return {"symbol": symbol, "status": "ok", "last": _f(last), "prev_close": _f(prev), "change": _f(change),
            "pct": _f(change / prev * 100) if prev and not internal else None, "volume": _f(volume) if volume > 0 else None,
            "high": _f(session["high"].max()), "low": _f(session["low"].min()),
            "time": df["time"].iloc[-1].strftime("%H:%M")}


def rows(symbols: list[str], day: str, cursor: int | None = None) -> list[dict]:
    return [row(s, day, cursor) for s in symbols]
