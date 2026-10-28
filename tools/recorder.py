"""Records series IBKR sends only as live quotes into 1-minute bars, since there's no history to download.

IBKR's NYSE market indicators arrive as quote fields rather than prices (TWS API docs, "market indicators"):
    AD-NYSE   bid = advancing issues, ask = declining issues   -> ADD-NYSE  = bid - ask
    VOL-NYSE  bid = up volume,        ask = down volume        -> VOLD-NYSE = bid - ask
While the collector runs in live mode, each pass of its loop samples the quotes during regular hours and keeps
the current minute's open/high/low/close; changed minutes are written to the cache every few seconds, merged with
what's already there for the day (so a restart doesn't lose the morning). History starts when recording starts.
"""
from __future__ import annotations

import contextlib
import logging
import math
import time

import pandas as pd

from app import control, sessions, store

log = logging.getLogger("fetch_ibkr")
RTH_START, RTH_END = 9 * 60 + 30, 16 * 60


def value(ticker) -> float | None:
    """bid - ask of an indicator ticker, or None while either is missing (IBKR sends -1 or NaN for 'none')."""
    bid, ask = getattr(ticker, "bid", None), getattr(ticker, "ask", None)
    if bid is None or ask is None or any(math.isnan(x) for x in (bid, ask)) or bid < 0 or ask < 0:
        return None
    return float(bid) - float(ask)


class Recorder:
    """contract(name) returns the qualified IBKR contract for an indicator (e.g. AD-NYSE), or None when IBKR
    doesn't have it; the collector passes its own, which looks the contract up once and remembers it."""

    def __init__(self, ib, symbols, contract, write_every: float = 5.0, clock=time.monotonic):
        self.ib, self.contract, self.write_every, self.clock = ib, contract, write_every, clock
        self.symbols = [s for s in symbols if s in control.RECORDED]
        self.failed: dict = {}             # recorded symbol -> why it isn't recorded
        self.tickers: dict = {}            # recorded symbol -> live ticker
        self.bars: dict = {}               # recorded symbol -> {minute timestamp: [o, h, l, c]}
        self.dirty: set = set()
        self.day = None
        self.last_write = None

    def _subscribe(self):
        """Ask for each indicator's live quotes once. One that can't be had is noted (status, log) and skipped,
        so it never stops the collector."""
        for sym in self.symbols:
            if sym in self.tickers or sym in self.failed:
                continue
            source = control.RECORDED[sym]
            try:
                c = self.contract(source)
                if c is None:
                    raise LookupError(f"IBKR has no {source} contract")
                self.tickers[sym] = self.ib.reqMktData(c, "", False, False)
            except Exception as e:              # noqa: BLE001  (anything from TWS or ib_async: skip this one)
                self.failed[sym] = f"{source}: {e}"
                log.warning("Not recording %s: %s", sym, self.failed[sym])
                continue
            log.info("Recording %s from %s (live quotes)", sym, source)

    def cancel(self):
        for t in self.tickers.values():
            with contextlib.suppress(Exception):          # the connection may already be gone
                self.ib.cancelMktData(t.contract)
        self.tickers.clear()

    def sync(self, now: pd.Timestamp) -> int:
        """One pass: subscribe in regular hours, sample, and write what changed. Returns files written."""
        day, minute = now.strftime("%Y-%m-%d"), now.hour * 60 + now.minute
        if not self.symbols or not sessions.is_trading_day(day) or not RTH_START <= minute < RTH_END:
            if self.tickers:
                self.flush()
                self.cancel()
            return 0
        if day != self.day:
            self.flush()
            self.day, self.bars = day, {}
        self._subscribe()
        stamp = now.floor("min")
        for sym, t in self.tickers.items():
            v = value(t)
            if v is None:
                continue
            bar = self.bars.setdefault(sym, {}).get(stamp)
            if bar is None:
                self.bars[sym][stamp] = [v, v, v, v]
            else:
                bar[1], bar[2], bar[3] = max(bar[1], v), min(bar[2], v), v
            self.dirty.add(sym)
        t = self.clock()
        if self.last_write is not None and t - self.last_write < self.write_every:
            return 0
        self.last_write = t
        return self.flush()

    def flush(self) -> int:
        n = 0
        for sym in sorted(self.dirty):
            rows = [{"time": ts, "open": o, "high": h, "low": lo, "close": c, "volume": 0.0}
                    for ts, (o, h, lo, c) in sorted(self.bars.get(sym, {}).items())]
            if not rows or not self.day:
                continue
            new = pd.DataFrame(rows, columns=store.COLUMNS)
            old = store.read_day(sym, self.day)
            merged = pd.concat([old, new], ignore_index=True) if not old.empty else new
            store.write_day(sym, self.day, merged)          # same minutes: the newer bar wins
            n += 1
        self.dirty.clear()
        return n
