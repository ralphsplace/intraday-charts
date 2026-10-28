"""Session structure studies: Initial Balance, anchored VWAP, relative volume by time of day, TPO profile.
All prices are invented."""
import pandas as pd
import pytest

from app import engine, store
from app.studies.levels import ib_state

ET = "America/New_York"
DAY, PREV, PREV2 = "2026-10-16", "2026-10-15", "2026-10-14"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return tmp_path


def bars(day, prices, vol=1000.0, start=570):
    """One bar a minute from `start` (09:30): each price is that bar's open/close; high/low +/- 0.05."""
    t = pd.Timestamp(day, tz=ET) + pd.to_timedelta([start + i for i in range(len(prices))], unit="min")
    vols = vol if isinstance(vol, list) else [vol] * len(prices)
    return pd.DataFrame({"time": t, "open": prices, "high": [p + 0.05 for p in prices], "low": [p - 0.05 for p in prices],
                         "close": prices, "volume": vols})


def study(symbol, cursor, type, params=None, tf=1, days=1):
    v = engine.build_view(symbol, DAY, tf=tf, cursor=cursor, days=days,
                          studies=[{"uid": "s", "type": type, "params": params or {}}])
    r = v["studies"]["s"]
    assert r["ok"], r.get("error")
    return r, v


# ---------------------------------------------------------------- Initial Balance
def test_initial_balance_levels_and_extensions(cache):
    # first hour between 100 and 102, then up to 105
    prices = [100.0] * 30 + [102.0] * 30 + [103.0] * 30 + [105.0] * 30
    store.write_day("ACME", DAY, bars(DAY, prices))
    r, _ = study("ACME", 600, "initial_balance")                       # 10:00: still building
    assert [lv["label"] for lv in r["levels"]] == ["IB high (building)", "IB low (building)", "IB mid (building)"]
    assert "building" in r["note"]
    r, _ = study("ACME", 700, "initial_balance", {"extensions": "1x and 2x"})
    px = {lv["label"]: lv["price"] for lv in r["levels"]}
    assert (px["IB high"], px["IB low"], px["IB mid"]) == (102.05, 99.95, 101.0)
    assert px["IB +1x"] == pytest.approx(104.15) and px["IB −2x"] == pytest.approx(95.75)
    assert r["box"]["high"] == 102.05 and r["box"]["low"] == 99.95
    assert r["note"] == "range 2.10, extended up 1.4x the IB range"      # 105.05 is 3.00 above the IB high
    r, _ = study("ACME", 700, "initial_balance", {"minutes": "30", "extensions": "Off", "mid": False, "box": False})
    assert [lv["label"] for lv in r["levels"]] == ["IB high", "IB low"] and "box" not in r
    pre = pd.concat([bars(DAY, [99.0] * 10, start=540), bars(DAY, prices)], ignore_index=True)
    store.write_day("BETA", DAY, pre)
    r, _ = study("BETA", 560, "initial_balance")                       # 09:20, premarket
    assert r["levels"] == [] and r["note"] == "starts at 09:30"


def test_ib_state_describes_without_signalling():
    assert ib_state(102, 100, 101.5, 100.2) == "inside the IB so far"
    assert ib_state(102, 100, 102, 97) == "extended down 1.5x the IB range"
    assert ib_state(102, 100, 103, 99) == "traded out both sides"


# ---------------------------------------------------------------- anchored VWAP
def test_anchored_vwap_from_a_chosen_time(cache):
    store.write_day("ACME", DAY, bars(DAY, [100.0, 101.0, 102.0, 104.0], vol=[1000.0, 1000.0, 3000.0, 1000.0]))
    r, v = study("ACME", 600, "anchored_vwap", {"anchor": "Chosen time", "at": f"{DAY} 09:31", "bands": False})
    line = r["lines"][0]["data"]
    assert [p["value"] for p in line] == [101.0, pytest.approx(101.75), pytest.approx((101 + 3 * 102 + 104) / 5)]
    assert line[0]["time"] == v["bars"][1]["time"]                    # starts at the anchor bar
    assert r["verticals"][0]["time"] == v["bars"][1]["time"] and r["note"] == f"from {DAY} 09:31"
    r, _ = study("ACME", 600, "anchored_vwap", {"at": f"{DAY} 15:00"})
    assert not r["lines"] and "after the replay time" in r["note"]
    r, _ = study("ACME", 600, "anchored_vwap", {"at": "yesterday-ish"})
    assert not r["lines"] and "can't read" in r["note"]


def test_anchored_vwap_bands_start_at_zero_width(cache):
    store.write_day("ACME", DAY, bars(DAY, [100.0, 102.0, 101.0]))
    r, _ = study("ACME", 600, "anchored_vwap", {"at": f"{DAY} 09:30", "band1": 1.0})
    by_id = {ln["id"]: [p["value"] for p in ln["data"]] for ln in r["lines"]}
    assert by_id["band1_up"][0] == by_id["vwap"][0] == by_id["band1_dn"][0]
    assert by_id["band1_up"][-1] > by_id["vwap"][-1] > by_id["band1_dn"][-1]


def test_anchored_vwap_from_highs_lows_and_across_days(cache):
    store.write_day("ACME", PREV, bars(PREV, [100.0, 110.0, 105.0]))   # prior day high at 09:31
    store.write_day("ACME", DAY, bars(DAY, [104.0, 103.0, 106.0, 102.0]))
    r, _ = study("ACME", 600, "anchored_vwap", {"anchor": "Prior day high"}, days=2)
    assert r["note"] == f"from prior day high {PREV} 09:31"
    assert r["lines"][0]["data"][0]["value"] == 110.0 and len(r["lines"][0]["data"]) == 2 + 4   # carries into today
    r, _ = study("ACME", 600, "anchored_vwap", {"anchor": "High of day"})
    assert r["note"] == "from high of day 09:32" and r["lines"][0]["data"][0]["value"] == 106.0
    r, _ = study("ACME", 600, "anchored_vwap", {"anchor": "Low of day"})
    assert r["note"] == "from low of day 09:33"
    r, _ = study("ACME", 600, "anchored_vwap", {"anchor": "Latest event today"})
    assert not r["lines"] and "no event" in r["note"]


def test_anchored_vwap_skips_extended_hours_unless_asked(cache):
    pre = bars(DAY, [90.0, 90.0], start=540)                            # 09:00 premarket
    store.write_day("ACME", DAY, pd.concat([pre, bars(DAY, [100.0, 100.0])], ignore_index=True))
    r, _ = study("ACME", 600, "anchored_vwap", {"at": f"{DAY} 09:00"})
    assert r["lines"][0]["data"][-1]["value"] == 100.0
    r, _ = study("ACME", 600, "anchored_vwap", {"at": f"{DAY} 09:00", "extended": True})
    assert r["lines"][0]["data"][-1]["value"] == 95.0


# ---------------------------------------------------------------- relative volume by time of day
def test_rvol_compares_each_bar_with_its_own_time_slot(cache):
    for d in ("2026-10-13", PREV2, PREV):
        store.write_day("ACME", d, bars(d, [100.0] * 4, vol=[4000.0, 1000.0, 1000.0, 1000.0]))   # busy open
    store.write_day("ACME", DAY, bars(DAY, [100.0] * 4, vol=[4000.0, 2000.0, 500.0, 100.0]))
    r, _ = study("ACME", 600, "rvol", {"sessions": 3, "high": 2.0, "low": 0.5})
    hist = r["histograms"][0]["data"]
    assert [h["value"] for h in hist] == [1.0, 2.0, 0.5, 0.1]              # a big open is normal for the open
    assert [h["color"] for h in hist][1:] == ["#26a69a", "#8a8f98", "#4a525e"]
    assert r["hlines"][0]["price"] == 1.0 and "note" not in r
    r, _ = study("ACME", 600, "rvol", {"sessions": 10})
    assert r["note"] == "averaged over 3 cached sessions"


# ---------------------------------------------------------------- TPO / Market Profile
def test_tpo_counts_time_at_price_and_carries_levels(cache):
    # two days back: POC around 90, never revisited (naked). Prior day: POC around 100, revisited today.
    store.write_day("ACME", PREV2, bars(PREV2, [90.0] * 90 + [95.0] * 30))
    store.write_day("ACME", PREV, bars(PREV, [100.0] * 90 + [99.0] * 30))
    store.write_day("ACME", DAY, bars(DAY, [99.5] * 60 + [100.0] * 60 + [104.0] * 30))
    r, _ = study("ACME", 960, "tpo", {"row_mode": "Custom price per row", "row_price": 0.5, "naked": 5})
    px = {lv["label"]: lv["price"] for lv in r["levels"]}
    assert px["TPO POC"] in (99.5, 100.0) and px["pPOC"] == 100.0
    assert px["nPOC 10-14"] == 90.0 and not any(k.startswith("nPOC 10-15") for k in px)   # prior day: drawn as pPOC
    counts = {b["lo"]: b["vol"] for b in r["profile"]["bins"]}
    assert max(counts.values()) == 2 and counts[103.75] == 1             # 104 for one 30-minute period
    assert r["profile"]["side"] == "right"
    r, _ = study("ACME", 960, "tpo", {"row_mode": "Custom price per row", "row_price": 0.5, "prior": False, "naked": 5})
    labels = [lv["label"] for lv in r["levels"]]
    assert "pPOC" not in labels and "nPOC 10-14" in labels and "nPOC 10-15" not in labels   # 100 was revisited today


def test_volume_profile_unchanged_by_the_shared_rows(cache):
    store.write_day("ACME", DAY, bars(DAY, [100.0] * 10 + [101.0] * 2, vol=1000.0))
    r, _ = study("ACME", 960, "volume_profile", {"row_mode": "Custom price per row", "row_price": 0.5})
    px = {lv["label"]: lv["price"] for lv in r["levels"]}
    assert px["POC"] == 100.0 and r["profile"]["side"] == "left"
