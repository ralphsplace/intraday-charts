"""Days a backtest needs that aren't cached yet, fetched from TWS (#78): the same requests the chart page sends the
collector (app/control.py), then a wait until the days are in the cache. The app stays read-only toward the
broker: this only asks the collector for price history, as "Load data…" does.

The collector fetches a requested day and the 5 trading days before it, skipping days it already has, so one
request covers up to 6 missing days. A day IBKR has nothing for (a market closure the calendar doesn't know,
a symbol that didn't trade yet) stays missing: once the collector has worked through every request, it's
reported and skipped.
"""
from __future__ import annotations

import time

from .. import control, sessions, store

ALIVE_SECONDS = 60          # the collector writes its status every few seconds
QUIET_SECONDS = 20          # the collector done with our requests this long, and days still missing: give up on them
POLL_SECONDS = 2            # how often the cache is looked at
STALL_SECONDS = 600         # nothing arrived for this long while the collector still had work: stop waiting


def collector_ready() -> str | None:
    """Why missing days can't be fetched now (in words), or None when the collector is connected to TWS."""
    s = control.read_status()
    if s.get("age") is None or s["age"] > ALIVE_SECONDS:
        return "the TWS collector isn't running (start it, or skip the days without cached bars)"
    if not s.get("connected"):
        return "the TWS collector isn't connected to TWS (start TWS, or skip the days without cached bars)"
    return None


def requests_for(days: list[str]) -> list[str]:
    """The days to ask for, latest first: each request brings that day and the 5 trading days before it."""
    out, covered = [], set()
    for d in sorted(days, reverse=True):
        if d in covered:
            continue
        out.append(d)
        covered.update(sessions.sessions_ending(d, 6))
    return out


def missing(symbol: str, days: list[str]) -> list[str]:
    return [d for d in days if not store.day_path(symbol, d).exists()]


def _ours_waiting(symbol: str, days: set, ids: set) -> bool:
    """Whether the collector still has work for these days: a request not taken yet, or a task queued or running."""
    if any(r.get("id") in ids for r in control.pending_requests()):
        return True
    s = control.read_status()
    queue = s.get("queue") or []
    if (s.get("queue_len") or 0) > len(queue):          # the status lists only the head of a long queue
        return True
    tasks = [*queue, s.get("current") or {}]
    src = control.fetchable(symbol)
    return any(isinstance(t, dict) and t.get("symbol") == src and t.get("day") in days for t in tasks)


def fetch(symbol: str, days: list[str], progress=None, sleep=time.sleep, clock=time.time) -> list[str]:
    """Ask the collector for `days` of `symbol` and wait for them. progress(got, wanted) after each check.
    Returns the days still missing (IBKR had nothing for them). ValueError when the collector isn't there, or
    stops answering."""
    why = collector_ready()
    if why:
        raise ValueError(f"Can't fetch {len(days)} missing day(s): {why}")
    today = sessions.today()
    later = sorted(d for d in days if d > today)           # not traded yet: nothing to fetch
    wanted = {d for d in days if d <= today}
    if not wanted:
        return later
    ids = {control.submit([symbol], day=d)["id"] for d in requests_for(sorted(wanted))}
    last_change, quiet_since, left = clock(), None, len(wanted)
    while True:
        now_missing = missing(symbol, sorted(wanted))
        if progress:
            progress(len(wanted) - len(now_missing), len(wanted))
        if not now_missing:
            return later
        if len(now_missing) < left:
            left, last_change = len(now_missing), clock()
        if _ours_waiting(symbol, set(now_missing), ids):
            quiet_since = None
            if clock() - last_change > STALL_SECONDS or collector_ready():
                raise ValueError(f"Fetching stopped with {len(now_missing)} day(s) still missing: "
                                 + (collector_ready() or "TWS hasn't sent anything for 10 minutes"))
        else:
            quiet_since = quiet_since or clock()
            if clock() - quiet_since > QUIET_SECONDS:      # done with our requests: what's left, IBKR doesn't have
                return sorted(now_missing + later)
        sleep(POLL_SECONDS)
