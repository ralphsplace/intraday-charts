"""The watch list's Holdings list: the collector's read-only positions reader (against the stand-in for TWS),
holdings summed over accounts, market value and P/L at the price on screen, the endpoint, and the switch."""
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import positions as reader
import synthetic
from app import envcheck, positions, quotes, store
from test_collector import Clock, drain, make

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    synthetic.generate(tmp_path)
    for demo, real in (("QQQ-DEMO", "QQQ"), ("SPY-DEMO", "SPY")):      # positions are in real symbols
        shutil.copytree(tmp_path / "bars" / demo, tmp_path / "bars" / real)
    return tmp_path


def pos(account, symbol, qty, avg, sec="STK"):
    return NS(account=account, contract=NS(symbol=symbol, secType=sec, currency="USD"), position=qty, avgCost=avg)


HELD = [pos("U1234567", "QQQ", 100, 600.0), pos("U7654321", "QQQ", 50, 630.0),
        pos("U1234567", "SPY", -20, 650.0), pos("U1234567", "QQQ", 3, 105.5, sec="OPT"),
        pos("U1234567", "BRK B", 10, 400.0), pos("U1234567", "AAPL", 0, 0.0)]


def test_holdings_are_summed_over_accounts_and_others_counted():
    data = reader.read_positions(NS(reqPositions=lambda: HELD))
    assert data["accounts"] == ["…4567", "…4321"]
    assert all("U1234567" not in json.dumps(p) and "U7654321" not in json.dumps(p) for p in data["positions"])
    held, others = positions.holdings(data)
    assert set(held) == {"QQQ", "SPY"} and others == 2          # the option, and BRK B (not a chart symbol)
    assert held["QQQ"]["qty"] == 150 and held["QQQ"]["avg_cost"] == pytest.approx(610.0)
    assert held["QQQ"]["accounts"] == ["…4567", "…4321"]


def test_rows_value_each_holding_at_the_price_on_screen(cache, monkeypatch):
    monkeypatch.setenv("HOLDINGS", "on")
    positions.write(reader.read_positions(NS(reqPositions=lambda: HELD)))
    day = store.list_days("QQQ")[-1]
    v = positions.view(day)
    assert v["status"] == "ok" and [r["symbol"] for r in v["rows"]] == ["QQQ", "SPY"]     # biggest first
    q = quotes.row("QQQ", day)
    r = v["rows"][0]
    assert r["market_value"] == pytest.approx(150 * q["last"], abs=0.01)
    assert r["unrealized"] == pytest.approx(150 * q["last"] - 150 * 610.0, abs=0.01)
    assert r["unrealized_pct"] == pytest.approx(r["unrealized"] / (150 * 610.0) * 100, abs=0.01)
    assert r["day_pnl"] == pytest.approx(150 * q["change"], abs=0.01)
    s = v["rows"][1]
    assert s["qty"] == -20 and s["market_value"] < 0                              # a short: negative value
    assert v["totals"]["market_value"] == pytest.approx(r["market_value"] + s["market_value"], abs=0.02)
    assert v["others"] == 2 and v["accounts"] == ["…4567", "…4321"]
    early = positions.view(day, cursor=10 * 60)                                  # Replay: the price at 10:00
    assert early["rows"][0]["last"] == quotes.row("QQQ", day, 10 * 60)["last"]


def test_off_missing_and_errors(cache, monkeypatch):
    monkeypatch.delenv("HOLDINGS", raising=False)
    assert positions.view("2026-10-16")["status"] == "off"
    monkeypatch.setenv("HOLDINGS", "on")
    assert positions.view("2026-10-16")["status"] == "missing"
    positions.write({"error": "TWS: no permission", "fetched": 1.0})
    v = positions.view("2026-10-16")
    assert v["status"] == "error" and "no permission" in v["message"]


def test_the_collector_reads_positions_only_when_turned_on(cache, monkeypatch):
    clock = Clock("2026-10-20 10:00")
    monkeypatch.delenv("HOLDINGS", raising=False)
    ib, col = make(cache, clock, live=True)
    ib.positions = HELD
    drain(col, clock)
    assert col.positions is None and getattr(ib, "position_reads", 0) == 0 and positions.read() is None
    monkeypatch.setenv("HOLDINGS", "on")
    ib, col = make(cache, clock, live=True)
    ib.positions = HELD
    col.step()
    assert ib.position_reads == 1 and len(positions.read()["positions"]) == 6
    col.step()                                                                   # once a minute, not every pass
    assert ib.position_reads == 1
    clock.advance(reader.EVERY + 1)
    col.step()
    assert ib.position_reads == 2
    ib2, col2 = make(cache, clock, live=False)                                  # a one-off backfill never reads them
    assert col2.positions is None


def test_a_failed_read_is_written_for_the_page(cache, monkeypatch):
    def boom():
        raise RuntimeError("not allowed")
    reader.PositionsReader(NS(reqPositions=boom)).sync()
    assert "not allowed" in positions.read()["error"]


def test_positions_are_read_in_one_place_only():
    """reqPositions appears only in the positions reader; nothing reads orders, executions or account values."""
    found = []
    for path in [*ROOT.glob("app/*.py"), *ROOT.glob("tools/*.py")]:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\.(reqPositions|reqExecutions|reqOpenOrders|reqAllOpenOrders|reqCompletedOrders|reqAccountUpdates"
                         r"|reqAccountSummary|reqPnL)\b", line):
                found.append(f"{path.relative_to(ROOT)}:{i}")
    assert [f.split(":")[0] for f in found] == ["tools/positions.py"]


@pytest.fixture
def client(cache, monkeypatch):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_positions_endpoint(client, cache, monkeypatch):
    day = store.list_days("QQQ")[-1]
    monkeypatch.delenv("HOLDINGS", raising=False)
    assert client.get("/api/positions", params={"day": day}).json()["status"] == "off"
    monkeypatch.setenv("HOLDINGS", "on")
    positions.write(reader.read_positions(NS(reqPositions=lambda: HELD)))
    v = client.get("/api/positions", params={"day": day}).json()
    assert v["status"] == "ok" and v["day"] == day and len(v["rows"]) == 2
    assert client.get("/api/positions", params={"day": "x"}).status_code == 400


def test_the_environment_check_says_whether_positions_are_read(monkeypatch):
    monkeypatch.delenv("HOLDINGS", raising=False)
    ro = next(c for c in envcheck.run() if c["name"] == "Read-only trading data")
    assert "never read" in ro["detail"]
    monkeypatch.setenv("HOLDINGS", "on")
    ro = next(c for c in envcheck.run() if c["name"] == "Read-only trading data")
    assert "reads the account's positions" in ro["detail"] and ro["status"] == "ok"
