"""The candle durations a chart can show: one list for the server and the page (sent in /api/meta).

Intraday durations (minutes) are built from 1-minute bars (engine.py) and show a number of days. Daily, weekly
and monthly ones are periods, built from daily prices (periods.py), and show a number of months.
"""
from __future__ import annotations

INTRADAY = {1: "1m", 3: "3m", 5: "5m", 15: "15m"}
DAY_RANGES = [(1, "Today"), (2, "2 days"), (3, "3 days"), (5, "5 days")]

# id -> label, seconds per candle (roughly, for monthly), months shown by default
PERIODS = {"1d": {"label": "1d", "seconds": 86400, "span": 6},
           "1w": {"label": "1w", "seconds": 7 * 86400, "span": 24},
           "1M": {"label": "1M", "seconds": 30 * 86400, "span": 120}}
SPANS = [(3, "3 months"), (6, "6 months"), (12, "1 year"), (24, "2 years"), (60, "5 years"), (120, "10 years")]


def parse(tf) -> int | str | None:
    """A timeframe id from a request (3, "3", "1d"), or None when it isn't one."""
    if isinstance(tf, str) and tf in PERIODS:
        return tf
    try:
        n = int(tf)
    except (TypeError, ValueError):
        return None
    return n if n in INTRADAY and str(n) == str(tf).strip() else None


def is_period(tf) -> bool:
    return tf in PERIODS


def label(tf) -> str:
    return PERIODS[tf]["label"] if is_period(tf) else INTRADAY[tf]


def span_label(months: int) -> str:
    return dict(SPANS).get(months, f"{months} months")


def listing() -> dict:
    """What the page needs to build a chart's duration and range menus."""
    items = [{"id": k, "label": v, "period": False} for k, v in INTRADAY.items()]
    items += [{"id": k, "label": p["label"], "period": True, "span": p["span"]} for k, p in PERIODS.items()]
    return {"list": items, "days": DAY_RANGES, "spans": SPANS}
