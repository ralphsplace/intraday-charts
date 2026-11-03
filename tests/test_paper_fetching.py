"""Backtests fetch the days they have no bars for (app/paper/fetching.py, jobs.py): through the real collector
(tools/fetch_ibkr.py) on a fake TWS, with the requests and status files between them as in production."""
import threading
import time
from argparse import Namespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fake_tws
import fetch_ibkr
from app import control, sessions, store
from app.paper import backtest, fetching, jobs, rules, strategies

ET = "America/New_York"
CLOSE = {"price": "close"}
SMA = {"study": {"type": "sma", "params": {"length": 20}, "output": "sma"}}


class Collector:
    """The collector on a fake TWS, one step at a time (as tests/test_collector.py drives it)."""

    def __init__(self, at="2026-10-23 18:00"):
        self.t = pd.Timestamp(at, tz=ET)
        self.mono = 1000.0
        args = Namespace(symbols=[], days=3, date=None, refresh=False, daily_years=0, live=False, write_every=5.0,
                         host="h", port=7496, client_id=1, data_dir=None)
        self.ib = fake_tws.FakeIB(now=lambda: self.t)
        self.col = fetch_ibkr.Collector(self.ib, args, qualify=fake_tws.qualify, now=lambda: self.t, clock=lambda: self.mono)

    def step(self, *_):
        self.col.step()
        self.mono += 2.5
        self.t += pd.Timedelta(seconds=2.5)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetching, "POLL_SECONDS", 0.01)
    return tmp_path


def test_no_collector_no_fetch(cache):
    assert "isn't running" in fetching.collector_ready()
    control.write_status({"connected": False})
    assert "isn't connected" in fetching.collector_ready()
    with pytest.raises(ValueError, match="Can't fetch 1 missing day"):
        fetching.fetch("SPY", ["2026-10-20"])
    assert not control.pending_requests()                        # nothing asked of a collector that isn't there


def test_one_request_covers_six_days_latest_first():
    days = sessions.sessions_ending("2026-10-23", 10)            # 2026-10-12 .. 2026-10-23
    assert fetching.requests_for(days) == ["2026-10-23", "2026-10-15"]
    assert fetching.requests_for(["2026-10-12", "2026-10-23"]) == ["2026-10-23", "2026-10-12"]


def test_missing_days_are_fetched_and_days_tws_has_nothing_for_are_given_back(cache, monkeypatch):
    c = Collector()
    real = fetch_ibkr.fetch_day
    monkeypatch.setattr(fetch_ibkr, "fetch_day", lambda ib, con, d: real(ib, con, d).iloc[0:0] if d == "2026-10-14" else real(ib, con, d))
    c.step()                                                     # it says it's there
    days = sessions.sessions_ending("2026-10-23", 8)
    seen = []
    t = [0.0]

    def clock():
        t[0] += 1
        return t[0]
    left = fetching.fetch("SPY", days, progress=lambda got, n: seen.append((got, n)), sleep=c.step, clock=clock)
    assert left == ["2026-10-14"]                                # TWS sent nothing for it
    assert [d for d in days if store.day_path("SPY", d).exists()] == [d for d in days if d != "2026-10-14"]
    assert seen[-1] == (7, 8) and seen[0][1] == 8
    assert len([r for r in c.ib.requests if "SPY" in str(r)]) <= 2 * 6 + 1  # two requests of six days, no more


def test_days_not_traded_yet_are_not_asked_for(cache):
    c = Collector()
    c.step()
    assert fetching.fetch("SPY", ["2099-01-02"], sleep=c.step) == ["2099-01-02"]
    assert not control.pending_requests()


def test_a_collector_that_stops_answering_stops_the_wait(cache, monkeypatch):
    c = Collector()
    c.step()
    t = [0.0]

    def clock():
        t[0] += 100
        return t[0]
    with pytest.raises(ValueError, match="hasn't sent anything"):          # the request is never taken
        fetching.fetch("SPY", ["2026-10-20"], sleep=lambda *_: None, clock=clock)


def test_a_backtest_fetches_its_missing_days_then_runs(cache, paper_runner):
    paper_runner()
    from app.server import app
    http = TestClient(app, client=("192.168.1.20", 50000))
    rules.save("Cross up", {"conditions": [{"a": CLOSE, "op": "crosses_above", "b": SMA}]})
    rules.save("Cross down", {"conditions": [{"a": CLOSE, "op": "crosses_below", "b": SMA}]})
    strategies.save("Crosses", {"buy": '"Cross up"', "short": '"Cross down"', "qty": 10, "exits": {"stop": 0.6, "target": 1.0}})
    body = {"strategy_name": "Crosses", "symbol": "SPY", "start": "2026-10-19", "end": "2026-10-23", "baseline_runs": 1}
    r = http.post("/api/paper/backtests", json=body)
    assert r.status_code == 400 and "collector isn't running" in r.json()["detail"]
    r = http.post("/api/paper/backtests", json={**body, "missing": "stop"})
    assert r.status_code == 400 and "No cached bars for 5" in r.json()["detail"]
    assert backtest.defaults()["missing"] == "fetch"

    c = Collector()
    c.step()
    run = http.post("/api/paper/backtests", json=body).json()
    assert run["status"] == "queued" and run["fetch"] == {"got": 0, "wanted": 5}
    assert http.get("/api/paper/backtests").json()["runs"][0]["fetch"] == {"got": 0, "wanted": 5}
    stop = threading.Event()

    def collector():
        while not stop.is_set():
            c.step()
            time.sleep(0.005)
    threading.Thread(target=collector, daemon=True).start()
    try:
        for _ in range(1000):
            run = jobs.read(run["id"])
            if run["status"] in ("done", "failed"):
                break
            time.sleep(0.02)
    finally:
        stop.set()
    assert run["status"] == "done", run.get("error")
    assert run["fetch"]["got"] == 5 and run["skipped"] == [] and len(run["report"]["days"]) == 5
    texts = [x["text"] for x in run["log"]]
    assert texts[1].startswith("fetching 5 day(s) without cached bars from TWS") and "fetched 5 of 5 day(s)" in texts
    assert all(store.day_path("SPY", d).exists() for d in sessions.sessions_ending("2026-10-23", 5))
