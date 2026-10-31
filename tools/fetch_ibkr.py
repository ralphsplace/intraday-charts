"""TWS collector: fetches bars from Trader Workstation into the local cache, and keeps today's bars live.

TWS must be running and logged in, with the API enabled (Configure > API > Settings). The connection is
opened read-only, so this script cannot place orders.

It works through a queue of fetches. The queue is filled from six places:
  - the symbols on the command line (or the SYMBOLS environment variable)
  - the chart page: typing a symbol into a chart, or "Load data" in Replay mode
  - the earnings page: a symbol's daily history and, when SEC_CONTACT is set, its earnings dates from SEC
    EDGAR (tools/earnings_sources.py; an internet request)
  - the expected-move page: option quotes (snapshots) for a symbol's expiry (tools/option_quotes.py)
  - the option-chain page: a symbol's option chain (snapshots) for a few expiries (tools/option_quotes.py)
  - each morning in live mode: the daily history of the streamed symbols
Watch lists from FinViz (when FINVIZ_TOKEN is set) are fetched straight away, outside the queue
(tools/list_sources.py; the other internet request, to finviz.com only).
With HOLDINGS=on it also reads the account's positions once a minute in live mode, for the watch list's Holdings
list (tools/positions.py): positions only, never orders or executions.
In live mode it also records the NYSE advance-decline and up/down volume (ADD-NYSE, VOLD-NYSE) from live quotes,
since IBKR has no history for them (tools/recorder.py; RECORD in .env).

Fetch 30 trading days of 1-minute bars (plus 10 years of daily bars), then stop:
    python tools/fetch_ibkr.py --symbols QQQ SPY --days 30

Fetch one day (and the 5 trading days before it), then stop:
    python tools/fetch_ibkr.py --symbols QQQ SPY --date 2026-10-16

Keep running: stream today's bars every few seconds and take requests from the chart page (live mode).
If TWS is closed, restarts or the PC sleeps, live mode waits and reconnects by itself:
    python tools/fetch_ibkr.py --symbols QQQ SPY --live

Connection settings come from flags or the IB_HOST / IB_PORT / IB_CLIENT_ID environment variables.
TWS ports: 7496 live, 7497 paper. IB_HOST is the address of the PC running TWS. The default,
host.docker.internal, is the machine running Docker; use 127.0.0.1 when running on the TWS PC without Docker,
or the PC's LAN address when Docker runs on another machine (e.g. the NAS).
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import (control, earnings, envcheck, expected_move, list_sources, option_chain, positions,  # noqa: E402
                 sessions, store)
from option_quotes import OptionQuotes  # noqa: E402
from earnings_sources import make_source  # noqa: E402
from list_sources import make_fetchers  # noqa: E402
from positions import PositionsReader  # noqa: E402
from recorder import Recorder  # noqa: E402

ET = "America/New_York"
RETRY_SECONDS = 30       # wait between reconnect attempts in live mode
HISTORY_DAYS = 5         # trading days fetched before a requested day (multi-day views, prior-day levels)
INFO_CODES = {2100, 2104, 2106, 2107, 2108, 2119, 2150, 2158, 2174}   # TWS "OK" notices, not errors
log = logging.getLogger("fetch_ibkr")


class TWSUnavailable(Exception):
    """TWS can't be reached or dropped the connection."""


# ---------------------------------------------------------------- bar conversion and single requests
def bars_to_frame(bars) -> pd.DataFrame:
    """Convert ib_async BarData objects to the cache schema (times in US/Eastern)."""
    rows = [{"time": b.date, "open": b.open, "high": b.high, "low": b.low,
             "close": b.close, "volume": max(float(b.volume), 0.0)} for b in bars]
    df = pd.DataFrame(rows, columns=store.COLUMNS)
    if df.empty:
        return df
    t = pd.to_datetime(df["time"], utc=True)  # formatDate=2 returns UTC datetimes
    df["time"] = t.dt.tz_convert(ET)
    return df


def only_day(df: pd.DataFrame, day: str) -> pd.DataFrame:
    return df[df["time"].dt.strftime("%Y-%m-%d") == day] if not df.empty else df


def trading_days_back(n: int, today: pd.Timestamp | None = None) -> list[str]:
    """Last n trading days up to and including today (weekends and exchange holidays skipped)."""
    today = today or pd.Timestamp.now(tz=ET)
    return sessions.sessions_ending(today.strftime("%Y-%m-%d"), n)


def fetch_day(ib, contract, day: str) -> pd.DataFrame:
    end = f"{day.replace('-', '')} 20:00:00 US/Eastern"
    bars = ib.reqHistoricalData(contract, endDateTime=end, durationStr="1 D", barSizeSetting="1 min",
                                whatToShow="TRADES", useRTH=False, formatDate=2, timeout=120)
    return only_day(bars_to_frame(bars or []), day)


def backfill(ib, contract, symbol: str, days: list[str], refresh: bool = False) -> int:
    """Fetch each day not cached yet (today is always re-fetched). Used by the tests and one-off scripts;
    the collector itself goes through its queue."""
    today = pd.Timestamp.now(tz=ET).strftime("%Y-%m-%d")
    written = 0
    for day in days:
        if store.day_path(symbol, day).exists() and day != today and not refresh:
            continue
        df = fetch_day(ib, contract, day)
        if not df.empty:
            store.write_day(symbol, day, df)
            written += 1
        ib.sleep(Pacer.MIN_GAP)
    return written


def fetch_daily(ib, contract, symbol: str, years: int) -> int:
    """Regular-hours daily bars (daily, weekly and monthly charts; daily moving averages, ATR, prior-week levels).
    The whole history the first time, or when `years` grew; afterwards only the last month, added to the file."""
    full = daily_need(symbol, None, years) == "full"
    bars = ib.reqHistoricalData(contract, endDateTime="", durationStr=f"{years} Y" if full else RECENT_DAILY,
                                barSizeSetting="1 day", whatToShow="TRADES", useRTH=True, formatDate=1, timeout=120)
    rows = [{"date": pd.Timestamp(b.date).strftime("%Y-%m-%d"), "open": b.open, "high": b.high, "low": b.low,
             "close": b.close, "volume": max(float(b.volume), 0.0)} for b in bars or []]
    if rows:
        new = pd.DataFrame(rows)
        old = store.read_daily(symbol) if not full else pd.DataFrame()
        store.write_daily(symbol, pd.concat([old, new], ignore_index=True) if not old.empty else new,
                          years=years if full else store.daily_years(symbol))
    log.info("%s: %d daily bars %s", symbol, len(rows), f"cached ({years} years asked for)" if full else "added")
    return len(rows)


def daily_need(symbol: str, day: str | None, years: int) -> str | None:
    """What a symbol's daily file needs: "full" (missing, or fetched for fewer years than asked), "recent" (it
    doesn't reach the session before `day`), or None. day=None skips the recency check."""
    d = store.read_daily(symbol)
    if d.empty or store.daily_years(symbol) < years:
        return "full"
    if day is not None and str(d["date"].iloc[-1]) < sessions.previous_session(day):
        return "recent"
    return None


RECENT_DAILY = "1 M"          # the daily bars fetched to bring a full file up to date


class Pacer:
    """Keeps historical requests under IBKR's limit (60 per 10 minutes) with a small gap between them."""
    LIMIT, WINDOW, MIN_GAP = 50, 600.0, 2.0

    def __init__(self, clock=time.monotonic):
        self.clock, self.times = clock, deque()

    def ready(self) -> bool:
        now = self.clock()
        while self.times and now - self.times[0] > self.WINDOW:
            self.times.popleft()
        if self.times and now - self.times[-1] < self.MIN_GAP:
            return False
        return len(self.times) < self.LIMIT

    def note(self) -> None:
        self.times.append(self.clock())


# ---------------------------------------------------------------- live streaming
def in_stream_hours(now: pd.Timestamp) -> bool:
    """Trading day, 04:00-20:00 ET (pre-market through after-hours)."""
    return sessions.is_trading_day(now.strftime("%Y-%m-%d")) and 4 * 60 <= now.hour * 60 + now.minute < 20 * 60


class LiveStream:
    """Today's 1-minute bars for each streamed symbol, kept up to date by TWS (keepUpToDate) and written to
    the cache when they change. Symbols can be added or removed at any time; everything is re-subscribed
    when the trading day rolls over, and paused outside 04:00-20:00 ET."""

    def __init__(self, ib, write_every: float = 5.0, clock=time.monotonic):
        self.ib, self.write_every, self.clock = ib, write_every, clock
        self.subs: dict = {}       # symbol -> BarDataList that TWS keeps updating
        self.written: dict = {}    # symbol -> signature of the last write
        self.day = None
        self.last_write = None
        self.open = False

    def subscribe(self, sym: str, contract) -> None:
        self.subs[sym] = self.ib.reqHistoricalData(contract, endDateTime="", durationStr="1 D", barSizeSetting="1 min",
                                                   whatToShow="TRADES", useRTH=False, formatDate=2,
                                                   keepUpToDate=True, timeout=60)
        log.info("Streaming %s", sym)

    def cancel(self, sym: str | None = None) -> None:
        for s in ([sym] if sym else list(self.subs)):
            bars = self.subs.pop(s, None)
            self.written.pop(s, None)
            try:
                if bars is not None:
                    self.ib.cancelHistoricalData(bars)
            except Exception:  # connection may already be gone
                pass

    @staticmethod
    def signature(bars):
        if not bars:
            return None
        b = bars[-1]
        return (len(bars), b.date, b.close, b.volume)

    def write_changed(self, day: str) -> int:
        """Write every symbol whose bars changed since the last write. Returns how many were written."""
        n = 0
        for sym, bars in self.subs.items():
            sig = self.signature(bars)
            if sig is None or sig == self.written.get(sym):
                continue
            df = only_day(bars_to_frame(list(bars)), day)
            if not df.empty:
                store.write_day(sym, day, df)
                n += 1
            self.written[sym] = sig
        return n

    def sync(self, now: pd.Timestamp, contracts: dict) -> int:
        """Match the subscriptions to `contracts` (symbol -> contract), then write what changed."""
        day = now.strftime("%Y-%m-%d")
        self.open = in_stream_hours(now)
        if not self.open or not contracts:
            if self.subs:
                log.info("Streaming paused (%s)", "market closed" if not self.open else "no live symbols")
                self.cancel()
            return 0
        if day != self.day:
            self.cancel()
            self.day = day
        for sym in [s for s in self.subs if s not in contracts]:
            self.cancel(sym)
        for sym, c in contracts.items():
            if sym not in self.subs:
                self.subscribe(sym, c)
                self.last_write = None
        t = self.clock()
        if self.last_write is not None and t - self.last_write < self.write_every:
            return 0
        self.last_write = t
        return self.write_changed(day)


# ---------------------------------------------------------------- the collector
def make_stock(sym: str):
    """IBKR contract for a stock / ETF, or for a market index such as TICK-NYSE."""
    if control.is_index(sym):
        from ib_async import Index
        return Index(sym, control.INDEXES[sym], "USD")
    from ib_async import Stock
    return Stock(sym.replace(".", " "), "SMART", "USD")      # IBKR writes BRK.B as "BRK B"


class Collector:
    """Works through the fetch queue, streams the live symbols, and reports progress in control/status.json."""

    def __init__(self, ib, args, qualify=None, now=sessions.now_et, clock=time.monotonic, option=None):
        self.ib, self.args, self.now, self.clock = ib, args, now, clock
        self.qualify_fn = qualify or self._qualify_ib
        self.contracts: dict = {}
        self.bad: dict = {}                 # symbol -> reason
        self.tasks: deque = deque()         # (kind, symbol, day)
        self.queued: set = set()
        self.results: deque = deque(maxlen=40)
        self.errors: deque = deque(maxlen=15)
        self.current = None
        self.pacer = Pacer(clock)
        self.stream = LiveStream(ib, args.write_every, clock)
        self.live: set = set(control.load_live_symbols()) if args.live else set()
        self.daily_done_for = None
        self.earnings_source = make_source(getattr(args, "sec_contact", None), store.DATA_DIR / "earnings")
        self.list_fetchers = make_fetchers(os.environ.get("FINVIZ_TOKEN"))   # watch lists from FinViz (.env)
        self.option_quotes = OptionQuotes(ib, **({"option": option} if option else {}))   # tests pass a fake option
        # the account's positions, for the watch list's Holdings list: only with HOLDINGS=on, only in live mode
        self.positions = PositionsReader(ib, clock) if args.live and positions.turned_on() else None
        self.recorder = Recorder(ib, getattr(args, "record", []), self.contract, args.write_every, clock) if args.live else None
        err = getattr(ib, "errorEvent", None)
        if err is not None:
            err += self._on_error

    # ---- TWS messages
    def _on_error(self, reqId, code, msg, contract=None, *rest):
        if code in INFO_CODES:
            return
        sym = getattr(contract, "symbol", None)
        self.errors.append({"code": code, "message": str(msg)[:300], "symbol": sym, "at": time.time()})
        log.warning("TWS message %s%s: %s", code, f" ({sym})" if sym else "", msg)

    def _qualify_ib(self, sym: str):
        c = make_stock(sym)
        return c if self.ib.qualifyContracts(c) else None

    def contract(self, sym: str):
        if sym in self.contracts:
            return self.contracts[sym]
        if sym in self.bad:
            return None
        c = self.qualify_fn(sym)
        if c is None:
            self.bad[sym] = ("IBKR has no index with this symbol" if control.is_index(sym)
                             else "IBKR has no US stock or ETF with this symbol")
            log.warning("%s: no such contract at IBKR, skipped", sym)
            return None
        self.contracts[sym] = c
        return c

    # ---- the queue
    def add_task(self, kind: str, sym: str, day: str | None = None, front: bool = False) -> None:
        key = (kind, sym, day)
        if key in self.queued:
            return
        self.queued.add(key)
        (self.tasks.appendleft if front else self.tasks.append)(key)

    def request(self, symbols, day: str | None = None, live: bool = False, history: int = HISTORY_DAYS,
                front: bool = False, daily_only: bool = False, earnings_dates: bool = False) -> None:
        """Queue everything needed to chart `symbols` on `day` (default: today's live day). daily_only: just the
        daily history; earnings_dates: also the earnings dates (when a source is configured)."""
        now = self.now()
        today = sessions.today(now)
        end = day or sessions.live_day(now)
        days = sessions.sessions_ending(end, history + 1)
        streamed_today = live and in_stream_hours(now)       # the stream delivers today's bars
        # market internals (NYSE TICK, TRIN) come along with every stock request, for the breadth studies
        if any(not control.is_index(s) for s in symbols) and not daily_only:
            symbols = list(dict.fromkeys([*symbols, *getattr(self.args, "companions", [])]))
        for sym in dict.fromkeys(f for f in (control.fetchable(s) for s in symbols) if f):   # recorded: nothing to fetch
            if self.contract(sym) is None:
                continue
            if live:
                self.live.add(sym)
            todo = [] if daily_only else [d for d in reversed(days) if not (streamed_today and d == today)
                                          and (d == today or not store.day_path(sym, d).exists())]
            for i, d in enumerate(todo):                     # the requested day first, then older days
                self.add_task("day", sym, d, front=front and i == 0)
            if self.args.daily_years > 0 and control.has_daily(sym) and daily_need(sym, end, self.args.daily_years):
                self.add_task("daily", sym, front=front and daily_only)
            if earnings_dates and self.earnings_source and earnings.is_stale(sym):
                self.add_task("earnings", sym, front=front)
        if live:
            control.save_live_symbols(self.live)

    def take_requests(self) -> None:
        for r in control.take_requests():
            if r.get("list"):                                 # a watch list from an outside source (FinViz)
                self.fetch_list(r["list"])
                continue
            syms = [s for s in (control.clean_symbol(x) for x in r.get("symbols", [])) if s]
            if r.get("stop_live"):
                self.live.difference_update(syms)
                control.save_live_symbols(self.live)
                log.info("Stopped streaming %s", ", ".join(syms))
                continue
            for s in syms:
                self.bad.pop(s, None)                        # asked again: try once more
            if isinstance(r.get("chain"), dict):              # the option-chain page: one moment's chain
                ch = r["chain"]
                key = ",".join(str(e) for e in ch.get("expiries") or []) + "|" + str(ch.get("window") or "")
                log.info("Option chain requested: %s %s", " ".join(syms), key)
                for s in syms:
                    self.add_task("chain", s, key, front=True)
                continue
            if r.get("options_for"):                         # the expected-move page: option quotes only
                log.info("Option quotes requested: %s for %s", " ".join(syms), r["options_for"])
                for s in syms:
                    self.add_task("options", s, str(r["options_for"]), front=True)
                continue
            log.info("Request from the chart page: %s %s%s", " ".join(syms), r.get("day") or "today",
                     " (live)" if r.get("live") else "")
            self.request(syms, r.get("day"), live=bool(r.get("live")), front=True,
                         daily_only=bool(r.get("daily_only")), earnings_dates=bool(r.get("earnings")))

    def run_task(self, task) -> None:
        kind, sym, day = task
        self.queued.discard(task)
        c = self.contract(sym)
        if c is None:
            return
        self.current = {"kind": kind, "symbol": sym, "day": day, "started": time.time()}
        self.write_status()
        self.pacer.note()
        if kind == "daily":
            n = fetch_daily(self.ib, c, sym, self.args.daily_years)
        elif kind == "earnings":
            n = self.fetch_earnings(sym)
        elif kind == "options":
            n = self.fetch_options(c, sym, day)
        elif kind == "chain":
            n = self.fetch_chain(c, sym, day)
        else:
            df = fetch_day(self.ib, c, day)
            n = len(df)
            if n:
                store.write_day(sym, day, df)
            log.info("%s %s: %s", sym, day, f"{n} bars cached" if n else "no bars (holiday, or no data permission)")
        self.results.append({"kind": kind, "symbol": sym, "day": day, "bars": n, "at": time.time()})
        self.current = None

    def fetch_list(self, ref) -> None:
        """A watch list from an outside source (tools/list_sources.py), cached in data/lists/ for the page; a
        failure too, so the page can say why. Not a TWS request: it doesn't wait in the queue."""
        if not list_sources.valid(ref):
            log.warning("Watch list request ignored: not a valid list reference")
            return
        fetcher = self.list_fetchers.get(ref["source"])
        name = list_sources.source(ref["source"]).name
        res = fetcher.load(ref) if fetcher else {"status": "off", "message": f"{name} lists are off (see .env.example)"}
        list_sources.write(ref, {**res, "fetched": time.time()})
        label = list_sources.source(ref["source"]).label(ref)
        if res["status"] == "ok":
            log.info("%s: %d symbols", label, len(res["symbols"]))
        else:
            log.warning("%s: %s", label, res.get("message"))

    def fetch_options(self, contract, sym: str, target: str) -> int:
        """Option quotes for the expected-move page (tools/option_quotes.py), cached in data/options/. A failure
        is cached too, so the page can say why."""
        try:
            data = self.option_quotes.fetch(contract, sym, target, self.now())
        except Exception as e:                       # noqa: BLE001  (TWS or ib_async: tell the page, carry on)
            data = {"symbol": sym, "target": target, "fetched": time.time(), "error": f"TWS: {e}"}
        expected_move.write(sym, data)
        if data.get("error"):
            log.warning("%s: option quotes: %s", sym, data["error"])
        return sum(len(e.get("quotes", {})) for e in (data.get("expiries") or {}).values())

    def fetch_chain(self, contract, sym: str, key: str) -> int:
        """An option chain for the option-chain page, cached in data/chains/ (a failure too, so the page can say
        why). key: "YYYYMMDD,YYYYMMDD|window"."""
        expiries, _, window = key.partition("|")
        try:
            w = int(window) if window.isdigit() else option_chain.DEFAULT_WINDOW
            data = self.option_quotes.fetch_chain(contract, sym, [e for e in expiries.split(",") if e],
                                                  min(max(w, 1), max(option_chain.WINDOWS)), self.now(),
                                                  previous=option_chain.read(sym))
        except Exception as e:                       # noqa: BLE001  (TWS or ib_async: tell the page, carry on)
            data = {"symbol": sym, "fetched": time.time(), "quoted_at": self.now().isoformat(), "error": f"TWS: {e}"}
        option_chain.write(sym, data)
        if data.get("error"):
            log.warning("%s: option chain: %s", sym, data["error"])
        return sum(len(e.get("quotes", {})) for e in (data.get("expiries") or {}).values())

    def fetch_earnings(self, sym: str) -> int:
        """Look up a symbol's earnings dates and cache them for the earnings page (failures are cached too, so
        the page can say why)."""
        res = self.earnings_source.lookup(sym)
        earnings.write(sym, {**res, "source": self.earnings_source.name, "fetched": time.time()})
        n = len(res.get("earnings") or [])
        if res.get("status") == "ok":
            log.info("%s: %d earnings reports found (%s): %s", sym, n, self.earnings_source.name,
                     ", ".join(f"{e['date']} {e['time']}" for e in res["earnings"][:8]))
        else:
            log.warning("%s: earnings lookup: %s", sym, res.get("message"))
        return n

    def morning(self, now: pd.Timestamp) -> None:
        """Once per trading day from 04:00: refresh the daily history and fill gaps for the live symbols."""
        day = sessions.today(now)
        if self.daily_done_for == day or now.hour < 4 or not sessions.is_trading_day(day):
            return
        self.daily_done_for = day
        if self.live:
            self.request(sorted(self.live), live=True)

    def live_contracts(self) -> dict:
        return {s: self.contracts[s] for s in sorted(self.live) if self.contract(s) is not None}

    def status(self) -> dict:
        return {"connected": True, "host": self.args.host, "port": self.args.port, "read_only": True,
                "live": sorted(self.live), "streaming": sorted(self.stream.subs), "market_open": self.stream.open,
                "queue": [{"kind": k, "symbol": s, "day": d} for k, s, d in list(self.tasks)[:60]],
                "queue_len": len(self.tasks), "current": self.current, "results": list(self.results),
                "bad_symbols": self.bad, "errors": list(self.errors), "message": None,
                "recording": sorted(self.recorder.tickers) if self.recorder else [],
                "not_recording": dict(self.recorder.failed) if self.recorder else {}}

    def write_status(self) -> None:
        try:
            control.write_status(self.status())
        except OSError as e:
            log.warning("Could not write status: %s", e)

    def step(self) -> None:
        """One pass of the live loop."""
        if not self.ib.isConnected():
            raise TWSUnavailable("connection to TWS was closed")
        now = self.now()
        self.take_requests()
        self.morning(now)
        self.stream.sync(now, self.live_contracts())
        if self.recorder:
            self.recorder.sync(now)
        if self.positions:
            self.positions.sync()
        if self.tasks and self.pacer.ready():
            self.run_task(self.tasks.popleft())
        self.write_status()

    def run(self) -> None:
        a = self.args
        start_days = a.days if not a.date else HISTORY_DAYS + 1
        self.request(a.symbols, a.date, live=a.live, history=start_days - 1)
        if a.refresh:
            for sym in a.symbols:
                for d in sessions.sessions_ending(a.date or sessions.live_day(self.now()), start_days):
                    self.add_task("day", sym, d)
        if not a.live:
            while self.tasks:
                if self.pacer.ready():
                    self.run_task(self.tasks.popleft())
                else:
                    self.ib.sleep(0.5)
            self.write_status()
            return
        log.info("Live mode: streaming %s, writing changed bars every %ss (Ctrl+C to stop)",
                 ", ".join(sorted(self.live)) or "nothing yet", a.write_every)
        while True:
            self.step()
            self.ib.sleep(1 if self.tasks else min(a.write_every, 2))

    def close(self) -> None:
        self.stream.cancel()
        if self.recorder:
            self.recorder.flush()
            self.recorder.cancel()


def connect(args):
    from ib_async import IB  # imported here so the rest of the module works without it
    from ib_async.ib import StartupFetchNONE
    ib = IB()
    try:
        # read-only, and without the account's positions, orders and executions: charts never need them
        ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=30, fetchFields=StartupFetchNONE)
    except (ConnectionRefusedError, OSError, TimeoutError) as e:
        raise TWSUnavailable(str(e)) from e
    return ib


def run_session(args) -> None:
    """Connect, then work the queue (and stream, in live mode) until done or the connection drops."""
    log.info("Connecting to TWS at %s:%s (read-only, client id %s)...", args.host, args.port, args.client_id)
    ib = connect(args)
    col = Collector(ib, args)
    try:
        col.run()
    finally:
        col.close()
        ib.disconnect()


def write_down_status(args, message: str) -> None:
    with contextlib.suppress(OSError):
        control.write_status({"connected": False, "host": args.host, "port": args.port, "read_only": True,
                              "message": message,
                              "live": control.load_live_symbols(), "streaming": [], "queue": [], "queue_len": 0,
                              "results": [], "bad_symbols": {}, "errors": []})


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", nargs="*", default=os.environ.get("SYMBOLS", "QQQ SPY").split(),
                   help="stock/ETF tickers to fetch at start (and stream, with --live)")
    p.add_argument("--companions", nargs="*", default=os.environ.get("COMPANIONS", "TICK-NYSE TRIN-NYSE").split(),
                   help="market indexes fetched with every stock request (default: TICK-NYSE TRIN-NYSE; "
                        "add TICK-NDX if your account has real-time Nasdaq index data)")
    p.add_argument("--days", type=int, default=int(os.environ.get("BACKFILL_DAYS", "30")),
                   help="trading days to backfill at start (default 30)")
    p.add_argument("--date", help="fetch this day (YYYY-MM-DD) and the 5 trading days before it, instead of --days")
    p.add_argument("--refresh", action="store_true", help="re-download days already cached")
    p.add_argument("--daily-years", type=int, default=int(os.environ.get("DAILY_YEARS", "10")),
                   help="years of daily bars to keep, for daily/weekly/monthly charts and long-history studies "
                        "(0 = skip, default 10)")
    p.add_argument("--live", action="store_true",
                   help="keep running: stream today's bars and take requests from the chart page")
    p.add_argument("--write-every", type=float, default=float(os.environ.get("LIVE_WRITE_SECONDS", "5")),
                   help="live mode: seconds between cache writes (default 5)")
    p.add_argument("--host", default=os.environ.get("IB_HOST", "host.docker.internal"), help="address of the PC running TWS")
    p.add_argument("--port", type=int, default=int(os.environ.get("IB_PORT", "7496")),
                   help="TWS API port: 7496 live, 7497 paper")
    p.add_argument("--client-id", type=int, default=int(os.environ.get("IB_CLIENT_ID", "17")))
    p.add_argument("--record", nargs="*", default=os.environ.get("RECORD", "ADD-NYSE VOLD-NYSE").split(),
                   help="live mode: series to record from live quotes (default: ADD-NYSE VOLD-NYSE; none to turn off)")
    p.add_argument("--sec-contact", default=os.environ.get("SEC_CONTACT") or None,
                   help="your name and email, sent to SEC EDGAR with earnings-date lookups (the SEC requires a "
                        "contact); leave unset to turn the lookups off")
    p.add_argument("--data-dir", default=os.environ.get("DATA_DIR"),
                   help="cache folder, e.g. a NAS share (default: ./data next to the app)")
    args = p.parse_args(argv)
    args.symbols = [s for s in (control.clean_symbol(x) for x in args.symbols) if s]
    args.companions = [s for s in (control.clean_symbol(x) for x in args.companions) if s]
    if args.date:
        args.date = sessions.session_on_or_before(args.date)
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.data_dir:
        store.DATA_DIR = Path(args.data_dir)
    envcheck.require_local_tws(args.host)        # TWS must be on this machine or the home network

    while True:
        try:
            run_session(args)
            return 0
        except (TWSUnavailable, ConnectionError, OSError) as e:
            hint = ("Is TWS running and logged in, with 'Enable ActiveX and Socket Clients' ticked, port "
                    f"{args.port}, and this machine's address under Trusted IPs? See the user guide, 'Connecting to TWS'.")
            if not args.live:
                log.error("Could not reach TWS at %s:%s (%s). %s", args.host, args.port, e, hint)
                return 2
            write_down_status(args, f"Can't reach TWS at {args.host}:{args.port} ({e}). Retrying every {RETRY_SECONDS}s.")
            log.warning("TWS not reachable (%s). Retrying in %ss. %s", e, RETRY_SECONDS, hint)
            time.sleep(RETRY_SECONDS)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
