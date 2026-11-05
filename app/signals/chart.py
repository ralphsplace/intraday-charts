"""A signal strategy on a chart (#83): its entries and exits as arrows on any symbol and day, not only in a
backtest. The day is worked through bar by bar with the backtest's engine (app/backtesting/backtest.run_day), as a
backtest would trade it, so an arrow never depends on a later bar; with cash enough that buying power never stops
an entry (these are signals, not an account's trades). Nothing is traded: nothing here places an order.

The result is kept until the day's bars change (a live day's file grows as bars arrive), so a chart that asks
again every few seconds costs a file check.
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict

from .. import store
from ..backtesting import backtest, engine, review
from . import strategies

CASH = 1e12                     # no entry is ever refused for buying power
KEEP = 64                       # days kept worked out
_kept: OrderedDict = OrderedDict()
_lock = threading.Lock()


def _trades(c: dict, symbol: str, day: str) -> list[dict]:
    try:
        stamp = store.day_path(symbol, day).stat().st_mtime_ns
    except OSError:
        raise ValueError(f"No bars cached for {symbol} on {day}") from None
    key = (json.dumps(c, sort_keys=True), symbol, day, stamp)
    with _lock:
        if key in _kept:
            _kept.move_to_end(key)
            return _kept[key]
    r = backtest.run_day(c, symbol, day, CASH, engine.DEFAULT_SETTINGS)
    trades = backtest.trades_of(day, r["fills"], with_open=True)
    with _lock:
        _kept[key] = trades
        while len(_kept) > KEEP:
            _kept.popitem(last=False)
    return trades


def day_markers(name: str, symbol: str, day: str, cursor: int | None = None, tf: int | None = None) -> dict:
    """{"strategy_name", "symbol", "day", "tf", "markers", "trades"} for the saved strategy `name` (KeyError when
    there's none), the arrows on the chart's `tf`-minute bars (default: the strategy's own). cursor (minute of the
    day, Replay): only what had happened before it."""
    st = strategies.all_strategies().get(name)
    if st is None:
        raise KeyError(f'No signal strategy called "{name}"')
    c = strategies.prepare(st)
    trades = _trades(c, symbol, day)
    if cursor is not None:
        trades = [t for t in trades if t["entry_minute"] < cursor]
    tf = tf or c["tf"]
    return {"strategy_name": name, "symbol": symbol, "day": day, "tf": tf,
            "markers": review.markers(symbol, day, tf, trades, cursor), "trades": len(trades)}
