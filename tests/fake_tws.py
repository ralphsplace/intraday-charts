"""A stand-in for TWS that invents bars, for the automated tests and UI checks. NOT market data.

Runs the real collector (tools/fetch_ibkr.py) against invented prices, so the chart page's
"type a symbol / Load data / Live" flow can be tried without IBKR. Point it at a test data folder only:
    python tests/fake_tws.py --data-dir /tmp/test-data --live
Symbols starting with ZZ are treated as unknown to IBKR.
"""
from __future__ import annotations

import contextlib
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import fetch_ibkr  # noqa: E402

ET = "America/New_York"


class Bar:
    def __init__(self, date, o, h, l, c, v):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, o, h, l, c, v


class Contract:
    def __init__(self, symbol, conId=0):
        self.symbol, self.conId = symbol, conId


def invented_index_day(symbol: str, day: str, until: pd.Timestamp | None = None) -> list[Bar]:
    """TICK-like (around 0, swings to +/-1000) or TRIN-like (around 1) bars, regular hours only."""
    rng = np.random.default_rng(zlib.crc32(f"{symbol}{day}".encode()))
    d0 = pd.Timestamp(day, tz=ET)
    out, x = [], 0.0
    for m in range(570, 960):
        t = d0 + pd.Timedelta(minutes=m)
        if until is not None and t > until:
            break
        if symbol.startswith("TRIN"):
            c = round(float(np.clip(1 + rng.normal(0, 0.25), 0.2, 4)), 3)
            out.append(Bar(t.tz_convert("UTC").to_pydatetime(), c, c * 1.05, c * 0.95, c, 0.0))
            continue
        x = 0.6 * x + rng.normal(0, 260)
        o, c = round(x + rng.normal(0, 120)), round(x)
        out.append(Bar(t.tz_convert("UTC").to_pydatetime(), o, max(o, c) + abs(round(rng.normal(0, 250))),
                       min(o, c) - abs(round(rng.normal(0, 250))), c, 0.0))
    return out


def invented_day(symbol: str, day: str, until: pd.Timestamp | None = None) -> list[Bar]:
    if "-" in symbol:
        return invented_index_day(symbol, day, until)
    seed = zlib.crc32(f"{symbol}{day}".encode())
    rng = np.random.default_rng(seed)
    base = 50 + zlib.crc32(symbol.encode()) % 650
    base *= 1 + (pd.Timestamp(day).dayofyear % 20 - 10) / 400
    mins = np.arange(4 * 60, 20 * 60)
    closes = base * np.exp(np.cumsum(rng.normal(0, 0.0006, len(mins))))
    vol = np.where((mins >= 570) & (mins < 960), 8000, 600) * rng.lognormal(0, 0.3, len(mins))
    d0 = pd.Timestamp(day, tz=ET)
    out, prev = [], closes[0]
    for m, c, v in zip(mins, closes, vol, strict=True):
        t = d0 + pd.Timedelta(minutes=int(m))
        if until is not None and t > until:
            break
        o = prev
        out.append(Bar(t.tz_convert("UTC").to_pydatetime(), round(o, 2), round(max(o, c) * 1.0004, 2),
                       round(min(o, c) * 0.9996, 2), round(c, 2), float(round(v))))
        prev = c
    return out


class FakeTicker:
    """An invented live quote whose bid/ask drift with the clock."""

    def __init__(self, contract, now):
        self.contract, self.now = contract, now
        self.scale = 1e6 if contract.symbol.startswith("VOL") else 1.0

    def _m(self):
        t = self.now()
        return t.hour * 60 + t.minute + t.second / 60

    @property
    def bid(self):
        return round((1500 + 300 * np.sin(self._m() / 37)) * self.scale)

    @property
    def ask(self):
        return round((1400 + 250 * np.cos(self._m() / 23)) * self.scale)


class FakeIB:
    def __init__(self, now=None, delay=0.0):
        self.now = now or (lambda: pd.Timestamp.now(tz=ET))
        self.delay = delay
        self.connected = True
        self.live: list = []          # (symbol, list) kept up to date
        self.tickers: list = []       # live quote subscriptions (reqMktData)
        self.requests: list = []
        self.durations: list = []    # (symbol, durationStr) of daily requests

    def isConnected(self):
        return self.connected

    def reqHistoricalData(self, contract, endDateTime, durationStr, barSizeSetting, keepUpToDate=False, **kw):
        sym = contract.symbol
        self.requests.append((sym, endDateTime, barSizeSetting, keepUpToDate))
        if self.delay:
            time.sleep(self.delay)
        if barSizeSetting == "1 day":
            self.durations.append((sym, durationStr))
            n, unit = durationStr.split()
            days = pd.bdate_range(end=self.now().tz_localize(None).normalize(),
                                  periods=int(n) * (252 if unit == "Y" else 21))
            rng = np.random.default_rng(zlib.crc32(sym.encode()))
            px = (50 + zlib.crc32(sym.encode()) % 650) * np.exp(np.cumsum(rng.normal(0, 0.01, len(days))))
            return [Bar(d.date(), p, p * 1.01, p * 0.99, p, 1e6) for d, p in zip(days, px, strict=True)]
        if keepUpToDate:
            now = self.now()
            bars = invented_day(sym, now.strftime("%Y-%m-%d"), until=now)
            self.live.append((sym, bars))
            return bars
        day = datetime.strptime(endDateTime[:8], "%Y%m%d").strftime("%Y-%m-%d")
        return invented_day(sym, day, until=self.now())

    def reqMktData(self, contract, genericTickList="", snapshot=False, regulatorySnapshot=False):
        """Live quotes for the NYSE indicators: invented advancing/declining counts (AD-NYSE) or up/down volume
        (VOL-NYSE) in bid/ask, like TWS sends them."""
        if not getattr(contract, "conId", 0):     # like ib_async: only a qualified contract can be subscribed
            raise ValueError(f"Contract {contract.symbol} can't be hashed because no 'conId' value exists")
        self.requests.append((contract.symbol, "mktdata", None, True))
        t = FakeTicker(contract, self.now)
        self.tickers.append(t)
        return t

    def cancelMktData(self, contract):
        self.tickers = [t for t in self.tickers if t.contract is not contract]

    def cancelHistoricalData(self, bars):
        self.live = [(s, b) for s, b in self.live if b is not bars]

    def tick(self):
        """Bring the streamed lists up to now, like TWS does."""
        now = self.now()
        for sym, bars in self.live:
            fresh = invented_day(sym, now.strftime("%Y-%m-%d"), until=now)
            if len(fresh) > len(bars):
                bars.extend(fresh[len(bars):])

    def sleep(self, secs):
        if self.delay:
            time.sleep(min(secs, 1.0))
        self.tick()


def qualify(sym):
    return None if sym.startswith("ZZ") else Contract(sym, conId=abs(hash(sym)) % 10**8 + 1)


def main(argv=None):
    from app import store
    args = fetch_ibkr.parse_args(argv)
    if not args.data_dir:
        sys.exit("--data-dir is required: point it at a test folder, never your real data")
    store.DATA_DIR = Path(args.data_dir)
    ib = FakeIB(delay=0.3)
    col = fetch_ibkr.Collector(ib, args, qualify=qualify)
    with contextlib.suppress(KeyboardInterrupt):
        col.run()


if __name__ == "__main__":
    main()
