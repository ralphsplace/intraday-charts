"""Daily, weekly and monthly candles (app/periods.py, app/timeframes.py), and the collector keeping years of daily
prices for them. All prices here are invented."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import control, engine, periods, store, timeframes
from test_collector import Clock, drain, make

ET = "America/New_York"
DAY = "2026-10-16"                       # a Friday


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return tmp_path


def daily(dates, start=100.0):
    n = len(dates)
    return pd.DataFrame({"date": list(dates), "open": [start + i for i in range(n)], "high": [start + i + 2 for i in range(n)],
                         "low": [start + i - 2 for i in range(n)], "close": [start + i + 1 for i in range(n)],
                         "volume": [1000.0] * n})


def minutes(day, start_px=500.0):
    """09:30 to 15:59, one bar a minute, price rising a cent a minute."""
    t = pd.date_range(f"{day} 09:30", f"{day} 15:59", freq="1min", tz=ET)
    px = [start_px + 0.01 * i for i in range(len(t))]
    return pd.DataFrame({"time": t, "open": px, "high": [p + 0.05 for p in px], "low": [p - 0.05 for p in px],
                         "close": px, "volume": 10.0})


# ---------------------------------------------------------------- the list of durations
def test_timeframes():
    assert [t["label"] for t in timeframes.listing()["list"]] == ["1m", "3m", "5m", "15m", "1d", "1w", "1M"]
    assert [timeframes.parse(x) for x in (3, "3", "15", "1d", "1w", "1M", "2", "1D", "x", None, "3m")] == \
        [3, 3, 15, "1d", "1w", "1M", None, None, None, None, None]
    assert timeframes.is_period("1w") and not timeframes.is_period(5)


# ---------------------------------------------------------------- grouping
def test_weeks_start_monday_and_months_on_the_first():
    d = daily(["2026-09-28", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"]).assign(complete=True)
    w = periods.group(d, "1w")
    assert list(w["day"]) == ["2026-09-28", "2026-10-05"]
    assert w.iloc[0][["open", "high", "low", "close", "volume"]].tolist() == [100.0, 105.0, 98.0, 104.0, 4000.0]
    m = periods.group(d, "1M")
    assert list(m["day"]) == ["2026-09-28", "2026-10-01"] and m.iloc[1]["close"] == 105.0


def test_daily_view_with_today_from_minutes_up_to_the_cursor(cache):
    dates = pd.bdate_range(end="2026-10-15", periods=300).strftime("%Y-%m-%d")
    store.write_daily("ACME", daily(dates))
    store.write_day("ACME", DAY, minutes(DAY))
    v = periods.build_view("ACME", DAY, "1d", cursor=10 * 60 + 30)               # 10:30 in a replay
    last = v["bars"][-1]
    assert last["day"] == DAY and last["open"] == 500.0 and not last["complete"]
    assert last["close"] == pytest.approx(500.59) and last["high"] == pytest.approx(500.64)  # nothing after 10:30
    assert v["price"] == pytest.approx(500.59) and v["period"] and v["step"] == 86400
    full = periods.build_view("ACME", DAY, "1d")
    assert full["bars"][-1]["complete"] and full["bars"][-1]["close"] == pytest.approx(503.89)
    # 6 months shown by default; earlier candles only warm up indicators
    first = pd.Timestamp(full["bars"][0]["day"])
    assert pd.Timestamp(DAY) - pd.DateOffset(months=6) <= first < pd.Timestamp(DAY) - pd.DateOffset(months=6) + pd.Timedelta(days=5)
    assert (full["tf_label"], full["range_label"]) == ("1d", "6 months")
    assert len(periods.build_view("ACME", DAY, "1d", span=3)["bars"]) < len(full["bars"])
    pre = periods.build_view("ACME", DAY, "1d", cursor=9 * 60)                  # premarket: no candle yet today
    assert pre["bars"][-1]["day"] == "2026-10-15"


def test_weeks_and_months_still_forming_are_marked(cache):
    dates = pd.bdate_range(end="2026-10-15", periods=600).strftime("%Y-%m-%d")
    store.write_daily("ACME", daily(dates))
    store.write_day("ACME", DAY, minutes(DAY))
    w = periods.build_view("ACME", DAY, "1w")
    assert w["bars"][-1]["day"] == "2026-10-12" and not w["bars"][-1]["complete"] and w["bars"][-2]["complete"]
    assert w["bars"][-1]["close"] == pytest.approx(503.89)                    # this week so far ends with today
    m = periods.build_view("ACME", DAY, "1M", span=24)
    assert m["bars"][-1]["day"] == "2026-10-01" and not m["bars"][-1]["complete"]
    assert len(m["bars"]) in (24, 25)
    assert [pd.Timestamp(t, unit="s").strftime("%Y-%m-%d") for t in m["future"]] == ["2026-11-01", "2026-12-01", "2027-01-01"]


def test_studies_on_period_candles(cache):
    dates = pd.bdate_range(end=DAY, periods=400).strftime("%Y-%m-%d")
    store.write_daily("ACME", daily(dates))
    studies = [{"uid": t, "type": t, "params": {}} for t in
               ("ema", "sma", "rsi", "macd", "bollinger", "ma_cloud", "volume", "atr", "obv", "vwap", "session_levels",
                "volume_profile", "tick", "prior_day")]
    v = periods.build_view("ACME", DAY, "1d", studies=studies)
    r = v["studies"]
    assert all(x["ok"] for x in r.values()), {k: x.get("error") for k, x in r.items() if not x["ok"]}
    for t in ("ema", "sma", "rsi", "bollinger", "atr"):
        assert r[t]["lines"] and len(r[t]["lines"][0]["data"]) == len(v["bars"]), t     # warmed up: a value on every candle
    for t in ("vwap", "session_levels", "volume_profile", "tick", "prior_day"):
        assert r[t]["note"] == "intraday charts only (1m to 15m)" and not r[t].get("lines"), t
    assert r["volume"]["histograms"][0]["data"][0]["value"] == 1000.0


def test_symbols_without_daily_prices_use_their_cached_minutes(cache):
    for d in ("2026-10-14", "2026-10-15", DAY):
        store.write_day("TICK-NYSE", d, minutes(d, 0.0))
    v = periods.build_view("TICK-NYSE", DAY, "1d")
    assert [b["day"] for b in v["bars"]] == ["2026-10-14", "2026-10-15", DAY]
    with pytest.raises(ValueError, match="No cached bars"):
        periods.build_view("NOPE", DAY, "1d")


def test_minus_vix_daily_is_vix_upside_down(cache):
    store.write_daily("VIX", daily(pd.bdate_range(end=DAY, periods=30).strftime("%Y-%m-%d"), 15.0))
    v = periods.build_view("-VIX", DAY, "1d")
    assert all(b["close"] < 0 and b["high"] >= b["low"] for b in v["bars"])


def test_view_endpoint(cache):
    from app.server import app
    store.write_daily("ACME", daily(pd.bdate_range(end=DAY, periods=200).strftime("%Y-%m-%d")))
    c = TestClient(app, client=("192.168.1.20", 50000))
    ok = c.post("/api/view", json={"symbol": "ACME", "day": DAY, "tf": "1w", "span": 12})
    assert ok.status_code == 200 and ok.json()["range_label"] == "1 year"
    assert c.post("/api/view", json={"symbol": "ACME", "day": DAY, "tf": "1d", "span": 7}).status_code == 400
    assert c.post("/api/view", json={"symbol": "ACME", "day": DAY, "tf": "2d"}).status_code == 400
    assert c.post("/api/view", json={"symbol": "ACME", "day": DAY, "tf": 2}).status_code == 400
    assert c.post("/api/view", json={"symbol": "NOPE", "day": DAY, "tf": "1d"}).status_code == 404
    meta = c.get("/api/meta").json()["timeframes"]
    assert [t["id"] for t in meta["list"]] == [1, 3, 5, 15, "1d", "1w", "1M"] and [m for m, _ in meta["spans"]][-1] == 120


# ---------------------------------------------------------------- the collector: years of daily prices
def test_collector_keeps_years_of_daily_prices_and_tops_them_up(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=True)
    col.args.daily_years = 10
    store.write_daily("SPY", daily(pd.bdate_range(end="2026-10-16", periods=500).strftime("%Y-%m-%d")))  # older version: 2 years
    control.submit(["SPY"], day="2026-10-16")
    drain(col, clock)
    assert ("SPY", "10 Y") in ib.durations and store.daily_years("SPY") == 10       # deeper history fetched once
    n, oldest = len(store.read_daily("SPY")), store.read_daily("SPY")["date"].iloc[0]
    assert n >= 2500
    control.submit(["SPY"], day="2026-10-16")
    drain(col, clock)
    assert ib.durations.count(("SPY", "10 Y")) == 1                                  # not again
    # a later day: just the last month, added to the file
    later = Clock("2026-11-20 08:00")
    ib2, col2 = make(cache, later, live=True)
    col2.args.daily_years = 10
    control.submit(["SPY"], day="2026-11-19")
    drain(col2, later)
    assert ib2.durations == [("SPY", "1 M")]
    d = store.read_daily("SPY")
    assert len(d) > n and d["date"].iloc[0] == oldest and store.daily_years("SPY") == 10   # history kept


def test_collector_fetches_daily_vix_but_not_the_indicators(cache):
    clock = Clock("2026-10-20 08:00")
    ib, col = make(cache, clock, live=True)
    control.submit(["-VIX", "TICK-NYSE"], day="2026-10-16")
    drain(col, clock)
    assert [s for s, _ in ib.durations] == ["VIX"] and not store.read_daily("-VIX").empty
    assert control.has_daily("SPY") and control.has_daily("-VIX") and not control.has_daily("TICK-NYSE")
    assert not control.has_daily("ADD-NYSE")

