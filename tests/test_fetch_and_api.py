import sys
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import store

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import fetch_ibkr  # noqa: E402


class Bar:
    def __init__(self, date, px):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, px, px + 1, px - 1, px, 100


class FakeIB:
    """Stands in for ib_async.IB: returns two UTC bars per requested day."""
    def __init__(self):
        self.requests = []

    def reqHistoricalData(self, contract, endDateTime, **kw):
        self.requests.append(endDateTime)
        d = datetime.strptime(endDateTime[:8], "%Y%m%d")
        return [Bar(datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC), 100.0),   # 09:30 ET
                Bar(datetime(d.year, d.month, d.day, 13, 31, tzinfo=UTC), 101.0)]

    def sleep(self, secs):
        pass


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_bars_convert_from_utc_to_eastern():
    df = fetch_ibkr.bars_to_frame([Bar(datetime(2026, 10, 16, 13, 30, tzinfo=UTC), 1.0)])
    assert df["time"].iloc[0].strftime("%H:%M") == "09:30"
    assert str(df["time"].dt.tz) == "America/New_York"


def test_backfill_writes_and_skips_cached_days(cache):
    ib = FakeIB()
    days = ["2026-10-14", "2026-10-15"]
    assert fetch_ibkr.backfill(ib, object(), "QQQ", days) == 2
    assert store.list_days("QQQ") == days
    assert ib.requests[0] == "20261014 20:00:00 US/Eastern"
    assert fetch_ibkr.backfill(ib, object(), "QQQ", days) == 0     # already cached
    assert len(ib.requests) == 2
    df = store.read_day("QQQ", "2026-10-15")
    assert list(df["close"]) == [100.0, 101.0]


def test_trading_days_back_skips_weekends():
    days = fetch_ibkr.trading_days_back(3, pd.Timestamp("2026-10-19", tz="America/New_York"))  # a Monday
    assert days == ["2026-10-15", "2026-10-16", "2026-10-19"]


def test_api_serves_page_and_view(demo):
    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))   # a device on the home network
    assert c.get("/").status_code == 200
    assert c.get("/static/vendor/lightweight-charts.standalone.production.js").status_code == 200
    meta = c.get("/api/meta").json()
    assert any(s["symbol"] == "QQQ-DEMO" and s["demo"] for s in meta["symbols"])
    cat = c.get("/api/studies").json()
    assert {"vwap", "ema", "sma", "rsi", "macd", "prior_day", "sr_ladder", "session_levels", "vzo"} <= {s["type"] for s in cat["studies"]}
    assert cat["default_layout"] == []                                   # a new chart starts with no studies
    assert "presets" not in cat
    layout = [{"uid": str(i), "type": t, "params": {}} for i, t in enumerate(("prior_day", "sr_ladder", "session_levels", "events"))]
    r = c.post("/api/view", json={"symbol": "QQQ-DEMO", "day": "2026-10-16", "tf": 3, "cursor": 640, "studies": layout})
    assert r.status_code == 200
    v = r.json()
    assert v["cursor_label"] == "10:40" and v["future"]
    assert all(res["ok"] for res in v["studies"].values())
    assert any(res.get("verticals") for res in v["studies"].values())
    assert c.post("/api/view", json={"symbol": "QQQ-DEMO", "day": "2026-10-16", "tf": 2}).status_code == 400
    assert c.post("/api/view", json={"symbol": "QQQ-DEMO", "day": "2026-10-16", "days": 9}).status_code == 400
    import screenshot_layout     # the three charts in Ralph's screenshot, at every replay point that matters
    for cfg in screenshot_layout.configs():
        for cursor in (300, 575, 640, 900, None):
            r = c.post("/api/view", json={"symbol": cfg["symbol"] + "-DEMO", "day": "2026-10-16", "tf": cfg["tf"],
                                          "cursor": cursor, "studies": cfg["studies"]})
            assert r.status_code == 200, (cfg["symbol"], cfg["tf"], cursor)
            bad = {k: x.get("error") for k, x in r.json()["studies"].items() if not x["ok"]}
            assert not bad, (cfg["symbol"], cfg["tf"], cursor, bad)
    assert c.post("/api/view", json={"symbol": "NOPE", "day": "2026-10-16"}).status_code == 404


def test_daily_fetch_writes_daily_file(cache):
    class DailyIB(FakeIB):
        def reqHistoricalData(self, contract, endDateTime, **kw):
            from datetime import date
            return [Bar(date(2026, 10, 14), 100.0), Bar(date(2026, 10, 15), 101.0)]
    assert fetch_ibkr.fetch_daily(DailyIB(), object(), "QQQ", 2) == 2
    d = store.read_daily("QQQ")
    assert list(d["date"]) == ["2026-10-14", "2026-10-15"]


def test_live_mode_keeps_retrying_when_tws_is_down(cache, monkeypatch):
    calls = {"n": 0}

    def fake_session(args):
        calls["n"] += 1
        if calls["n"] < 3:
            raise fetch_ibkr.TWSUnavailable("connection refused")
        raise KeyboardInterrupt

    monkeypatch.setattr(fetch_ibkr, "run_session", fake_session)
    monkeypatch.setattr(fetch_ibkr.time, "sleep", lambda s: None)
    assert fetch_ibkr.main(["--live"]) == 0 and calls["n"] == 3
    calls["n"] = -10
    assert fetch_ibkr.main([]) == 2                         # without --live it reports and stops


def test_default_port_is_tws_live():
    assert fetch_ibkr.parse_args([]).port == 7496
