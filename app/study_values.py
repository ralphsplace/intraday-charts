"""A ticker's study values: the value of one of a study's lines or levels at the cursor, by name.

The one place that answers "where is QQQ's VWAP / 50-period SMA / +1 ATR level now?" for code outside the
charts: the watch list's study columns today, and anything that later needs a study's price (for example a
price taken from VWAP or an SMA). It runs the same study code as the charts, on the same cached bars, up to
the same cursor, so a value here always matches the line on a chart with the same settings.

A spec: {"type": a study in the catalog, "params": its settings (defaults fill the rest), "output": a line id
or a level's plot id or label, "tf": chart timeframe in minutes (1, 2, 3, 5 or 15)}.
"""
from __future__ import annotations

import math
from functools import lru_cache

from . import engine, store
from .studies import base as studies_base

TIMEFRAMES = (1, 2, 3, 5, 15)


def check(spec: dict) -> dict:
    """A spec with its study known and its settings coerced; ValueError otherwise."""
    t = spec.get("type")
    if t not in studies_base.REGISTRY:
        raise ValueError(f"Unknown study '{t}'")
    tf = int(spec.get("tf") or 1)
    if tf not in TIMEFRAMES:
        raise ValueError(f"Timeframe {tf} isn't one of {TIMEFRAMES}")
    params = studies_base.coerce(studies_base.REGISTRY[t], spec.get("params") or {})
    return {"type": t, "params": params, "output": str(spec.get("output") or t), "tf": tf}


def _pick(result: dict, output: str) -> float | None:
    for line in result.get("lines") or []:
        if line.get("id") == output:
            pts = [p["value"] for p in line.get("data") or [] if p.get("value") is not None]
            return float(pts[-1]) if pts else None
    for lv in result.get("levels") or []:
        if lv.get("plot") == output or lv.get("label") == output:
            return float(lv["price"])
    return None


def _mtime(symbol: str, day: str) -> float:
    try:
        return store.day_path(symbol, day).stat().st_mtime
    except OSError:
        return 0.0


@lru_cache(maxsize=2048)
def _value(symbol: str, day: str, cursor: int | None, key: tuple, mtime: float, data_dir: str) -> tuple[float | None, str]:
    spec = dict(key)
    ctx = engine.DayContext(symbol, day, spec["tf"], cursor)
    res = studies_base.run_study(ctx, spec["type"], dict(spec["params"]))
    if not res.get("ok"):
        return None, res.get("error") or "study failed"
    v = _pick(res, spec["output"])
    return (None, res.get("note") or "no value yet") if v is None or math.isnan(v) else (round(v, 4), "")


def value(symbol: str, day: str, spec: dict, cursor: int | None = None) -> dict:
    """{"value": price or None, "note": why there is none}. Cached until the day's bars change."""
    s = check(spec)
    key = tuple(sorted({**s, "params": tuple(sorted(s["params"].items()))}.items()))
    try:
        v, note = _value(symbol.upper(), day, cursor, key, _mtime(symbol.upper(), day), str(store.DATA_DIR))
    except ValueError as e:                      # no bars cached for the day
        return {"value": None, "note": str(e)}
    return {"value": v, "note": note}
