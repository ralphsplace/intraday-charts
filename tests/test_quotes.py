"""Watch list rows (/api/quotes): last, change from the prior close, volume, high and low from cached 1-minute bars,
up to the Replay cursor; uncached symbols and market internals."""
import pytest
from fastapi.testclient import TestClient

import synthetic
from app import quotes, store

DAY = "2026-10-16"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    synthetic.generate(tmp_path)
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_rows_follow_the_cursor_and_the_prior_close(demo):
    full = quotes.row("QQQ-DEMO", DAY)
    early = quotes.row("QQQ-DEMO", DAY, cursor=600)                  # 10:00
    assert full["status"] == early["status"] == "ok"
    assert early["time"] == "09:59" and full["time"] > early["time"]
    df = store.read_day("QQQ-DEMO", DAY)
    assert full["last"] == pytest.approx(float(df["close"].iloc[-1]), abs=1e-4)
    assert full["change"] == pytest.approx(full["last"] - full["prev_close"], abs=1e-3)
    assert full["pct"] == pytest.approx(full["change"] / full["prev_close"] * 100, abs=1e-3)
    assert early["volume"] < full["volume"] and early["high"] <= full["high"] and early["low"] >= full["low"]
    assert quotes.row("QQQ-DEMO", DAY, cursor=200) == {"symbol": "QQQ-DEMO", "status": "none yet"}   # 03:20
    assert quotes.row("NVDA", DAY) == {"symbol": "NVDA", "status": "missing"}


def test_internals_have_no_percent_change_or_volume(demo, monkeypatch):
    monkeypatch.setattr(store, "read_day", lambda s, d: synthetic_internal())
    r = quotes.row("TICK-NYSE", DAY)
    assert r["status"] == "ok" and r["pct"] is None and r["volume"] is None


def synthetic_internal():
    import pandas as pd
    t = pd.date_range(f"{DAY} 09:30", periods=30, freq="1min", tz="America/New_York")
    return pd.DataFrame({"time": t, "open": 100.0, "high": 300.0, "low": -200.0, "close": 150.0, "volume": 0.0})


def test_quotes_endpoint(demo):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))
    r = c.get("/api/quotes", params={"symbols": "qqq-demo, SPY-DEMO;NVDA", "day": DAY, "cursor": 600}).json()
    assert [(i["symbol"], i["status"]) for i in r["items"]] == [("QQQ-DEMO", "ok"), ("SPY-DEMO", "ok"), ("NVDA", "missing")]
    assert c.get("/api/quotes", params={"symbols": "not one!", "day": DAY}).status_code == 400
    assert c.get("/api/quotes", params={"symbols": "QQQ", "day": "16 Oct"}).status_code == 400
    assert c.get("/api/quotes", params={"symbols": " ".join(f"S{i}" for i in range(101)), "day": DAY}).status_code == 400
