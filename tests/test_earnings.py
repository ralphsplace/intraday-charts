"""The earnings view: reaction days, the % windows, split handling, the SEC EDGAR source (against hand-written
samples in EDGAR's format, no network), the collector's earnings requests, and the endpoints and page route."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import earnings_sources
import synthetic
from app import control, earnings, store
from test_collector import Clock, drain, make


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def daily(closes, start="2026-01-05"):
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start=start, periods=len(closes))]
    return pd.DataFrame({"date": dates, "open": closes, "high": closes, "low": closes, "close": closes, "volume": 1e6})


# ---------------------------------------------------------------- reports and reaction days
def test_reaction_day_follows_the_report_time():
    dates = ["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03"]
    assert earnings.reaction_index(dates, {"date": "2026-07-29", "time": "07:00"}) == 1       # before the open: same day
    assert earnings.reaction_index(dates, {"date": "2026-07-29", "time": "12:30"}) == 1       # during the session
    assert earnings.reaction_index(dates, {"date": "2026-07-29", "time": "16:05"}) == 2       # after the close: next day
    assert earnings.reaction_index(dates, {"date": "2026-07-31", "time": "16:30"}) == 4       # Friday evening: Monday
    assert earnings.reaction_index(dates, {"date": "2026-08-01", "time": "09:00"}) == 4       # a Saturday filing
    assert earnings.reaction_index(dates, {"date": "2026-08-03", "time": "16:10"}) is None    # not traded yet
    assert [earnings.timing(t) for t in ("06:59", "09:30", "15:59", "16:00")] == \
        ["before the open", "during the session", "during the session", "after the close"]


def test_preliminary_notices_dont_count_as_reports():
    rows = [{"date": "2026-01-10", "time": "08:00"}, {"date": "2026-01-28", "time": "16:05"},   # notice, then report
            {"date": "2026-04-29", "time": "16:05"}, {"date": "2026-07-29", "time": "16:05"}]
    assert [r["date"] for r in earnings.reports(rows)] == ["2026-07-29", "2026-04-29", "2026-01-28"]


# ---------------------------------------------------------------- windows
def test_window_is_relative_to_the_day_before_day_0():
    closes = [100 + i for i in range(30)]
    w = earnings.window(daily(closes), 15)
    assert [p["x"] for p in w["points"]] == list(range(-10, 6))
    by = {p["x"]: p for p in w["points"]}
    assert by[-1]["pct"] == 0 and by[0]["pct"] == pytest.approx((115 / 114 - 1) * 100, abs=1e-3)
    assert by[-1]["price"] == 114 and by[0]["price"] == 115 and not w["splits"]
    short = earnings.window(daily(closes), 27)          # a recent report: only 2 days after so far
    assert [p["x"] for p in short["points"]][-1] == 2


def test_levels_dont_matter_only_moves():
    """A stock at $20 and the same stock at $400 make the same relative line (splits, re-rating); the price view
    keeps their levels."""
    a = earnings.window(daily([20 * (1 + 0.01 * i) for i in range(20)]), 12)
    b = earnings.window(daily([400 * (1 + 0.01 * i) for i in range(20)]), 12)
    assert [p["pct"] for p in a["points"]] == [p["pct"] for p in b["points"]]
    assert [round(p["price"] * 20, 6) for p in a["points"]] == [round(p["price"], 6) for p in b["points"]]


def test_a_split_inside_a_window_is_adjusted_and_reported():
    closes = [1000.0] * 8 + [100.0] * 12                # 10:1 split, unadjusted data (IBKR adjusts; this is the safety net)
    w = earnings.window(daily(closes), 12)
    assert all(abs(p["pct"]) < 1e-9 for p in w["points"]) and w["splits"][0]["ratio"] == "10:1"
    assert {p["price"] for p in w["points"]} == {100.0}              # the price view is adjusted too
    rev = earnings.window(daily([5.0] * 8 + [50.0] * 12), 12)
    assert rev["splits"][0]["ratio"] == "1:10"
    real = earnings.window(daily([100.0] * 12 + [70.0] * 8), 12)   # a real -30% day isn't a split
    assert not real["splits"] and min(p["pct"] for p in real["points"]) == pytest.approx(-30)


def test_view_on_synthetic_earnings(cache):
    synthetic.generate_earnings(cache, "ACME-DEMO")
    v = earnings.view("ACME-DEMO")
    assert v["status"] == "ok" and len(v["quarters"]) == earnings.QUARTERS
    days = [q["day0"] for q in v["quarters"]]
    assert days == sorted(days, reverse=True)                          # newest first
    for q in v["quarters"]:
        xs = [p["x"] for p in q["points"]]
        assert xs[0] == -earnings.BEFORE and 0 in xs and q["move"] == next(p["pct"] for p in q["points"] if p["x"] == 0)
        after = q["report_time"] >= "16:00"
        assert (q["day0"] > q["report_date"]) == after


def test_days_before_and_after_can_be_chosen(cache):
    synthetic.generate_earnings(cache, "ACME-DEMO")
    v = earnings.view("ACME-DEMO", before=3, after=8)
    assert (v["before"], v["after"], v["max_days"]) == (3, 8, earnings.MAX_DAYS)
    old = v["quarters"][-1]                                              # an old report: every day is there
    assert [p["x"] for p in old["points"]] == list(range(-3, 9))
    assert next(p["pct"] for p in old["points"] if p["x"] == -1) == 0  # still relative to day -1
    wide = earnings.view("ACME-DEMO", before=earnings.MAX_DAYS, after=earnings.MAX_DAYS)
    assert wide["status"] == "ok" and min(p["x"] for p in wide["quarters"][-1]["points"]) == -earnings.MAX_DAYS
    for bad in ((0, 5), (10, 0), (earnings.MAX_DAYS + 1, 5)):
        with pytest.raises(ValueError):
            earnings.view("ACME-DEMO", before=bad[0], after=bad[1])


def test_view_says_what_is_missing(cache):
    assert earnings.view("NVDA")["missing"] == ["earnings dates", "daily prices"]
    earnings.write("SPY", {"source": "x", "fetched": 1, "status": "ok", "earnings": []})
    store.write_daily("SPY", daily([100.0] * 30))
    v = earnings.view("SPY")
    assert v["status"] == "no_earnings" and "funds" in v["message"]
    earnings.write("ZZZ", {"source": "x", "fetched": 1, "status": "not_found", "message": "not at the SEC"})
    store.write_daily("ZZZ", daily([100.0] * 30))
    assert earnings.view("ZZZ")["status"] == "not_found"


def test_cache_staleness(cache):
    assert earnings.is_stale("NVDA")
    earnings.write("NVDA", {"fetched": 1000.0, "status": "ok", "earnings": []})
    assert not earnings.is_stale("NVDA", now=1000.0 + 3600)
    assert earnings.is_stale("NVDA", now=1000.0 + earnings.REFRESH_SECONDS + 1)
    earnings.write("NVDA", {"fetched": 1000.0, "status": "error", "message": "x"})
    assert earnings.is_stale("NVDA", now=1000.0 + 3601)                # failed lookups retry after an hour
    earnings.write("ASML", {"source": "by hand", "status": "ok", "earnings": [{"date": "2026-07-15", "time": "07:00"}]})
    assert not earnings.is_stale("ASML", now=1e12)                     # written by hand: never replaced


# ---------------------------------------------------------------- SEC EDGAR source (hand-written samples, no network)
TICKERS = {"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
           "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}}


def recent(rows):
    """EDGAR's parallel-array filing block from (form, items, acceptanceDateTime) rows. Invented sample, not real filings."""
    return {"form": [r[0] for r in rows], "items": [r[1] for r in rows], "acceptanceDateTime": [r[2] for r in rows],
            "accessionNumber": [f"0000000000-26-{i:06d}" for i in range(len(rows))]}


def edgar(pages, calls=None):
    def fetch(url):
        (calls if calls is not None else []).append(url)
        return json.dumps(pages[url]).encode()
    return fetch


def test_edgar_finds_item_202_filings_with_their_times(tmp_path):
    sub = {"name": "NVIDIA CORP", "filings": {"recent": recent([
        ("8-K", "2.02,9.01", "2026-08-26T16:20:43.000Z"),
        ("4", "", "2026-08-20T18:00:00.000Z"),
        ("8-K", "5.02", "2026-06-10T08:00:00.000Z"),           # not earnings
        ("8-K/A", "2.02", "2026-06-01T09:00:00.000Z"),         # an amendment repeats a report
        ("8-K", "2.02,7.01,9.01", "2026-05-27T16:21:00.000Z")]), "files": []}}
    calls = []
    src = earnings_sources.SecEdgar("Jane Doe jane@example.com", cache_dir=tmp_path,
                                    fetch=edgar({earnings_sources.TICKERS_URL: TICKERS,
                                                 earnings_sources.SUBMISSIONS_URL.format(name="CIK0001045810.json"): sub}, calls))
    res = src.lookup("NVDA")
    assert res["status"] == "ok" and res["cik"] == 1045810
    assert [(e["date"], e["time"]) for e in res["earnings"]] == [("2026-08-26", "16:20"), ("2026-05-27", "16:21")]
    assert "jane@example.com" in src.agent
    src.lookup("NVDA")                                         # the ticker list is cached
    assert calls.count(earnings_sources.TICKERS_URL) == 1


def test_edgar_reads_older_filing_lists_for_busy_filers():
    old = recent([("8-K", "2.02", f"2025-{m:02d}-15T16:05:00.000Z") for m in (2, 5, 8, 11)])
    sub = {"name": "BUSY", "filings": {"recent": recent([("8-K", "2.02", "2026-02-15T16:05:00.000Z")] +
                                                        [("424B2", "", "2026-01-01T10:00:00.000Z")] * 50),
                                       "files": [{"name": "CIK0001067983-submissions-001.json"}]}}
    pages = {earnings_sources.TICKERS_URL: TICKERS,
             earnings_sources.SUBMISSIONS_URL.format(name="CIK0001067983.json"): sub,
             earnings_sources.SUBMISSIONS_URL.format(name="CIK0001067983-submissions-001.json"): old}
    res = earnings_sources.SecEdgar("x", fetch=edgar(pages)).lookup("BRK.B")      # BRK.B is BRK-B at the SEC
    assert len(res["earnings"]) == 5 and res["earnings"][0]["date"] == "2026-02-15"


def test_edgar_unknown_ticker_and_failures():
    src = earnings_sources.SecEdgar("x", fetch=edgar({earnings_sources.TICKERS_URL: TICKERS}))
    assert src.lookup("ASML")["status"] == "not_found"

    def down(url):
        raise OSError("network unreachable")
    res = earnings_sources.SecEdgar("x", fetch=down).lookup("NVDA")
    assert res["status"] == "error" and "network unreachable" in res["message"]
    assert earnings_sources.make_source(None) is None and earnings_sources.make_source("") is None


# ---------------------------------------------------------------- the collector
class StubSource:
    name = "stub"

    def __init__(self):
        self.asked = []

    def lookup(self, symbol):
        self.asked.append(symbol)
        return {"status": "ok", "earnings": [{"date": "2026-07-29", "time": "16:05"}]}


def test_earnings_request_fetches_daily_prices_and_dates_only(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=True)
    col.earnings_source = StubSource()
    control.submit(["NVDA"], daily_only=True, earnings=True)
    drain(col, clock)
    assert store.list_days("NVDA") == []                     # no 1-minute days, no market internals
    assert not store.read_daily("NVDA").empty
    assert col.earnings_source.asked == ["NVDA"]
    assert earnings.read("NVDA")["earnings"][0]["date"] == "2026-07-29" and earnings.read("NVDA")["source"] == "stub"
    control.submit(["NVDA"], daily_only=True, earnings=True)  # cached and fresh: not looked up again
    drain(col, clock)
    assert col.earnings_source.asked == ["NVDA"]


def test_no_lookups_without_a_contact(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=True)
    assert col.earnings_source is None                        # SEC_CONTACT unset
    control.submit(["NVDA"], daily_only=True, earnings=True)
    drain(col, clock)
    assert earnings.read("NVDA") is None and not store.read_daily("NVDA").empty


# ---------------------------------------------------------------- endpoints and page
@pytest.fixture
def client(cache, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_earnings_endpoints(client, cache, monkeypatch):
    assert client.get("/earnings").status_code == 200
    v = client.get("/api/earnings", params={"symbol": "nvda"}).json()
    assert v["status"] == "off" and "SEC_CONTACT" in v["message"]
    monkeypatch.setenv("SEC_CONTACT", "Jane Doe jane@example.com")
    v = client.get("/api/earnings", params={"symbol": "NVDA"}).json()
    assert v["status"] == "missing" and v["lookups_on"]
    assert client.post("/api/earnings/request", json={"symbol": "NVDA"}).status_code == 200
    req = control.pending_requests()[-1]
    assert req["symbols"] == ["NVDA"] and req["daily_only"] and req["earnings"]
    assert client.get("/api/earnings", params={"symbol": "not a symbol"}).status_code == 400
    assert client.post("/api/earnings/request", json={"symbol": "ACME-DEMO"}).status_code == 400   # synthetic: never fetched
    synthetic.generate_earnings(cache, "ACME-DEMO")
    v = client.get("/api/earnings", params={"symbol": "ACME-DEMO"}).json()
    assert v["status"] == "ok" and len(v["quarters"]) == 6 and "SYNTHETIC" in v["source"]
    assert (v["before"], v["after"]) == (earnings.BEFORE, earnings.AFTER)        # the defaults
    v = client.get("/api/earnings", params={"symbol": "ACME-DEMO", "before": 20, "after": 15}).json()
    assert (v["before"], v["after"]) == (20, 15) and v["quarters"][-1]["points"][0]["x"] == -20
    for bad in ({"before": 0}, {"after": earnings.MAX_DAYS + 1}, {"before": "x"}):
        assert client.get("/api/earnings", params={"symbol": "ACME-DEMO", **bad}).status_code == 422, bad


def test_earnings_is_not_a_dashboard_name():
    from app import dashboards
    assert not dashboards.valid_name("earnings") and not dashboards.valid_name("Earnings")


def test_environment_check_says_when_the_collector_goes_online(monkeypatch):
    from app import envcheck
    monkeypatch.setenv("SEC_CONTACT", "x")
    on = next(c for c in envcheck.run() if c["name"] == "Internet access")["detail"]
    monkeypatch.delenv("SEC_CONTACT")
    off = next(c for c in envcheck.run() if c["name"] == "Internet access")["detail"]
    assert "sec.gov" in on and "off" in off
