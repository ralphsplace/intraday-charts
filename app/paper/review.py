"""A backtest's day, for a chart (#69): the symbol, the strategy's timeframe, the studies its rules read, and its
trades that day as entry and exit markers placed on the chart bars they filled in. The chart page shows them in
its review mode (/review?run=<id>&day=<day>). Read-only: from the run's own report."""
from __future__ import annotations

from .. import engine as day_engine
from ..studies import base as studies_base
from . import strategies

BUY, SELL = "#26a69a", "#ef5350"


def studies_of(c: dict) -> list[dict]:
    """The studies a prepared strategy reads, each once (a study read for two of its lines or levels is one
    study), with the settings the rules use: [{"type", "params"}]."""
    out = []
    for spec in strategies.studies(c):
        x = {"type": spec["type"], "params": spec["params"]}
        if x not in out and spec["type"] in studies_base.REGISTRY:
            out.append(x)
    return out


def day_view(run: dict, day: str) -> dict:
    """{"strategy_name", "symbol", "day", "tf", "studies", "trades", "markers", "when"}; KeyError when the run has
    no such day, ValueError when it hasn't finished."""
    if run.get("status") != "done":
        raise ValueError("The backtest hasn't finished")
    rep, c = run["report"], run["strategy"]
    if day not in rep["days"]:
        raise KeyError(f"The backtest has no day {day}")
    tf, symbol = c["tf"], rep["symbol"]
    ctx = day_engine.DayContext(symbol, day, tf, None)
    shown = ctx.shown[ctx.shown["day"] == ctx.shown["day"].iloc[-1]] if "day" in ctx.shown else ctx.shown   # this day's bars
    ct_of = {int(b): int(t) for b, t in zip(shown["bucket"], shown["ct"], strict=True)}

    def at(minute: int) -> int | None:                     # the chart bar a fill happened in
        return ct_of.get(minute - minute % tf)

    trades = [t for t in rep["trades"] if t["day"] == day]
    markers = []
    for n, t in enumerate(trades, 1):
        long = t["side"] == "long"
        for when, price, opening in ((t["entry_minute"], t["entry"], True), (t["exit_minute"], t["exit"], False)):
            buy = long == opening
            time = at(when)
            if time is None:
                continue
            word = ("Buy" if buy else "Sell") if opening else ("Sell" if long else "Cover")
            markers.append({"time": time, "position": "belowBar" if buy else "aboveBar", "shape": "arrowUp" if buy else "arrowDown",
                            "color": BUY if buy else SELL, "price": price, "trade": n,
                            "text": f"{n}: {word} {t['qty']} @ {price:.2f}" + ("" if opening else f" ({t['why'] or 'exit'}, {t['pnl']:+.2f})")})
    markers.sort(key=lambda m: m["time"])
    return {"strategy_name": run.get("strategy_name") or run.get("rule_name"), "symbol": symbol, "day": day, "tf": tf,
            "studies": studies_of(c), "trades": trades, "markers": markers,
            "when": {k: c.get(k) for k, _ in strategies.SIGNALS}}
