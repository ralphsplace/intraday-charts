"""A signal strategy on a chart (app/signals/chart.py, /api/signal-strategies/<name>/chart): the arrows are the trades a
backtest of the same strategy makes that day (with cash enough that none is refused), placed on the chart's own
bars whatever its timeframe; in Replay only what had happened before the cursor; a trade still open shows its
entry; worked out again only when the day's bars change."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app import store
from app.backtesting import backtest, engine
from app.signals import chart, rules, strategies

CLOSE = {"price": "close"}
SMA = {"study": {"type": "sma", "params": {"length": 20}, "output": "sma"}}


@pytest.fixture
def on_demo(demo, monkeypatch):
    shutil.rmtree(demo / "user", ignore_errors=True)
    chart._kept.clear()
    rules.save("Cross up", {"conditions": [{"a": CLOSE, "op": "crosses_above", "b": SMA}]})
    rules.save("Cross down", {"conditions": [{"a": CLOSE, "op": "crosses_below", "b": SMA}]})
    strategies.save("Crosses", {"tf": 1, "buy": '"Cross up"', "short": '"Cross down"', "qty": 100_000,      # far more than $25,000 buys
                                "exits": {"stop": 0.6, "target": 1.0}})
    return demo


def day():
    return store.list_days("QQQ-DEMO")[3]


def test_the_arrows_are_a_backtests_trades_with_none_refused(on_demo):
    d = day()
    c = strategies.prepare(strategies.all_strategies()["Crosses"])
    want = backtest.trades_of(d, backtest.run_day(c, "QQQ-DEMO", d, chart.CASH, engine.DEFAULT_SETTINGS)["fills"])
    assert backtest.run_day(c, "QQQ-DEMO", d, 25_000, engine.DEFAULT_SETTINGS)["skipped"]      # an account would refuse them
    v = chart.day_markers("Crosses", "QQQ-DEMO", d)
    assert v["trades"] == len(want) > 2 and len(v["markers"]) == 2 * len(want)
    entries = [m for m in v["markers"] if ": Buy" in m["text"] or (": Sell" in m["text"] and "(" not in m["text"])]
    assert [round(m["price"], 4) for m in entries] == [round(t["entry"], 4) for t in want]
    assert {m["shape"] for m in v["markers"]} == {"arrowUp", "arrowDown"}


def test_the_arrows_sit_on_the_charts_own_bars(on_demo):
    d = day()
    one, three = chart.day_markers("Crosses", "QQQ-DEMO", d, tf=1), chart.day_markers("Crosses", "QQQ-DEMO", d, tf=3)
    assert three["tf"] == 3 and len(three["markers"]) == len(one["markers"])
    for a, b in zip(one["markers"], three["markers"], strict=True):
        assert b["time"] == a["time"] - a["time"] % 180 and b["text"] == a["text"]   # the 3-minute bar the fill is in


def test_in_replay_only_what_happened_before_the_cursor(on_demo):
    d = day()
    c = strategies.prepare(strategies.all_strategies()["Crosses"])
    trades = backtest.trades_of(d, backtest.run_day(c, "QQQ-DEMO", d, chart.CASH, engine.DEFAULT_SETTINGS)["fills"])
    t = next(t for t in trades[1:] if t["exit_minute"] - t["entry_minute"] >= 2)
    cursor = t["entry_minute"] + 1                                      # inside a trade: its entry, not its exit
    full = chart.day_markers("Crosses", "QQQ-DEMO", d)["markers"]
    early = chart.day_markers("Crosses", "QQQ-DEMO", d, cursor)["markers"]
    assert 0 < len(early) < len(full) and all(m in full for m in early)
    assert all((m["time"] % 86400) // 60 < cursor for m in early)                    # chart times are ET wall clock
    assert len(early) % 2 == 1 and early[-1]["price"] == pytest.approx(t["entry"])      # the open trade's entry, last


def test_an_open_trade_shows_its_entry():
    fills = [{"side": "buy", "qty": 10, "price": 100.0, "minute": 600, "commission": 1.0},
             {"side": "sell", "qty": 10, "price": 101.0, "minute": 610, "commission": 1.0, "note": "target"},
             {"side": "sell", "qty": 5, "price": 102.0, "minute": 620, "commission": 1.0}]
    assert len(backtest.trades_of("d", fills)) == 1
    open_ = backtest.trades_of("d", fills, with_open=True)[-1]
    assert open_["side"] == "short" and open_["exit_minute"] is None and open_["pnl"] is None


def test_worked_out_again_only_when_the_days_bars_change(on_demo, monkeypatch):
    d = day()
    calls = []
    real = backtest.run_day
    monkeypatch.setattr(backtest, "run_day", lambda *a, **k: calls.append(1) or real(*a, **k))
    chart.day_markers("Crosses", "QQQ-DEMO", d)
    chart.day_markers("Crosses", "QQQ-DEMO", d, 11 * 60)                # another cursor: the same day worked out
    assert len(calls) == 1
    p = store.day_path("QQQ-DEMO", d)
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))       # a live day's file grew
    chart.day_markers("Crosses", "QQQ-DEMO", d)
    assert len(calls) == 2


def test_the_endpoint(on_demo):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))
    d = day()
    r = c.get("/api/signal-strategies/Crosses/chart", params={"symbol": "QQQ-DEMO", "day": d, "tf": 3, "cursor": 700}).json()
    assert r["strategy_name"] == "Crosses" and r["tf"] == 3 and r["markers"]
    assert c.get("/api/signal-strategies/Nope/chart", params={"symbol": "QQQ-DEMO", "day": d}).status_code == 404
    assert c.get("/api/signal-strategies/Crosses/chart", params={"symbol": "QQQ-DEMO", "day": "2020-01-02"}).status_code == 400
    assert c.get("/api/signal-strategies/Crosses/chart", params={"symbol": "QQQ-DEMO", "day": d, "cursor": -1}).status_code == 422
