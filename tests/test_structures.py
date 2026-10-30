"""The option-chain page: Black-Scholes and implied volatility, evaluating structures (payoffs, breakevens, best and
worst, chance of profit, grid, loss-limit prices), templates on the fake TWS's invented chain, the chain view, the
collector's chain requests, and the endpoints."""
import math

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fake_tws
import synthetic
from app import control, dashboards, option_chain, saved, store
from app import structures as st
from test_collector import Clock, drain, make

ET = "America/New_York"
NOW = pd.Timestamp("2026-10-28 10:00", tz=ET)          # a Wednesday


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def leg(qty, strike, right, price, expiry="20261030", iv=0.3):
    return {"qty": qty, "expiry": expiry, "strike": strike, "right": right, "price": price, "iv": iv}


# ---------------------------------------------------------------- pricing
def test_black_scholes_parity_greeks_and_implied_vol():
    s, k, t, iv = 100.0, 105.0, 30 / 365, 0.25
    c, p = st.bs_price(s, k, t, iv, "C"), st.bs_price(s, k, t, iv, "P")
    assert c - p == pytest.approx(s - k * math.exp(-st.RATE * t), abs=1e-9)                 # put-call parity
    h = 0.01
    g = st.bs_greeks(s, k, t, iv, "C")
    assert g["delta"] == pytest.approx((st.bs_price(s + h, k, t, iv, "C") - st.bs_price(s - h, k, t, iv, "C")) / (2 * h), abs=1e-4)
    assert g["vega"] == pytest.approx((st.bs_price(s, k, t, iv + 0.01, "C") - c), rel=0.02)    # per IV point
    assert g["theta"] == pytest.approx(st.bs_price(s, k, t - 1 / 365, iv, "C") - c, rel=0.05)  # per day
    assert st.implied_vol(c, s, k, t, "C") == pytest.approx(iv, abs=1e-6)
    assert st.implied_vol(0.01, s, 80, t, "C") is None                                       # below intrinsic
    assert st.bs_price(s, k, 0, iv, "P") == 5 and st.bs_greeks(s, k, 0, iv, "P")["delta"] == -1


def test_evaluation_times():
    legs = [leg(1, 100, "C", 1)]
    assert [t["id"] for t in st.eval_times(legs, NOW)] == ["now", "close", "front_noon", "front_close"]
    fri = pd.Timestamp("2026-10-30 13:00", tz=ET)                                           # the expiry day itself
    assert [t["id"] for t in st.eval_times(legs, fri)] == ["now", "front_close"]


# ---------------------------------------------------------------- evaluating
def test_long_call_payoff():
    r = st.evaluate([leg(1, 100, "C", 2.0)], 100.0, NOW, "front_close", sigma=0.3)
    assert r["kind"] == "debit" and r["cost"] == 200
    assert r["breakevens"] == [pytest.approx(102.0, abs=0.05)]                               # strike + premium
    assert r["max_profit"]["unlimited"] and not r["max_loss"]["unlimited"]
    assert r["max_loss"]["value"] == pytest.approx(-200)
    assert 0 < r["chance"] < 50
    assert len(r["graph"]["prices"]) == st.POINTS == len(r["graph"]["at"]) == len(r["graph"]["now"])
    g = r["grid"]
    assert len(g["prices"]) == 11 and g["prices"][5] == 100.0 and len(g["values"][0]) == len(g["times"]) == 4
    assert g["values"][5][-1] == pytest.approx(-200)                                         # at the money at expiry


def test_iron_condor_best_worst_and_loss_limit():
    legs = [leg(-1, 105, "C", 1.5), leg(1, 110, "C", 0.5), leg(-1, 95, "P", 1.5), leg(1, 90, "P", 0.5)]
    r = st.evaluate(legs, 100.0, NOW, "front_close", sigma=0.3, stop=-200)
    assert r["kind"] == "credit" and r["cost"] == -200
    assert r["max_profit"]["value"] == pytest.approx(200) and r["max_loss"]["value"] == pytest.approx(-300)
    assert r["breakevens"] == [pytest.approx(93, abs=0.05), pytest.approx(107, abs=0.05)]
    assert r["stop"]["below"] == pytest.approx(91, abs=0.02) and r["stop"]["above"] == pytest.approx(109, abs=0.02)
    assert not r["max_loss"]["unlimited"] and not r["max_profit"]["unlimited"]
    assert r["greeks"]["theta"] > 0 and r["greeks"]["vega"] < 0                              # short premium


def test_wish_list_payoff():
    """Puts +1 x -3 x 1 (110 / 100 / 90, a 0.20 credit): the credit above 110, a butterfly's peak at 100, and below
    90 like owning 100 shares from 100 (worst as the stock goes to 0)."""
    legs = [leg(1, 110, "P", 5.0), leg(-3, 100, "P", 2.0), leg(1, 90, "P", 0.8)]
    r = st.evaluate(legs, 105.0, NOW, "front_close", sigma=0.3)
    assert r["kind"] == "credit" and r["cost"] == pytest.approx(-20)
    assert r["breakevens"] == [pytest.approx(94.9, abs=0.05)]                     # 2S - 189.8 = 0; none above
    assert r["max_profit"]["value"] == pytest.approx(1020, abs=1) and r["max_profit"]["price"] == pytest.approx(100, abs=0.6)
    assert r["max_loss"]["value"] == pytest.approx(-9980, abs=5) and not r["max_loss"]["unlimited"]
    at = dict(zip(r["graph"]["prices"], r["graph"]["at"], strict=True))
    assert at[max(at)] == pytest.approx(20, abs=0.5)                              # above 110: the credit


def test_iv_change_moves_a_calendar():
    legs = [leg(-1, 100, "C", 1.2), leg(1, 100, "C", 3.0, expiry="20261106", iv=0.3)]
    base = st.evaluate(legs, 100.0, NOW, "front_close", sigma=0.3)["max_profit"]["value"]
    lower = st.evaluate(legs, 100.0, NOW, "front_close", iv_shift=-0.05, sigma=0.3)["max_profit"]["value"]
    assert lower < base                                                                    # the long leg loses vega


# ---------------------------------------------------------------- the chain (fake TWS)
@pytest.fixture
def chain(cache):
    synthetic.generate_chain(cache, "ACME-DEMO")
    return option_chain.read("ACME-DEMO")


def test_chain_view(chain):
    v = option_chain.view("ACME-DEMO")
    assert v["status"] == "ok" and v["synthetic"] and v["expiry"] == "20261030" and v["next_weekly"] == "20261106"
    assert len(v["rows"]) == 19 and len(v["strip"]) == option_chain.STRIP
    assert [s["full"] for s in v["strip"]].count(True) == 2
    assert all(s["move"] for s in v["strip"])                                               # every strip expiry has its EM
    row = min(v["rows"], key=lambda r: abs(r["strike"] - v["price"]))
    assert 0.4 < row["C"]["delta"] < 0.6 and -0.6 < row["P"]["delta"] < -0.4 and row["C"]["iv"] > 0
    assert option_chain.view("ACME-DEMO", "20261106")["expiry"] == "20261106"
    assert option_chain.view("ACME-DEMO", "20261102")["expiry"] == "20261030"              # not quoted in full: the first


def test_strike_profile(chain):
    v = option_chain.view("ACME-DEMO")
    prof = v["profile"]
    assert v["oi_day"] == "2026-10-28" and prof["missing"] == 0 and len(prof["strikes"]) == 19
    row = next(r for r in v["rows"] if r["strike"] == 53.0)
    x = next(p for p in prof["strikes"] if p["strike"] == 53.0)
    price = v["price"]
    assert x["call_oi"] == fake_tws.fake_open_interest("ACME-DEMO", 53.0, "C")
    assert x["call"] == pytest.approx(row["C"]["gamma"] * x["call_oi"] * 100 * price ** 2 * 0.01, rel=1e-6)   # $ per 1% move
    assert x["put"] < 0 < x["call"]                                               # puts plotted below zero
    assert prof["net"] == pytest.approx(sum(p["call"] + p["put"] for p in prof["strikes"]), abs=0.05)
    assert prof["call_wall"] == max(prof["strikes"], key=lambda p: p["call"])["strike"]
    assert option_chain.gamma_exposure(None, 100, 50) is None


def test_open_interest_is_fetched_once_a_day(cache):
    clock = Clock("2026-10-28 10:00")
    ib, col = make(cache, clock, live=True)
    col.option_quotes.option = fake_tws.FakeOption
    ask = lambda: control.submit(["AMZN"], chain={"expiries": ["20261030"], "window": 5})   # noqa: E731
    ask(); drain(col, clock)
    subs = [r for r in ib.requests if r[1] == "mktdata" and r[2] == "101"]
    assert len(subs) == 22 and not ib.tickers                                    # 11 strikes x C/P, all cancelled
    assert option_chain.view("AMZN")["profile"]["missing"] == 0
    ask(); drain(col, clock)                                                     # again the same day: reused
    assert len([r for r in ib.requests if r[1] == "mktdata" and r[2] == "101"]) == 22
    assert option_chain.view("AMZN")["profile"]["missing"] == 0
    clock.t = pd.Timestamp("2026-10-29 10:00", tz=ET)                            # the next day: fetched again
    ask(); drain(col, clock)
    assert len([r for r in ib.requests if r[1] == "mktdata" and r[2] == "101"]) == 44


def test_double_diagonal_template_follows_the_rule(chain):
    from app import expected_move as em
    legs = st.template("double_diagonal", chain, "20261030", "20261106")
    price, move = chain["price"], em.straddle_at(chain, "20261030", chain["price"])["value"]
    short_c, short_p, long_c, long_p = legs
    assert (short_c["qty"], short_c["right"], short_p["qty"], short_p["right"]) == (-1, "C", -1, "P")
    assert short_c["strike"] == em.nearest([k for k in em.listed_side(chain, "20261030", "C") if k >= price], price + move)
    assert long_c["expiry"] == "20261106" and long_c["strike"] == short_c["strike"] - 1         # one strike closer ($1 apart)
    assert long_p["strike"] == short_p["strike"] + 1
    r = option_chain.evaluate("ACME-DEMO", legs, "front_close", 0.0, None)
    assert r["status"] == "ok" and r["kind"] == "debit" and len(r["legs"]) == 4


def test_wish_list_template(chain):
    from app import expected_move as em
    legs = st.template("wish_list", chain, "20261030", None)
    assert [(x["qty"], x["right"]) for x in legs] == [(1, "P"), (-3, "P"), (1, "P")]
    up, body, low = (x["strike"] for x in legs)
    price, move = chain["price"], em.straddle_at(chain, "20261030", chain["price"])["value"]
    assert body == em.nearest([k for k in em.listed_side(chain, "20261030", "P") if k <= price], price - move)
    assert up - body == body - low == st.WING                                     # $1 strikes, 2 out
    r = option_chain.evaluate("ACME-DEMO", legs, "front_close", 0.0, None)
    assert r["status"] == "ok" and len(r["breakevens"]) >= 1


def test_other_templates(chain):
    ic = st.template("iron_condor", chain, "20261030", None)
    assert ic[1]["strike"] - ic[0]["strike"] == st.WING and ic[2]["strike"] - ic[3]["strike"] == st.WING
    fly = st.template("butterfly", chain, "20261030", None)
    assert [x["qty"] for x in fly] == [1, -2, 1] and fly[1]["strike"] - fly[0]["strike"] == fly[2]["strike"] - fly[1]["strike"]
    cal = st.template("calendar", chain, "20261030", "20261106")
    assert cal[0]["strike"] == cal[1]["strike"] and cal[1]["expiry"] == "20261106"
    for name in st.TEMPLATES:
        if name != "custom":
            assert st.template(name, chain, "20261030", "20261106"), name
    with pytest.raises(ValueError, match="later expiry"):
        st.template("calendar", chain, "20261030", None)


def test_evaluate_says_which_expiries_are_missing(chain):
    far = {"qty": 1, "expiry": "20261102", "strike": 60.0, "right": "C"}          # Nov 2: only its at-the-money strikes
    r = option_chain.evaluate("ACME-DEMO", [far], "front_close", 0, None)
    assert r == {"status": "missing", "missing": ["20261102"]}
    assert option_chain.evaluate("ACME-DEMO", [{**far, "strike": 53.0}], "front_close", 0, None)["status"] == "ok"


# ---------------------------------------------------------------- collector
def test_collector_fetches_a_chain_on_request(cache):
    clock = Clock("2026-10-28 10:00")
    ib, col = make(cache, clock, live=True)
    col.option_quotes.option = fake_tws.FakeOption
    control.submit(["AMZN"], chain={"expiries": ["20261030", "20261106"], "window": 15})
    drain(col, clock)
    c = option_chain.read("AMZN")
    assert c["wanted"] == ["20261030", "20261106"] and c["window"] == 15
    assert len(c["expiries"]["20261030"]["quotes"]) == 31                                     # 15 either side
    tickers = [r for r in ib.requests if r[0] == "qualify"]
    assert len(tickers) > 2                                                                  # snapshots asked in batches
    assert store.list_days("AMZN") == []


def test_collector_caches_a_chain_failure(cache):
    clock = Clock("2026-10-28 10:00")
    ib, col = make(cache, clock, live=True)
    col.option_quotes.option = fake_tws.FakeOption
    real = ib.qualifyContracts
    ib.qualifyContracts = lambda *c: [x for x in real(*c) if not isinstance(x, fake_tws.FakeOption)]   # no options
    control.submit(["AMZN"], chain={"expiries": [], "window": 9})
    drain(col, clock)
    v = option_chain.view("AMZN")
    assert v["status"] == "error" and "no quotes" in v["message"]


# ---------------------------------------------------------------- endpoints
@pytest.fixture
def client(cache):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_option_endpoints(client, cache):
    assert client.get("/options").status_code == 200
    assert client.get("/api/options/chain", params={"symbol": "QQQ"}).json()["status"] == "missing"
    assert client.post("/api/options/template", json={"symbol": "QQQ", "template": "straddle", "front": "20261030"}).status_code == 409
    r = client.post("/api/options/request", json={"symbol": "qqq", "expiries": ["20261030"], "window": 9})
    assert r.status_code == 200 and control.pending_requests()[-1]["chain"] == {"expiries": ["20261030"], "window": 9}
    bad = [{"symbol": "QQQ", "expiries": ["2026-10-30"]}, {"symbol": "QQQ", "window": 7}, {"symbol": "ACME-DEMO"},
           {"symbol": "QQQ", "expiries": ["20261030"] * 5}, {"symbol": "not one!"}]
    for b in bad:
        assert client.post("/api/options/request", json=b).status_code in (400, 422), b
    synthetic.generate_chain(cache, "ACME-DEMO")
    ok = client.post("/api/options/template", json={"symbol": "ACME-DEMO", "template": "double_diagonal",
                                                    "front": "20261030", "back": "20261106"})
    legs = ok.json()["legs"]
    assert len(legs) == 4
    r = client.post("/api/options/evaluate", json={"symbol": "ACME-DEMO", "legs": legs, "at": "front_noon", "iv_shift": -0.02,
                                                  "stop": -100}).json()
    assert r["status"] == "ok" and r["at"] == "front_noon" and r["iv_shift"] == -0.02 and "stop" in r
    for b in [{"legs": []}, {"legs": [{**legs[0], "right": "X"}]}, {"legs": [{**legs[0], "qty": 99}]},
              {"legs": legs, "stop": 50}, {"legs": [{**legs[0], "expiry": "20261399"}]}]:
        assert client.post("/api/options/evaluate", json={"symbol": "ACME-DEMO", **b}).status_code in (400, 422), b


def test_names_and_saved_kind():
    assert "options" in dashboards.RESERVED and "structures" in saved.KINDS
