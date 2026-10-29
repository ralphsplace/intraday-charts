"""The expected-move view: choosing expiries, the straddle and its interpolation, the event priced between expiries,
the diagonal's legs, the warnings, the collector's option requests (against the fake TWS's invented chain) and the
endpoints and page route."""
import pytest
from fastapi.testclient import TestClient

import fake_tws
import synthetic
from app import control, dashboards, expected_move, store
from test_collector import Clock, drain, make



@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def q(bid, ask, iv=None):
    return {"bid": bid, "ask": ask, "last": None, "close": None, "iv": iv}


def hand_cache(quotes, price=101.0, market_open=True, prev=None):
    """A cache for one expiry (2026-10-30) with quotes {strike: (call, put)}, quoted Wed 2026-10-28 10:00."""
    exp = {"20261030": {"quotes": {f"{k:g}": {"C": c, "P": p} for k, (c, p) in quotes.items()}}}
    if prev:
        exp["20261028"] = {"quotes": {f"{k:g}": {"C": c, "P": p} for k, (c, p) in prev.items()}}
    return {"symbol": "XYZ", "target": "2026-10-30", "fetched": 0, "quoted_at": "2026-10-28T10:00:00-04:00",
            "market_open": market_open, "price": price, "price_source": "last", "chosen": "20261030",
            "prev": "20261028" if prev else None, "next": None, "expiries": exp, "warnings": []}


# ---------------------------------------------------------------- expiries
def test_expiry_is_the_first_on_or_after_the_date_and_the_next_weekly_a_week_on():
    ex = ["20261026", "20261028", "20261030", "20261102", "20261104", "20261106", "20261113"]
    p = expected_move.pick_expiries(ex, "2026-10-29", "2026-10-27")
    assert p == {"chosen": "20261030", "prev": "20261028", "next": "20261106"}       # Fri -> next Fri, not Mon or Wed
    assert expected_move.pick_expiries(ex, "2026-10-30", "2026-10-27")["chosen"] == "20261030"
    assert expected_move.pick_expiries(ex, "2026-12-01", "2026-10-27")["chosen"] is None
    # an expiry already gone isn't the "previous" one
    assert expected_move.pick_expiries(ex, "2026-10-30", "2026-10-29")["prev"] is None


# ---------------------------------------------------------------- the straddle and the moves
def test_straddle_is_interpolated_to_the_price(cache):
    expected_move.write("XYZ", hand_cache({100: (q(3.9, 4.1, .4), q(2.9, 3.1, .4)), 102: (q(2.9, 3.1, .4), q(3.9, 4.1, .4))}))
    v = expected_move.view("XYZ", "2026-10-30")
    assert v["status"] == "ok" and v["straddle"]["value"] == pytest.approx(7.0)     # 7 at 100, 7 at 102
    assert [m["name"] for m in v["moves"]][:2] == ["Straddle (expected move)", "0.85 x straddle"]
    assert v["moves"][0]["low"] == pytest.approx(94.0) and v["moves"][1]["move"] == pytest.approx(5.95)
    # 1 sigma = S * IV * sqrt(T): 2.25 days to Friday 16:00, counted from the quote time, not from now
    assert v["days"] == pytest.approx(2.25)
    assert v["moves"][2]["move"] == pytest.approx(101 * 0.4 * (2.25 / 365) ** 0.5, abs=0.01)
    assert v["warnings"] == [] and v["event"] is None and v["diagonal"] is None


def test_warnings_for_wide_quotes_parity_and_after_hours(cache):
    expected_move.write("XYZ", hand_cache({100: (q(1.0, 3.0), q(0.9, 1.1))}, price=105.0, market_open=False))
    w = expected_move.view("XYZ", "2026-10-30")["warnings"]
    assert any("outside regular hours" in x for x in w)
    assert any("Wide bid/ask" in x and "100 call" in x for x in w)
    assert any("imply a price near 101.00" in x for x in w)                          # 100 + 2 - 1, not 105


def test_statuses(cache):
    assert expected_move.view("XYZ", "2026-10-30")["status"] == "missing"
    expected_move.write("XYZ", hand_cache({100: (q(1, 1.1), q(1, 1.1))}))
    v = expected_move.view("XYZ", "2026-11-06")
    assert v["status"] == "missing" and "another date" in v["message"]
    expected_move.write("XYZ", {"symbol": "XYZ", "target": "2026-10-30", "fetched": 0, "error": "TWS: boom"})
    assert expected_move.view("XYZ", "2026-10-30") == {**expected_move.view("XYZ", "2026-10-30"), "status": "error",
                                                         "message": "TWS: boom"}


# ---------------------------------------------------------------- the fake TWS's chain end to end
def test_synthetic_quotes_find_the_event_and_the_diagonal(cache):
    synthetic.generate_options(cache)
    v = expected_move.view("ACME-DEMO", synthetic.DEMO_OPTIONS_DATE)
    assert v["status"] == "ok" and (v["expiry"], v["prev_expiry"], v["next_expiry"]) == ("20261030", "20261028", "20261106")
    assert v["event"]["found"] and v["event"]["pct"] == pytest.approx(fake_tws.FAKE_EVENT_MOVE * 100, abs=0.2)
    assert v["event"]["prev_iv"] == pytest.approx(fake_tws.FAKE_BASE_IV, abs=0.01)
    d, price, move = v["diagonal"], v["price"], v["straddle"]["value"]
    assert d["short_expiry"] == "20261030" and d["long_expiry"] == "20261106"
    # short legs at the strikes nearest price +/- move, long legs one strike closer to the money
    assert abs(d["call"]["short_strike"] - (price + move)) <= 1 and abs(d["put"]["short_strike"] - (price - move)) <= 1
    assert d["call"]["long_strike"] < d["call"]["short_strike"] and d["put"]["long_strike"] > d["put"]["short_strike"]
    assert d["call"]["net"] == pytest.approx(d["call"]["long"] - d["call"]["short"], abs=0.011)
    assert v["warnings"] == []


def test_collector_fetches_option_quotes_on_request(cache):
    clock = Clock("2026-10-28 10:00")
    ib, col = make(cache, clock, live=True)
    col.option_quotes.option = fake_tws.FakeOption
    control.submit(["AMZN"], options_for="2026-10-30")
    drain(col, clock)
    v = expected_move.view("AMZN", "2026-10-30")
    assert v["status"] == "ok" and v["event"]["found"] and v["diagonal"]["net"] is not None
    assert store.list_days("AMZN") == []                                     # option quotes only, no 1-minute bars


def test_collector_caches_a_failure(cache):
    clock = Clock("2026-10-28 10:00")
    ib, col = make(cache, clock, live=True)
    col.option_quotes.option = fake_tws.FakeOption
    control.submit(["AMZN"], options_for="2027-06-30")                       # past the fake chain's last expiry
    drain(col, clock)
    v = expected_move.view("AMZN", "2027-06-30")
    assert v["status"] == "error" and "no AMZN expiry on or after" in v["message"]


# ---------------------------------------------------------------- endpoints and page
@pytest.fixture
def client(cache):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_expected_move_endpoints(client, cache):
    assert client.get("/expected-move").status_code == 200
    r = client.get("/api/expected-move", params={"symbols": "amzn, lly;MA", "date": "2026-10-30"}).json()
    assert [it["symbol"] for it in r["items"]] == ["AMZN", "LLY", "MA"] and r["stale_seconds"] == expected_move.STALE_SECONDS
    assert all(it["status"] == "missing" for it in r["items"])
    assert client.post("/api/expected-move/request", json={"symbols": "AMZN LLY", "date": "2026-10-30"}).status_code == 200
    req = control.pending_requests()[-1]
    assert req["symbols"] == ["AMZN", "LLY"] and req["options_for"] == "2026-10-30"
    bad = [{"symbols": "AMZN", "date": "Oct 30"}, {"symbols": "not a symbol!", "date": "2026-10-30"},
           {"symbols": "ACME-DEMO", "date": "2026-10-30"}, {"symbols": " ".join(f"S{i}" for i in range(21)), "date": "2026-10-30"}]
    for b in bad:
        assert client.post("/api/expected-move/request", json=b).status_code == 400, b
    assert client.get("/api/expected-move", params={"symbols": "AMZN", "date": "2026-02-30"}).status_code == 400


def test_page_name_is_reserved():
    assert "expected-move" in dashboards.RESERVED
