"""Replay practice (app/paper/practice.py): a session is its actions replayed over the day's bars, so it's exact at
any cursor, never fills on a bar already shown, and steps back cleanly."""
import pytest
from fastapi.testclient import TestClient

import synthetic
from app import store
from app.paper import accounts, practice

DAY = "2026-10-16"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("practice")
    synthetic.generate(d)
    return d


@pytest.fixture
def acct(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    import shutil
    shutil.rmtree(demo / "user", ignore_errors=True)
    name, _ = accounts.create("Practice", start_cash=100_000)
    return name


def bar_at(minute):
    return next(b for b in practice.bars("QQQ-DEMO", DAY) if b["minute"] == minute)


def test_a_market_order_fills_on_the_first_bar_not_yet_shown(acct):
    v = practice.view(acct, "QQQ-DEMO", DAY, 600)
    assert v["equity"]["position"] == 0 and v["equity"]["cash"] == 100_000
    practice.act(acct, "QQQ-DEMO", DAY, 600, {"kind": "order", "order": {"side": "buy", "qty": 10, "type": "market"}})
    v = practice.view(acct, "QQQ-DEMO", DAY, 601)
    assert [round(f["price"], 4) for f in v["fills"]] == [round(bar_at(600)["open"] + 0.01, 4)]
    assert v["new_fills"] and v["equity"]["position"] == 10


def test_nothing_fills_before_the_cursor_moves(acct):
    practice.view(acct, "QQQ-DEMO", DAY, 600)
    v = practice.act(acct, "QQQ-DEMO", DAY, 600, {"kind": "order", "order": {"side": "buy", "qty": 10, "type": "market"}})
    assert v["fills"] == [] and len(v["orders"]) == 1


def test_stepping_back_keeps_the_trades_until_they_are_removed(acct):
    practice.view(acct, "QQQ-DEMO", DAY, 600)
    practice.act(acct, "QQQ-DEMO", DAY, 600, {"kind": "order", "order": {"side": "buy", "qty": 10, "type": "market"}})
    practice.view(acct, "QQQ-DEMO", DAY, 650)
    v = practice.view(acct, "QQQ-DEMO", DAY, 590)                     # stepped back past the order
    assert v["later_actions"] == 1 and v["equity"]["position"] == 0
    with pytest.raises(Exception, match="ahead of the replay"):
        practice.act(acct, "QQQ-DEMO", DAY, 590, {"kind": "flatten"})
    v = practice.rewind(acct, "QQQ-DEMO", DAY, 590)
    assert v["later_actions"] == 0 and v["fills"] == []
    assert practice.view(acct, "QQQ-DEMO", DAY, 700)["fills"] == []   # gone for good


def test_a_bracket_and_the_session_end(acct):
    practice.view(acct, "QQQ-DEMO", DAY, 600)
    px = bar_at(599)["close"]
    practice.act(acct, "QQQ-DEMO", DAY, 600, {"kind": "bracket", "order": {"side": "buy", "qty": 100, "type": "market"},
                                               "stop": {"price": round(px - 50, 2)}, "target": {"price": round(px + 50, 2)}})
    v = practice.view(acct, "QQQ-DEMO", DAY, 16 * 60)
    assert v["closed"] and v["equity"]["position"] == 0 and v["orders"] == []
    assert [f["note"] for f in v["fills"]][-1] == "session end"
    assert accounts.all_accounts()[acct]["balance"] == pytest.approx(v["equity"]["cash"])


def test_an_order_at_a_study_level(acct):
    practice.view(acct, "QQQ-DEMO", DAY, 600)
    practice.act(acct, "QQQ-DEMO", DAY, 600, {"kind": "order", "order": {"side": "buy", "qty": 5, "type": "level",
                                               "level": {"spec": {"type": "vwap", "output": "vwap"}, "as": "limit"}}})
    v = practice.view(acct, "QQQ-DEMO", DAY, 960)
    for f in v["fills"][:1]:                                            # when it filled: at or below that bar's VWAP
        from app import study_values
        vw = study_values.value("QQQ-DEMO", DAY, {"type": "vwap", "output": "vwap"}, cursor=f["minute"])["value"]
        assert f["price"] <= vw + 1e-6


def test_refused_orders_say_why(acct):
    practice.view(acct, "QQQ-DEMO", DAY, 600)
    with pytest.raises(Exception, match="Not enough cash"):
        practice.act(acct, "QQQ-DEMO", DAY, 600, {"kind": "order", "order": {"side": "buy", "qty": 100_000, "type": "market"}})


def test_endpoints(acct, demo):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))
    where = {"account": acct, "symbol": "QQQ-DEMO", "day": DAY}
    assert c.post("/api/paper/practice", json={**where, "cursor": 600}).json()["demo"] is True
    r = c.post("/api/paper/practice/act", json={**where, "cursor": 600, "order": {"side": "buy", "qty": 1, "type": "market"}})
    assert r.status_code == 200 and len(r.json()["orders"]) == 1
    assert c.post("/api/paper/practice/act", json={**where, "cursor": 600, "order": {"side": "buy", "qty": 10**7, "type": "market"}}).status_code == 409
    assert c.post("/api/paper/practice/act", json={**where, "cursor": 600, "kind": "teleport"}).status_code == 400
    assert c.post("/api/paper/practice", json={**where, "account": "nope", "cursor": 600}).status_code == 404
    assert c.post("/api/paper/practice/rewind", json={**where, "cursor": 590}).json()["orders"] == []
