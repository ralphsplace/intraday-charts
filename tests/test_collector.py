"""The TWS collector's queue, live streaming and status, and the chart page endpoints that drive it."""
from argparse import Namespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fake_tws
import fetch_ibkr
from app import control, saved, sessions, store, watchlist

ET = "America/New_York"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


class Clock:
    def __init__(self, t="2026-10-20 10:00"):
        self.t = pd.Timestamp(t, tz=ET)
        self.mono = 1000.0

    def now(self):
        return self.t

    def monotonic(self):
        return self.mono

    def advance(self, secs):
        self.mono += secs
        self.t += pd.Timedelta(seconds=secs)


def make(cache, clock, live=True, symbols=(), **kw):
    args = Namespace(symbols=list(symbols), days=3, date=None, refresh=False, daily_years=2, live=live,
                     write_every=5.0, host="h", port=7496, client_id=1, data_dir=None, **kw)
    ib = fake_tws.FakeIB(now=clock.now)
    return ib, fetch_ibkr.Collector(ib, args, qualify=fake_tws.qualify, now=clock.now, clock=clock.monotonic)


def drain(col, clock, limit=200):
    for _ in range(limit):
        col.step()
        clock.advance(2.5)
        if not col.tasks:
            col.step()
            return
    raise AssertionError("queue never emptied")


# ---------------------------------------------------------------- trading calendar
def test_trading_calendar_skips_weekends_and_holidays():
    assert not sessions.is_trading_day("2026-11-26")            # Thanksgiving
    assert sessions.previous_session("2026-11-27") == "2026-11-25"
    assert sessions.session_on_or_before("2026-10-18") == "2026-10-16"   # Sunday -> Friday
    assert sessions.sessions_ending("2026-10-20", 3) == ["2026-10-16", "2026-10-19", "2026-10-20"]
    assert sessions.last_complete_session(pd.Timestamp("2026-10-20 08:14", tz=ET)) == "2026-10-19"
    assert sessions.last_complete_session(pd.Timestamp("2026-10-20 16:05", tz=ET)) == "2026-10-20"
    assert sessions.live_day(pd.Timestamp("2026-10-18 12:00", tz=ET)) == "2026-10-16"


# ---------------------------------------------------------------- queue
def test_page_request_fetches_day_and_history_requested_day_first(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=True)
    control.submit(["SPY"], day="2026-10-16")
    col.step()
    assert col.results[0]["day"] == "2026-10-16"              # the asked-for day comes first
    drain(col, clock)
    assert store.list_days("SPY") == sessions.sessions_ending("2026-10-16", 6)
    assert not store.read_daily("SPY").empty
    st = control.read_status()
    assert st["running"] and st["connected"] and st["queue_len"] == 0
    assert {r["day"] for r in st["results"] if r["kind"] == "day"} == set(store.list_days("SPY"))
    n = len(ib.requests)
    control.submit(["SPY"], day="2026-10-16")                  # cached: nothing more to fetch
    drain(col, clock)
    assert len(ib.requests) == n


def test_unknown_symbol_is_reported(cache):
    clock = Clock()
    ib, col = make(cache, clock)
    control.submit(["ZZZQ"], day="2026-10-16")
    drain(col, clock)
    assert "ZZZQ" in control.read_status()["bad_symbols"] and not ib.requests


def test_live_request_streams_and_keeps_symbol_across_restarts(cache):
    clock = Clock("2026-10-20 09:35")
    ib, col = make(cache, clock)
    control.submit(["NVDA"], live=True)
    drain(col, clock)
    assert col.stream.subs.keys() == {"NVDA"}
    today = store.read_day("NVDA", "2026-10-20")
    assert len(today) and today["time"].iloc[-1] <= clock.t
    assert store.list_days("NVDA")[-1] == "2026-10-20" and len(store.list_days("NVDA")) == 6
    # bars keep arriving and are written at most every write_every seconds
    clock.advance(180); ib.tick(); col.step()
    assert len(store.read_day("NVDA", "2026-10-20")) > len(today)
    assert control.load_live_symbols() == ["NVDA"]
    _, col2 = make(cache, clock)                                 # restart: still streamed
    assert col2.live == {"NVDA"}
    control.submit(["NVDA"], stop_live=True)
    col.step()
    assert not col.stream.subs and control.load_live_symbols() == []


def test_stream_pauses_after_hours_and_resubscribes_next_morning(cache):
    clock = Clock("2026-10-20 19:58")
    ib, col = make(cache, clock)
    control.submit(["QQQ"], live=True)
    drain(col, clock)
    assert col.stream.subs
    clock.t = pd.Timestamp("2026-10-20 20:05", tz=ET); col.step()
    assert not col.stream.subs and not col.stream.open
    clock.t = pd.Timestamp("2026-10-21 04:01", tz=ET); clock.advance(10); col.step()
    assert col.stream.day == "2026-10-21" and col.stream.subs


def test_started_after_hours_fetches_today_instead_of_streaming(cache):
    clock = Clock("2026-10-20 21:00")
    ib, col = make(cache, clock, symbols=["QQQ"])
    col.request(["QQQ"], live=True)
    drain(col, clock)
    assert "2026-10-20" in store.list_days("QQQ") and not col.stream.subs


def test_one_shot_run_fetches_a_date_and_stops(cache):
    clock = Clock()
    ib, col = make(cache, clock, live=False, symbols=["QQQ"])
    col.args.date = "2026-10-16"
    col.pacer.MIN_GAP = 0
    col.run()
    assert store.list_days("QQQ") == sessions.sessions_ending("2026-10-16", 6)


def test_pacer_limits_request_rate():
    t = [0.0]
    p = fetch_ibkr.Pacer(clock=lambda: t[0])
    sent = 0
    for _ in range(2000):
        if p.ready():
            p.note(); sent += 1
        t[0] += 0.25
    assert sent <= fetch_ibkr.Pacer.LIMIT * (500 / 600 + 1)
    assert sent >= 50


# ---------------------------------------------------------------- endpoints
def test_fetch_endpoint_validates_and_queues(cache):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))   # a device on the home network
    r = c.post("/api/fetch", json={"symbols": ["spy", "QQQ"], "day": "2026-10-18"})
    assert r.status_code == 200 and r.json()["day"] == "2026-10-16" and r.json()["symbols"] == ["SPY", "QQQ"]
    assert c.post("/api/fetch", json={"symbols": ["S P Y"]}).status_code == 400
    assert c.post("/api/fetch", json={"symbols": ["SPY"], "day": "2099-01-02"}).status_code == 400
    assert control.pending_requests()[0]["symbols"] == ["SPY", "QQQ"]
    st = c.get("/api/collector").json()
    assert not st["running"] and st["waiting_requests"] == 1
    assert "calendar" in c.get("/api/meta").json()


def test_saved_views_layouts_and_watchlists(cache):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))   # a device on the home network
    view = {"symbol": "QQQ", "tf": 3, "days": 2, "studies": [{"type": "vwap"}]}
    assert c.put("/api/saved/views/Opening drive", json=view).status_code == 200
    assert c.put("/api/saved/watchlists/Zone", json=["QQQ", "SPY"]).status_code == 200
    assert c.get("/api/saved/views").json() == {"Opening drive": view}
    assert c.put("/api/saved/views/a%2Fb", json=view).status_code in (400, 404)
    assert c.put("/api/saved/nope/x", json=view).status_code == 404
    c.delete("/api/saved/views/Opening drive")
    assert c.get("/api/saved/views").json() == {}
    zone = saved.all_items("watchlists")["Zone"]                    # a named watch list (app/watchlists.py)
    assert list(saved.all_items("watchlists")) == ["Zone"] and zone["symbols"] == ["QQQ", "SPY"] and zone["source"] == "symbols"


def test_watchlist_parsing():
    assert watchlist.parse_symbols("qqq, SPY\nnvda  brk.b")["symbols"] == ["QQQ", "SPY", "NVDA", "BRK.B"]
    tos = 'Watchlist "Zone"\n\nSymbol,Last,Net Chng\nQQQ,600.1,-1.2\n/ES,6700,3\n$SPX,6600,1\nAAPL,250,1\n'
    r = watchlist.parse_symbols(tos)
    assert r["symbols"] == ["QQQ", "AAPL"] and r["skipped"] == ["/ES", "$SPX"]
    assert watchlist.parse_symbols('No.,Ticker,Company\n1,"MSFT","Microsoft"\n')["symbols"] == ["MSFT"]
    assert watchlist.parse_symbols("DES,AAPL,STK,SMART\nDES,ES,FUT,CME\n")["symbols"] == ["AAPL"]


def test_requests_bring_nyse_tick_and_trin_along(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=False)
    col.args.companions = ["TICK-NYSE", "TRIN-NYSE"]
    control.submit(["QQQ"], day="2026-10-16")
    col.args.live = True
    drain(col, clock)
    assert "2026-10-16" in store.list_days("TICK-NYSE") and "2026-10-16" in store.list_days("TRIN-NYSE")
    assert store.read_daily("TICK-NYSE").empty                      # no daily history for indexes
    t = store.read_day("TICK-NYSE", "2026-10-16")
    assert (t["low"] < 0).any() and (t["high"] > 0).any()
    assert control.clean_symbol("tick-nyse") == "TICK-NYSE" and control.clean_symbol("TICK-XYZ") is None


def test_index_contracts():
    pytest.importorskip("ib_async")
    c = fetch_ibkr.make_stock("TICK-NYSE")
    assert (c.secType, c.exchange, c.symbol) == ("IND", "NYSE", "TICK-NYSE")
    assert fetch_ibkr.make_stock("QQQ").secType == "STK"
