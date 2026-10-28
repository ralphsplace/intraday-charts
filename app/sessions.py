"""US equity trading days (NYSE full-day closures), in US/Eastern.

Holidays are listed through 2027; later years fall back to weekdays only, so a holiday then is simply
fetched and comes back empty. Add new years to HOLIDAYS as the exchange publishes them.
"""
from __future__ import annotations

import pandas as pd

ET = "America/New_York"

HOLIDAYS = frozenset("""
2024-01-01 2024-01-15 2024-02-19 2024-03-29 2024-05-27 2024-06-19 2024-07-04 2024-09-02 2024-11-28 2024-12-25
2025-01-01 2025-01-09 2025-01-20 2025-02-17 2025-04-18 2025-05-26 2025-06-19 2025-07-04 2025-09-01 2025-11-27
2025-12-25
2026-01-01 2026-01-19 2026-02-16 2026-04-03 2026-05-25 2026-06-19 2026-07-03 2026-09-07 2026-11-26 2026-12-25
2027-01-01 2027-01-18 2027-02-15 2027-03-26 2027-05-31 2027-06-18 2027-07-05 2027-09-06 2027-11-25 2027-12-24
""".split())

CLOSE_MINUTE = 16 * 60


def now_et() -> pd.Timestamp:
    return pd.Timestamp.now(tz=ET)


def is_trading_day(day: str) -> bool:
    return pd.Timestamp(day).weekday() < 5 and day not in HOLIDAYS


def session_on_or_before(day: str) -> str:
    d = pd.Timestamp(day)
    while not is_trading_day(d.strftime("%Y-%m-%d")):
        d -= pd.Timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def previous_session(day: str) -> str:
    return session_on_or_before((pd.Timestamp(day) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))


def sessions_ending(day: str, n: int) -> list[str]:
    """The n trading days ending with day (day itself first snapped back to a trading day), oldest first."""
    out = [session_on_or_before(day)]
    while len(out) < n:
        out.append(previous_session(out[-1]))
    return out[::-1]


def today(now: pd.Timestamp | None = None) -> str:
    return (now or now_et()).strftime("%Y-%m-%d")


def live_day(now: pd.Timestamp | None = None) -> str:
    """The day Live mode shows: today if it is a trading day, else the last one."""
    return session_on_or_before(today(now))


def last_complete_session(now: pd.Timestamp | None = None) -> str:
    """The most recent trading day whose regular session has closed (the default replay date)."""
    now = now or now_et()
    t = today(now)
    if is_trading_day(t) and now.hour * 60 + now.minute >= CLOSE_MINUTE:
        return t
    return previous_session(t)


def info(now: pd.Timestamp | None = None) -> dict:
    now = now or now_et()
    return {"today": today(now), "live_day": live_day(now), "last_session": last_complete_session(now),
            "trading_today": is_trading_day(today(now))}
