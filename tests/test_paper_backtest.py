"""Rule backtests (app/paper/backtest.py, jobs.py): a backtest and Replay practice fill the same; on a random walk a
rule does no better than random entries; missing days are said; and the background run end to end."""
import math
import statistics
import time

import pytest
from fastapi.testclient import TestClient

import synthetic
from app import store
from app.paper import accounts, backtest, engine, practice, rules, strategies
from paper_help import strategy
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
    """Long when the close crosses above its 20-bar SMA, short when below (a prepared strategy)."""
    return strategy(long=[{"a": CLOSE, "op": "crosses_above", "b": SMA}], short=[{"a": CLOSE, "op": "crosses_below", "b": SMA}],
                    **{"tf": 3, "qty": 10, "exits": {"stop": 0.6, "target": 1.0}, **kw})


def save_cross_strategy():
    rules.save("Cross up", {"conditions": [{"a": CLOSE, "op": "crosses_above", "b": SMA}]})
    return {"buy": '"Cross up"', "qty": 10, "exits": {"stop": 0.6, "target": 1.0}}


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
    st = save_cross_strategy()
    r = c.post("/api/paper/backtests", json={"strategy": st, "symbol": "QQQ-DEMO", "start": have[0], "end": "2026-12-31"})
    assert r.status_code == 400 and "No cached bars" in r.json()["detail"]
    strategies.save("Crosses", st)
    r = c.post("/api/paper/backtests", json={"strategy_name": "Crosses", "symbol": "QQQ-DEMO", "start": have[0], "end": have[4],
                                             "baseline_runs": 1}).json()
    assert r["strategy_name"] == "Crosses" and r["strategy"]["when"]["long"]["c"]["op"] == "crosses_above"   # what the rule said
    for _ in range(200):
        run = c.get(f"/api/paper/backtests/{r['id']}").json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "done", run.get("error")
    assert run["done"] == run["total"] and run["report"]["stats"]["trades"] >= 1
    assert run["log"][0]["text"].startswith('"Crosses" on QQQ-DEMO, 5 day(s)') and run["log"][-1]["text"].startswith("done:")
    day = run["report"]["trades"][0]["day"]
    v = c.get(f"/api/paper/backtests/{r['id']}/review", params={"day": day}).json()
    assert v["strategy_name"] == "Crosses" and v["markers"] and v["when"]["buy"] == '"Cross up"'
    assert c.get(f"/api/paper/backtests/{r['id']}/review", params={"day": "2020-01-02"}).status_code == 404
    assert "review" in c.get("/review").text.lower() and '"review": true' in c.get("/review").text
    assert c.get("/api/paper/backtests").json()["runs"][0]["id"] == r["id"]
    # saved into an account: each day opens as a practice session with the same fills
    name, _ = accounts.create("Backtests", start_cash=100_000)
    assert c.post(f"/api/paper/backtests/{r['id']}/save", json={"account": name}).json()["saved_days"] == 5
    day = next(t["day"] for t in run["report"]["trades"])
    v = practice.view(name, "QQQ-DEMO", day, 16 * 60 + 1)
    want = [(t["entry"], t["exit"]) for t in run["report"]["trades"] if t["day"] == day]
    fills = [f["price"] for f in v["fills"]]
    assert [(fills[i], fills[i + 1]) for i in range(0, len(fills), 2)] == want
    assert c.post("/api/paper/backtests", json={"strategy_name": "nope", "symbol": "QQQ-DEMO", "start": have[0], "end": have[1]}).status_code == 404
    assert c.delete(f"/api/paper/backtests/{r['id']}").json()["runs"] == []


def test_entries_the_account_cant_afford_are_counted_not_hidden(on_demo):
    """Long or short, a position may be worth at most the equity; signals beyond it are skipped and reported."""
    days = store.list_days("QQQ-DEMO")[:3]
    rep = backtest.run(cross_rule(qty=1000), "QQQ-DEMO", days, 25_000, engine.DEFAULT_SETTINGS, baseline_runs=0)
    assert rep["trades"] == [] and rep["skipped"]["count"] > 0 and "buying power" in rep["skipped"]["first"]


def test_backtest_defaults_are_kept_in_the_config_and_used_when_a_run_leaves_them_out(on_demo, monkeypatch):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))
    assert c.get("/api/paper/backtest-defaults").json() == backtest.BUILT_IN_DEFAULTS
    for bad in ({"symbol": ""}, {"baseline_runs": 21}, {"baseline_runs": True}, {"missing": "maybe"}, {"account": 3}):
        assert c.put("/api/paper/backtest-defaults", json=bad).status_code == 400, bad
    d = c.put("/api/paper/backtest-defaults", json={"symbol": " qqq-demo ", "baseline_runs": 0, "missing": "skip", "x": 1}).json()
    assert d == {"symbol": "QQQ-DEMO", "account": "", "baseline_runs": 0, "missing": "skip"}
    seen = {}
    monkeypatch.setattr("app.paper.jobs.start", lambda *a: seen.update(missing=a[5], runs=a[8]) or {"id": "x"})
    have = store.list_days("QQQ-DEMO")
    st = save_cross_strategy()
    c.post("/api/paper/backtests", json={"strategy": st, "symbol": "QQQ-DEMO", "start": have[0], "end": have[1]})
    assert seen == {"missing": "skip", "runs": 0}                         # the defaults
    c.post("/api/paper/backtests", json={"strategy": st, "symbol": "QQQ-DEMO", "start": have[0], "end": have[1],
                                         "missing": "stop", "baseline_runs": 3})
    assert seen == {"missing": "stop", "runs": 3}                         # the run's own
    assert c.delete("/api/paper/backtest-defaults").json() == backtest.BUILT_IN_DEFAULTS


def test_a_run_logs_what_it_did_and_shows_a_day_for_a_chart(on_demo):
    """The log: each signal acted on (or why not), each fill, a line a day. A day for a chart: the studies the rules
    read, and each trade's entry and exit as arrows on the chart bars they filled in."""
    from app.paper import review
    days = store.list_days("QQQ-DEMO")[:4]
    lines = []
    rep = backtest.run(cross_rule(), "QQQ-DEMO", days, 100_000, engine.DEFAULT_SETTINGS, baseline_runs=1,
                       log=lambda day, text, level="info": lines.append((day, level, text)))
    assert [x for x in lines if x[1] == "day"] == [(d, "day", x[2]) for d, x in zip(days, [y for y in lines if y[1] == "day"], strict=True)]
    fills = [x for x in lines if "filled:" in x[2]]
    assert len(fills) == 2 * len(rep["trades"])                              # every entry and exit
    assert any("long signal" in x[2] or "short signal" in x[2] for x in lines) and lines[-1][0] is None   # the baseline last
    run = {"id": "x", "status": "done", "strategy_name": "Crosses", "strategy": cross_rule(), "report": rep}
    day = rep["trades"][0]["day"]
    v = review.day_view(run, day)
    assert v["symbol"] == "QQQ-DEMO" and v["tf"] == 3 and [s["type"] for s in v["studies"]] == ["sma"]
    n = len([t for t in rep["trades"] if t["day"] == day])
    assert len(v["markers"]) == 2 * n and v["markers"] == sorted(v["markers"], key=lambda m: m["time"])
    first = v["trades"][0]
    entry = next(m for m in v["markers"] if m["trade"] == 1 and m["price"] == first["entry"])
    assert entry["shape"] == ("arrowUp" if first["side"] == "long" else "arrowDown")
    from app import engine as day_engine
    ctx = day_engine.DayContext("QQQ-DEMO", day, 3, None)
    bar = ctx.shown[ctx.shown["bucket"] == first["entry_minute"] - first["entry_minute"] % 3]
    assert entry["time"] == int(bar["ct"].iloc[0])                           # on the bar the entry filled in
    with pytest.raises(KeyError):
        review.day_view(run, "2020-01-02")
    with pytest.raises(ValueError, match="hasn't finished"):
        review.day_view({**run, "status": "running"}, day)


def test_an_atr_trailing_stop_trails_by_n_atrs_at_the_entry(on_demo):
    """trail_atr: 2 x ATR(14) on the strategy's bars, as it was when the entry went in; backtest and Replay
    practice fill it the same."""
    from app import study_values
    day = store.list_days("QQQ-DEMO")[3]
    r = cross_rule(exits={"trail_atr": 2, "atr_length": 14})
    res = backtest.run_day(r, "QQQ-DEMO", day, 100_000, engine.DEFAULT_SETTINGS)
    bracket = next(a for a in res["actions"] if a["kind"] == "bracket")
    assert bracket["stop"] == {"trail": {"atr": 2.0, "length": 14, "tf": 3}}          # kept as written
    atr = study_values.value("QQQ-DEMO", day, {"type": "atr", "params": {"length": 14}, "output": "atr", "tf": 3},
                             cursor=bracket["minute"])["value"]
    st = engine.new_state(100_000, engine.DEFAULT_SETTINGS)
    practice._apply(st, bracket, practice.last_price(practice.bars("QQQ-DEMO", day), bracket["minute"]), "QQQ-DEMO", day)
    trail = next(o for o in st["orders"] if o["type"] == "trail")
    assert trail["trail"]["amount"] == pytest.approx(2 * atr, abs=1e-3) and atr > 0
    st2, events, refused = practice.replay("QQQ-DEMO", day, 100_000, engine.DEFAULT_SETTINGS, res["actions"], 16 * 60 + 1)
    assert refused == [] and [(f["price"], f["minute"]) for f in events if f["event"] == "fill"] == \
        [(f["price"], f["minute"]) for f in res["fills"]]
    with pytest.raises(engine.PaperError, match="0 to 20 times"):
        practice.atr_distance("QQQ-DEMO", day, {"atr": 0, "length": 14, "tf": 3}, 600)
