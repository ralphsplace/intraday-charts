"""Orders to the IBKR paper account (#84): app/live_orders.py (checks, requests, status), tools/trader.py (the only
code that places orders) on a fake paper TWS, the /api/live endpoints, and the environment check. Orders go only
with LIVE_ORDERS=paper, only while TWS reports a paper account (DU...), checked before every order."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

import fake_tws
import trader
from app import envcheck, live_orders, store

ROOT = envcheck.ROOT


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setenv("LIVE_ORDERS", "paper")
    monkeypatch.delenv("LIVE_MAX_SHARES", raising=False)
    monkeypatch.delenv("TRADE_ACCOUNT", raising=False)
    return tmp_path


def make(accounts=("DU1234567",)):
    ib = fake_tws.FakeTradingIB(accounts)
    t = [0.0]
    tr = trader.Trader(lambda: ib, clock=lambda: t[0], host="localhost", port=7497)
    return ib, tr


def send(tr, **action):
    req = live_orders.submit(live_orders.check(action))
    tr.step()
    return live_orders.result(req["id"])


BUY = {"side": "buy", "qty": 10, "type": "market"}


# ---------------------------------------------------------------- checking what the panel sends
def test_actions_are_checked(cache, monkeypatch):
    ok = live_orders.check({"action": "order", "symbol": "qqq", "order": BUY})
    assert ok == {"action": "order", "symbol": "QQQ", "order": BUY}
    bad = [{"action": "teleport", "symbol": "QQQ"}, {"action": "order", "symbol": "QQQ-DEMO", "order": BUY},
           {"action": "order", "symbol": "TICK-NYSE", "order": BUY}, {"action": "order", "symbol": "QQQ", "order": {**BUY, "qty": 0}},
           {"action": "order", "symbol": "QQQ", "order": {**BUY, "qty": 1001}}, {"action": "order", "symbol": "QQQ", "order": {**BUY, "type": "limit"}},
           {"action": "order", "symbol": "QQQ", "order": {**BUY, "side": "short"}}, {"action": "cancel", "symbol": "QQQ"},
           {"action": "bracket", "symbol": "QQQ", "order": BUY, "stop": {"price": 1}}]
    for b in bad:
        with pytest.raises(ValueError):
            live_orders.check(b)
    monkeypatch.setenv("LIVE_MAX_SHARES", "5000")
    assert live_orders.check({"action": "order", "symbol": "QQQ", "order": {**BUY, "qty": 5000}})["order"]["qty"] == 5000
    br = live_orders.check({"action": "bracket", "symbol": "QQQ", "order": BUY, "stop": {"trail": {"amount": 0.8}}, "target": {"price": 512.345}})
    assert br["stop"] == {"trail": {"amount": 0.8}} and br["target"] == {"price": 512.35}


def test_an_atr_trailing_distance_is_worked_out_from_todays_bars(demo):
    day = store.list_days("QQQ-DEMO")[3]
    a = live_orders.resolve_atr({"action": "order", "symbol": "QQQ-DEMO", "order": {**BUY, "type": "trail", "trail": {"atr": 2, "length": 14, "tf": 3}}},
                                day, 11 * 60)
    assert 0 < a["order"]["trail"]["amount"] < 10 and "atr" not in a["order"]["trail"]


# ---------------------------------------------------------------- the trader
def test_orders_go_to_the_paper_account(cache):
    ib, tr = make()
    r = send(tr, action="order", symbol="QQQ", order=BUY)
    assert r["ok"] and "BUY 10 QQQ market sent" in r["message"]
    c, o = ib.placed[-1]
    assert (c.symbol, o.action, o.totalQuantity, o.orderType, o.account, o.tif) == ("QQQ", "BUY", 10, "MKT", "DU1234567", "DAY")
    send(tr, action="order", symbol="QQQ", order={"side": "sell", "qty": 5, "type": "limit", "price": 510.25})
    send(tr, action="order", symbol="QQQ", order={"side": "sell", "qty": 5, "type": "stop", "price": 499})
    send(tr, action="order", symbol="QQQ", order={"side": "sell", "qty": 5, "type": "trail", "trail": {"amount": 0.75}})
    assert [(o.orderType, o.lmtPrice if o.orderType == "LMT" else o.auxPrice) for _, o in ib.placed[1:]] == \
        [("LMT", 510.25), ("STP", 499), ("TRAIL", 0.75)]
    s = live_orders.read_status()
    assert s["connected"] and s["paper"] and s["account"] == "DU…4567" and len(s["orders"]) == 4 and not s["refused"]


def test_a_bracket_is_an_entry_with_a_stop_and_target_sent_together(cache):
    ib, tr = make()
    r = send(tr, action="bracket", symbol="QQQ", order={**BUY, "type": "limit", "price": 500},
             stop={"price": 498}, target={"price": 504})
    assert r["ok"]
    (_, entry), (_, target), (_, stop) = ib.placed
    assert (entry.orderType, entry.transmit) == ("LMT", False)
    assert (target.action, target.orderType, target.lmtPrice, target.parentId, target.transmit) == ("SELL", "LMT", 504, entry.orderId, False)
    assert (stop.action, stop.orderType, stop.auxPrice, stop.parentId, stop.transmit) == ("SELL", "STP", 498, entry.orderId, True)
    send(tr, action="bracket", symbol="QQQ", order={"side": "sell", "qty": 3, "type": "market"},
         stop={"trail": {"amount": 1.2}}, target={"price": 490})
    assert ib.placed[-1][1].orderType == "TRAIL" and ib.placed[-1][1].action == "BUY" and ib.placed[-1][1].auxPrice == 1.2


def test_cancel_and_flatten(cache):
    ib, tr = make()
    send(tr, action="order", symbol="QQQ", order=BUY)
    ib.fill(ib.placed[-1][1].orderId, 500.0)
    send(tr, action="order", symbol="QQQ", order={"side": "sell", "qty": 10, "type": "limit", "price": 505})
    send(tr, action="order", symbol="SPY", order={"side": "buy", "qty": 1, "type": "limit", "price": 400})
    limit = ib.placed[-2][1].orderId
    assert send(tr, action="cancel", symbol="QQQ", order_id=limit)["ok"] and ib.cancelled == [limit]
    assert not send(tr, action="cancel", symbol="QQQ", order_id=99999)["ok"]
    send(tr, action="order", symbol="QQQ", order={"side": "sell", "qty": 10, "type": "stop", "price": 495})
    r = send(tr, action="flatten", symbol="QQQ")
    assert r["ok"] and "1 order(s) cancelled, 10 shares closed at market" in r["message"]
    assert (ib.placed[-1][1].action, ib.placed[-1][1].orderType, ib.placed[-1][1].totalQuantity) == ("SELL", "MKT", 10)
    assert [t.contract.symbol for t in ib.openTrades()] == ["SPY", "QQQ"]          # SPY's order untouched; the close working
    s = live_orders.read_status()
    assert s["positions"] == [{"symbol": "QQQ", "qty": 10.0, "avg": 500.0}] and s["fills"][0]["side"] == "buy"
    v = live_orders.view("QQQ")
    assert v["position"]["qty"] == 10 and [o["type"] for o in v["orders"]] == ["market"] and len(v["fills"]) == 1


def test_a_live_account_gets_no_orders(cache):
    ib, tr = make(accounts=("U7654321",))
    r = send(tr, action="order", symbol="QQQ", order=BUY)
    assert not r["ok"] and "live account (U7…4321)" in r["message"] and ib.placed == []
    s = live_orders.read_status()
    assert not s["paper"] and s["refused"] and "live account" in live_orders.why_not()
    assert envcheck.orders_check()["status"] == "warn"


def test_every_order_checks_the_account_again(cache):
    ib, tr = make()
    assert send(tr, action="order", symbol="QQQ", order=BUY)["ok"]
    ib.accounts = ["DU1234567", "U7654321"]                          # TWS now also reports a live account
    assert not send(tr, action="order", symbol="QQQ", order=BUY)["ok"] and len(ib.placed) == 1
    ib.accounts = ["DU1234567"]
    assert send(tr, action="order", symbol="QQQ", order=BUY)["ok"]


def test_no_paper_tws_no_orders(cache):
    def refuse():
        raise ConnectionRefusedError("refused")
    tr = trader.Trader(refuse, clock=lambda: 0.0, host="localhost", port=7497)
    req = live_orders.submit(live_orders.check({"action": "order", "symbol": "QQQ", "order": BUY}))
    tr.step()
    r = live_orders.result(req["id"])
    assert not r["ok"] and "Can't reach the paper TWS at localhost:7497" in r["message"]
    assert not live_orders.read_status()["connected"]


def test_an_unknown_symbol_is_refused(cache):
    ib, tr = make()
    assert not send(tr, action="order", symbol="ZZZQ", order=BUY)["ok"] and ib.placed == []


# ---------------------------------------------------------------- the endpoints
def client():
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_endpoints(cache, monkeypatch):
    c = client()
    monkeypatch.delenv("LIVE_ORDERS")
    v = c.get("/api/live", params={"symbol": "QQQ"}).json()
    assert not v["on"] and not v["ready"] and "LIVE_ORDERS=paper" in v["why_not"]
    r = c.post("/api/live/orders", json={"action": "order", "symbol": "QQQ", "order": BUY})
    assert r.status_code == 403 and "Orders are off" in r.json()["detail"]
    monkeypatch.setenv("LIVE_ORDERS", "paper")
    r = c.post("/api/live/orders", json={"action": "order", "symbol": "QQQ", "order": BUY})
    assert r.status_code == 403 and "trader isn't running" in r.json()["detail"]
    # a trader stepping, as the collector does
    ib, tr = make()
    tr.step()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            tr.step()
            time.sleep(0.02)
    threading.Thread(target=loop, daemon=True).start()
    try:
        r = c.post("/api/live/orders", json={"action": "order", "symbol": "qqq", "order": BUY}).json()
        assert r["ok"] and r["view"]["symbol"] == "QQQ" and len(ib.placed) == 1
        r = c.post("/api/live/orders", json={"action": "order", "symbol": "QQQ", "order": {**BUY, "qty": 10**6}})
        assert r.status_code == 400 and "LIVE_MAX_SHARES" in r.json()["detail"]
        r = c.post("/api/live/orders", json={"action": "cancel", "symbol": "QQQ", "order_id": 4242})
        assert r.status_code == 409 and "No working order" in r.json()["detail"]
        v = c.get("/api/live", params={"symbol": "QQQ"}).json()
        assert v["ready"] and v["account"] == "DU…4567" and v["orders"][0]["qty"] == 10
    finally:
        stop.set()


# ---------------------------------------------------------------- the environment check
def test_only_the_trader_has_order_calls(cache, monkeypatch):
    assert envcheck.order_calls() == []
    assert "placeOrder" in (ROOT / "tools" / "trader.py").read_text()                 # it's there, and allowed
    planted = ROOT / "app" / "backtesting" / "_planted_for_test.py"
    try:
        planted.write_text("ib.placeOrder(contract, order)\n")
        assert envcheck.order_calls() == ["app/backtesting/_planted_for_test.py:1"]
        assert envcheck.orders_check()["status"] == "fail"
    finally:
        planted.unlink()
    monkeypatch.delenv("LIVE_ORDERS")
    assert "Orders are off" in envcheck.orders_check()["detail"]
    monkeypatch.setenv("LIVE_ORDERS", "paper")
    ok = envcheck.orders_check()
    assert ok["status"] == "ok" and "only while TWS reports a paper account" in ok["detail"]


def test_the_collector_runs_the_trader_only_when_orders_are_on(cache, monkeypatch):
    import fetch_ibkr
    from test_collector import Clock, make as make_collector
    ib, tr = make()
    monkeypatch.setattr(fetch_ibkr, "make_trader", lambda clock: tr)
    _, col = make_collector(cache, Clock(), live=True)
    assert col.trader is tr
    req = live_orders.submit(live_orders.check({"action": "order", "symbol": "QQQ", "order": BUY}))
    col.step()
    assert live_orders.result(req["id"])["ok"] and len(ib.placed) == 1
    monkeypatch.delenv("LIVE_ORDERS")
    assert make_collector(cache, Clock(), live=True)[1].trader is None
    monkeypatch.setenv("LIVE_ORDERS", "paper")
    assert make_collector(cache, Clock(), live=False)[1].trader is None          # one-off backfills never trade
