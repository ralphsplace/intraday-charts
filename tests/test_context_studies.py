"""Context studies: the countdown to the next event, the daily range meter, relative strength against another
symbol, and the heavyweights strip; plus how a study names the symbols it needs. All prices are invented."""
import json

import pandas as pd
import pytest

from app import engine, holdings, store
from app.studies.levels import countdown
from app.studies.outputs import problems

ET = "America/New_York"
DAY, PREV = "2026-10-16", "2026-10-15"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return tmp_path


def bars(day, prices, start=570, spread=0.05):
    t = pd.Timestamp(day, tz=ET) + pd.to_timedelta([start + i for i in range(len(prices))], unit="min")
    return pd.DataFrame({"time": t, "open": prices, "high": [x + spread for x in prices],
                         "low": [x - spread for x in prices], "close": prices, "volume": 1000.0})


def run(symbol, cursor, type, params=None, tf=1, events_path=None):
    v = engine.build_view(symbol, DAY, tf=tf, cursor=cursor, events_path=events_path,
                          studies=[{"uid": "s", "type": type, "params": params or {}}])
    r = v["studies"]["s"]
    assert r["ok"], r.get("error")
    return r


# ---------------------------------------------------------------- countdown
def test_countdown_to_the_next_scheduled_event(cache):
    store.write_day("ACME", DAY, bars(DAY, [100.0] * 60))
    ev = cache / "events.json"
    ev.write_text(json.dumps([{"date": DAY, "time": "08:30", "label": "CPI", "kind": "scheduled"},
                              {"date": DAY, "time": "14:00", "label": "FOMC", "kind": "scheduled"},
                              {"date": DAY, "time": "09:45", "label": "Big move", "kind": "move"}]))
    r = run("ACME", 600, "events", events_path=ev)                         # 10:00
    assert r["labels"] == [{"text": "Next: FOMC 14:00, in 4h 00m", "bg": "#9b8cff"}]
    assert len(r["verticals"]) == 3
    assert "labels" not in run("ACME", 600, "events", {"countdown": False}, events_path=ev)
    assert [countdown(m) for m in (0, 42, 60, 185)] == ["under a minute", "42m", "1h 00m", "3h 05m"]


# ---------------------------------------------------------------- daily range meter
def test_range_meter(cache):
    for d in pd.bdate_range(end=PREV, periods=5).strftime("%Y-%m-%d"):
        store.write_day("ACME", d, bars(d, [100.0, 104.0], spread=0.0))      # 4.00 range every day
    store.write_day("ACME", DAY, bars(DAY, [100.0, 101.0, 99.0, 105.0], spread=0.0))
    r = run("ACME", 573, "range_meter", {"length": 5, "targets": True})     # high 101, low 99 by 09:33
    assert r["labels"] == [{"text": "Day range 2.00 = 50% of the 5-day average (4.00)", "bg": "#e6b450"}]
    assert {lv["label"]: lv["price"] for lv in r["levels"]} == {"Avg day ↑": 103.0, "Avg day ↓": 97.0}
    r = run("ACME", 574, "range_meter", {"length": 5})
    assert r["labels"][0]["text"].startswith("Day range 6.00 = 150%") and r["labels"][0]["bg"] == "#ef5350"
    assert "levels" not in r
    r = run("ACME", 571, "range_meter", {"length": 5})
    assert r["labels"][0]["bg"] == "#2bb39a"                                # 0% so far


# ---------------------------------------------------------------- relative strength
def test_relative_strength(cache):
    store.write_day("ACME", DAY, bars(DAY, [100.0, 102.0, 103.0]))
    store.write_day("SPY", DAY, bars(DAY, [50.0, 50.5, 51.0]))
    r = run("ACME", 600, "relative_strength")
    vals = [p["value"] for p in r["lines"][0]["data"]]
    assert vals == [0.0, pytest.approx((1.02 / 1.01 - 1) * 100, abs=1e-3), pytest.approx((1.03 / 1.02 - 1) * 100, abs=1e-3)]
    assert r["needs"] == ["SPY"] and r["note"] == "ACME vs SPY: +0.98% since 09:30"
    r = run("ACME", 600, "relative_strength", {"symbol": "QQQ"})
    assert not r.get("lines") and r["needs"] == ["QQQ"] and r["note"] == "waiting for QQQ bars"
    assert run("ACME", 600, "relative_strength", {"symbol": "ACME"})["note"] == "compare with a different symbol"
    assert "isn't a symbol" in run("ACME", 600, "relative_strength", {"symbol": "no way"})["note"]


# ---------------------------------------------------------------- heavyweights
def test_heavyweights_contributions(cache):
    (cache / "heavyweights.json").write_text(json.dumps(
        {"QQQ": {"as_of": "2026-10-01", "source": "test", "weights": {"BIG": 10.0, "MID": 5.0, "bad sym": 3, "NEW": 1.0}}}))
    for sym, prev, now in (("BIG", 100.0, 102.0), ("MID", 50.0, 49.0), ("QQQ", 400.0, 404.0)):
        store.write_day(sym, PREV, bars(PREV, [prev] * 3))
        store.write_day(sym, DAY, bars(DAY, [prev, now]))
    r = run("QQQ", 600, "heavyweights", {"count": 3})
    texts = [lb["text"] for lb in r["labels"]]
    assert texts == ["Top 3: +0.10 of QQQ +1.00%", "BIG +2.00% (+0.20)", "MID -2.00% (-0.10)", "NEW …"]
    assert [lb["bg"] for lb in r["labels"][1:]] == ["#1f6f5f", "#7a2e2e", "#3a4150"]
    assert r["needs"] == ["BIG", "MID", "NEW"] and r["note"] == "weights as of 2026-10-01; waiting for 1 of 3"
    r = run("QQQ", 600, "heavyweights", {"count": 3, "start": "Today's open"})
    assert r["labels"][1]["text"] == "BIG +2.00% (+0.20)"
    assert "no holdings listed for SPY" in run("QQQ", 600, "heavyweights", {"fund": "SPY"})["note"]
    (cache / "heavyweights.json").write_text(json.dumps({"QQQ": {"as_of": "x", "weights": {"NEW": 1.0}}}))
    assert run("QQQ", 600, "heavyweights")["labels"][0]["bg"] == "#3a4150"   # nothing to add up yet: neutral


def test_shipped_holdings_and_override(cache):
    q = holdings.fund("qqq")
    assert q["as_of"] == "2026-10-02" and list(q["weights"])[:3] == ["NVDA", "AAPL", "MSFT"]
    assert list(q["weights"].values()) == sorted(q["weights"].values(), reverse=True)        # heaviest first
    (cache / "heavyweights.json").write_text("not json")
    assert holdings.fund("QQQ")["as_of"] == "2026-10-02"                     # a broken override falls back
    (cache / "heavyweights.json").write_text(json.dumps({"QQQ": {"as_of": "x", "weights": {"AAPL": 9.0}}}))
    assert holdings.fund("QQQ")["weights"] == {"AAPL": 9.0}


def test_needs_is_a_list_of_symbols():
    assert problems({"needs": ["SPY"]}) == []
    assert problems({"needs": "SPY"}) == ["needs should be list"]
    assert problems({"needs": [1]}) == ["needs should be a list of symbols"]
