"""Rule backtests (app/paper/backtest.py, jobs.py): a backtest and Replay practice fill the same; on a random walk a
rule does no better than random entries; missing days are said; and the background run end to end."""
import math
import statistics
import time

import pytest
from fastapi.testclient import TestClient

import synthetic
from app import store
from app.paper import accounts, backtest, engine, practice, rules
from test_backtest import write_random_walk

CLOSE = {"price": "close"}
SMA = {"study": {"type": "sma", "params": {"length": 20}, "output": "sma"}}


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("bt")
    synthetic.generate(d)
    return d


@pytest.fixture
def on_demo(demo, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    import shutil
    shutil.rmtree(demo / "user", ignore_errors=True)
    return demo


def cross_rule(**kw):
    return rules.check({"tf": 3, "long": [{"a": CLOSE, "op": "crosses_above", "b": SMA}],
                        "short": [{"a": CLOSE, "op": "crosses_below", "b": SMA}], "qty": 10,
                        "exits": {"stop": 0.6, "target": 1.0}, **kw})


def test_a_backtest_fills_exactly_as_replay_practice(on_demo):
    """The same actions, replayed through practice (as a person stepping through the day would place them), give
    the same fills: one engine, one set of rules."""
    day = store.list_days("QQQ-DEMO")[3]
    for r in (cross_rule(), cross_rule(order={"type": "limit", "offset": 0.05}), cross_rule(exits={"trail": 0.5, "reverse": True})):
        res = backtest.run_day(r, "QQQ-DEMO", day, 100_000, engine.DEFAULT_SETTINGS)
        assert res["actions"], "the rule should trade on this day"
        st, events, refused = practice.replay("QQQ-DEMO", day, 100_000, engine.DEFAULT_SETTINGS, res["actions"], 16 * 60 + 1)
        assert refused == []
        assert [(f["side"], f["qty"], f["price"], f["minute"]) for f in events if f["event"] == "fill"] == \
               [(f["side"], f["qty"], f["price"], f["minute"]) for f in res["fills"]]
        assert st["cash"] == pytest.approx(res["cash"]) and st["position"]["qty"] == 0


def test_trades_and_stats(on_demo):
    days = store.list_days("QQQ-DEMO")[:6]
    rep = backtest.run(cross_rule(), "QQQ-DEMO", days, 100_000, engine.DEFAULT_SETTINGS, baseline_runs=2)
    s = rep["stats"]
    assert s["trades"] == len(rep["trades"]) > 0
    assert rep["end_cash"] == pytest.approx(100_000 + sum(t["pnl"] for t in rep["trades"]))
    assert s["long"]["trades"] + s["short"]["trades"] == s["trades"] and s["max_drawdown"] <= 0
    assert [e["day"] for e in rep["equity"]] == days and rep["baseline"]["trades"] > 0 and rep["demo"]


def test_on_a_random_walk_a_rule_does_no_better_than_random_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    write_random_walk(days=25)
    free = {**engine.DEFAULT_SETTINGS, "commission": {"per_share": 0, "minimum": 0, "max_pct": 1}, "slippage": 0}
    rep = backtest.run(cross_rule(), "RW", store.list_days("RW"), 1_000_000, free, baseline_runs=3)
    ours, base = [t["pnl"] for t in rep["trades"]], rep["baseline"]
    assert len(ours) > 50 and base["trades"] > 100            # random entries also wait for the last trade to end
    se = statistics.pstdev(ours) / math.sqrt(len(ours))
    assert abs(statistics.mean(ours)) < 3 * se                          # no edge where there is none
    assert abs(statistics.mean(ours) - base["total"] / base["trades"]) < 4 * se


def test_missing_days_are_said(on_demo):
    have = store.list_days("QQQ-DEMO")
    days, gaps = backtest.trading_days("QQQ-DEMO", have[0], "2026-12-31")
    assert days == have and gaps and all(g > have[-1] for g in gaps)
    with pytest.raises(ValueError, match="end is before"):
        backtest.trading_days("QQQ-DEMO", "2026-10-02", "2026-10-01")


def test_a_background_run_end_to_end(on_demo):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))
    have = store.list_days("QQQ-DEMO")
    rule = {"tf": 3, "long": [{"a": CLOSE, "op": "crosses_above", "b": SMA}], "qty": 10, "exits": {"stop": 0.6, "target": 1.0}}
    r = c.post("/api/paper/backtests", json={"rule": rule, "symbol": "QQQ-DEMO", "start": have[0], "end": "2026-12-31"})
    assert r.status_code == 400 and "No cached bars" in r.json()["detail"]
    r = c.post("/api/paper/backtests", json={"rule": rule, "symbol": "QQQ-DEMO", "start": have[0], "end": have[4],
                                             "baseline_runs": 1}).json()
    for _ in range(200):
        run = c.get(f"/api/paper/backtests/{r['id']}").json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "done", run.get("error")
    assert run["done"] == run["total"] and run["report"]["stats"]["trades"] >= 1
    assert c.get("/api/paper/backtests").json()["runs"][0]["id"] == r["id"]
    # saved into an account: each day opens as a practice session with the same fills
    name, _ = accounts.create("Backtests", start_cash=100_000)
    assert c.post(f"/api/paper/backtests/{r['id']}/save", json={"account": name}).json()["saved_days"] == 5
    day = next(t["day"] for t in run["report"]["trades"])
    v = practice.view(name, "QQQ-DEMO", day, 16 * 60 + 1)
    want = [(t["entry"], t["exit"]) for t in run["report"]["trades"] if t["day"] == day]
    fills = [f["price"] for f in v["fills"]]
    assert [(fills[i], fills[i + 1]) for i in range(0, len(fills), 2)] == want
    assert c.post("/api/paper/backtests", json={"rule_name": "nope", "symbol": "QQQ-DEMO", "start": have[0], "end": have[1]}).status_code == 404
    assert c.delete(f"/api/paper/backtests/{r['id']}").json()["runs"] == []


def test_entries_the_account_cant_afford_are_counted_not_hidden(on_demo):
    """Long or short, a position may be worth at most the equity; signals beyond it are skipped and reported."""
    days = store.list_days("QQQ-DEMO")[:3]
    rep = backtest.run(cross_rule(qty=1000), "QQQ-DEMO", days, 25_000, engine.DEFAULT_SETTINGS, baseline_runs=0)
    assert rep["trades"] == [] and rep["skipped"]["count"] > 0 and "buying power" in rep["skipped"]["first"]
