"""How the chart server and the TWS collector talk: small JSON files in <data>/control/.

The two may run in different containers or on different machines (the collector on the TWS PC writing to
the NAS share), so they only share the data folder.

    control/requests/<id>.json   written by the server: fetch these symbols for this day / stream them live
    control/status.json          written by the collector every few seconds: connection, queue, results
    control/live_symbols.json    written by the collector: symbols streamed in live mode (kept across restarts)
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from . import store

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$")
STALE_SECONDS = 150      # a historical request can block the collector for up to ~2 minutes


# Market indexes the collector can fetch: symbol -> exchange (IBKR index contracts, secType IND)
INDEXES = {"TICK-NYSE": "NYSE", "TRIN-NYSE": "NYSE", "AD-NYSE": "NYSE", "VOL-NYSE": "NYSE",
           "TICK-NASD": "NASDAQ", "TICK-NDX": "NASDAQ", "TRIN-NASD": "NASDAQ", "VIX": "CBOE"}

# Series IBKR sends only as live quotes, with no history: the collector records them (tools/recorder.py) into
# 1-minute bars under these names, from the bid minus the ask of the index (IBKR's TWS API docs, market
# indicators): ADD = advancing - declining NYSE issues, VOLD = NYSE up volume - down volume.
RECORDED = {"ADD-NYSE": "AD-NYSE", "VOLD-NYSE": "VOL-NYSE"}

# Indexes with daily price history worth keeping (daily, weekly and monthly charts). The NYSE/Nasdaq indicators
# (TICK, TRIN, AD, VOL) are intraday series: their daily charts are built from the cached 1-minute days.
DAILY_INDEXES = {"VIX"}


def clean_symbol(s: str) -> str | None:
    s = (s or "").strip().upper()
    return s if SYMBOL_RE.match(s) or s in INDEXES or s in RECORDED or s in store.DERIVED else None


def is_index(s: str) -> bool:
    """An index rather than a stock (also the recorded series, and symbols derived from an index)."""
    return s in INDEXES or s in RECORDED or store.source(s) in INDEXES


def has_daily(s: str) -> bool:
    """Whether the collector keeps daily prices for `s` (stocks, ETFs and DAILY_INDEXES)."""
    return not is_index(s) or store.source(s) in DAILY_INDEXES


def fetchable(s: str) -> str | None:
    """What the collector asks IBKR for to chart `s`: the symbol, the base of a derived one, or None for a
    recorded series (no history to fetch)."""
    return None if s in RECORDED else store.source(s)


def control_dir() -> Path:
    return store.DATA_DIR / "control"


def requests_dir() -> Path:
    return control_dir() / "requests"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- requests (server -> collector)
def submit(symbols: list[str], day: str | None = None, live: bool = False, stop_live: bool = False,
           daily_only: bool = False, earnings: bool = False, options_for: str | None = None,
           chain: dict | None = None) -> dict:
    """A request to the collector. daily_only: just the daily history (no 1-minute days); earnings: also look
    up the symbols' earnings dates (the earnings page); options_for: instead, option quotes for the first expiry
    on or after that date (YYYY-MM-DD, the expected-move page); chain: instead, an option chain
    ({"expiries": [YYYYMMDD, ...], "window": strikes either side}, the option-chain page)."""
    req = {"id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}", "symbols": symbols, "day": day,
           "live": live, "stop_live": stop_live, "daily_only": daily_only, "earnings": earnings,
           "options_for": options_for, "chain": chain, "created": time.time()}
    write_json(requests_dir() / f"{req['id']}.json", req)
    return req


def pending_requests() -> list[dict]:
    d = requests_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        r = read_json(p)
        if isinstance(r, dict):
            out.append(r)
    return out


def take_requests() -> list[dict]:
    """Collector side: read and remove every waiting request, oldest first."""
    d = requests_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        r = read_json(p)
        with contextlib.suppress(OSError):
            p.unlink()
        if isinstance(r, dict):
            out.append(r)
    return out


# ---------------------------------------------------------------- status (collector -> server)
def write_status(status: dict) -> None:
    write_json(control_dir() / "status.json", {**status, "heartbeat": time.time()})


def read_status() -> dict:
    s = read_json(control_dir() / "status.json", {}) or {}
    age = time.time() - s["heartbeat"] if "heartbeat" in s else None
    s["age"] = age
    s["running"] = age is not None and age < STALE_SECONDS
    s["waiting_requests"] = len(pending_requests())
    return s


def live_symbols_path() -> Path:
    return control_dir() / "live_symbols.json"


def load_live_symbols() -> list[str]:
    v = read_json(live_symbols_path(), [])
    return [s for s in v if isinstance(s, str)] if isinstance(v, list) else []


def save_live_symbols(symbols) -> None:
    write_json(live_symbols_path(), sorted(symbols))
