"""Watch list columns: the registry, each group's values (on synthetic bars, no network), market internals and
indexes left without meaningless values, Replay up to the cursor, and the study values the columns (and later
anything that needs a study's price) read."""
import shutil

import pytest
from fastapi.testclient import TestClient

import synthetic
from app import engine, quotes, store, study_values, watch_fields
from app.studies import base as studies_base


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    synthetic.generate(tmp_path)
    return tmp_path


ALL = [c["id"] for c in watch_fields.COLUMNS]


def test_the_registry_is_consistent():
    ids = [c["id"] for c in watch_fields.COLUMNS]
    assert len(ids) == len(set(ids))
    groups = set(watch_fields.GROUPS) | {"quote", "holding", "finviz"}
    for c in watch_fields.COLUMNS:
        assert c["group"] in groups and c["lists"] in ("all", "holding", "finviz") and c["kind"], c
    for kind, cols in watch_fields.DEFAULTS.items():
        assert cols[0] == "symbol" and all(x in ids for x in cols), kind
    assert watch_fields.groups_for(["last", "pct", "qty", "company"]) == set()          # nothing extra to compute
    assert watch_fields.groups_for(["gap_pct", "spark", "st_sma50_5m"]) == {"day", "spark", "study:sma50_5m"}


def test_values_from_the_cached_bars(cache):
    day = store.list_days("QQQ-DEMO")[-1]
    r = watch_fields.row("QQQ-DEMO", day, None, watch_fields.groups_for(ALL))
    q = quotes.row("QQQ-DEMO", day)
    df = store.read_day("QQQ-DEMO", day)
    m = engine.minute_of_day(df["time"])
    rth = df[(m >= engine.RTH_START) & (m < engine.RTH_END)]
    op = float(rth["open"].iloc[0])
    assert r["open"] == pytest.approx(op) and r["gap_pct"] == pytest.approx((op - q["prev_close"]) / q["prev_close"] * 100, abs=1e-3)
    assert r["chg_open"] == pytest.approx(q["last"] - op, abs=1e-4)
    vw = float(engine.vwap_frame(rth)["vwap"].iloc[-1])
    assert r["vwap"] == pytest.approx(vw, abs=1e-3) and r["vwap_state"] == ("above VWAP" if q["last"] > vw else "below VWAP")
    d = engine.prior_context("QQQ-DEMO", day, lookback=260)
    assert r["pdh"] == pytest.approx(float(d["high"].iloc[-1])) and r["hi52"] >= r["high"]
    assert r["range_atr"] == pytest.approx((q["high"] - q["low"]) / r["atr"], abs=1e-3)
    assert 0.2 < r["rvol"] < 5 and r["atr_zone"] and r["ib_state"]
    sp = r["spark"]
    assert 2 <= len(sp["p"]) <= watch_fields.SPARK_POINTS and sp["p"][-1] == pytest.approx(q["last"]) and sp["base"] == q["prev_close"]
    assert r["st_sma50_5m"] == study_values.value("QQQ-DEMO", day, watch_fields.STUDY_SPECS["sma50_5m"])["value"]
    assert r["vs_st_sma50_5m"] == pytest.approx((q["last"] - r["st_sma50_5m"]) / r["st_sma50_5m"] * 100, abs=1e-3)


def test_replay_values_stop_at_the_cursor(cache):
    day = store.list_days("QQQ-DEMO")[-1]
    early = watch_fields.row("QQQ-DEMO", day, 10 * 60, watch_fields.groups_for(ALL))
    assert early["ib_state"] == "IB building" and early["last"] == quotes.row("QQQ-DEMO", day, 10 * 60)["last"]
    pre = watch_fields.row("QQQ-DEMO", day, 9 * 60, watch_fields.groups_for(ALL))
    assert pre["vwap_state"] == "before 09:30" and "gap_pct" not in pre


def test_internals_and_indexes_get_only_what_means_something(cache):
    if not (cache / "bars" / "TICK-NYSE").exists():
        shutil.copytree(cache / "bars" / "QQQ-DEMO", cache / "bars" / "TICK-NYSE")
    day = store.list_days("QQQ-DEMO")[-1]
    if day not in store.list_days("VIX"):
        shutil.copytree(cache / "bars" / "SPY-DEMO", cache / "bars" / "VIX", dirs_exist_ok=True)
    t = watch_fields.row("TICK-NYSE", day, None, watch_fields.groups_for(ALL))
    assert "spark" in t and not any(k in t for k in ("gap_pct", "vwap", "atr_zone", "rvol", "st_sma50_5m"))
    vix_df = store.read_day("VIX", day)
    vix_df["volume"] = 0.0                                                   # indexes trade no volume
    vix_df.to_parquet(store.day_path("VIX", day))
    v = watch_fields.row("VIX", day, None, watch_fields.groups_for(ALL))
    assert v["vwap"] is None and v["vwap_state"] is None and "rvol" not in v and v["gap_pct"] is not None


def test_a_missing_symbol_and_a_failing_group(cache, monkeypatch):
    day = store.list_days("QQQ-DEMO")[-1]
    assert watch_fields.row("NOPE", day, None, {"day"}) == {"symbol": "NOPE", "status": "missing"}

    def boom(*a):
        raise ValueError("broken")
    monkeypatch.setitem(watch_fields.GROUPS, "daily", boom)
    r = watch_fields.row("QQQ-DEMO", day, None, {"daily", "day"})
    assert r["status"] == "ok" and "open" in r and r["notes"] == ["daily: broken"]


def test_earnings_from_the_calendar_or_the_last_report(cache, monkeypatch):
    day = store.list_days("QQQ-DEMO")[-1]
    monkeypatch.setattr(watch_fields, "_calendar", lambda mtime: [
        {"date": "2099-01-28", "time": "16:05", "label": "QQQ-DEMO earnings (after close)", "category": "earnings"}])
    r = watch_fields.row("QQQ-DEMO", day, None, {"events"})
    assert r["earnings"]["date"] == "2099-01-28" and r["earnings"]["days"] > 0 and not r["earnings"].get("last")
    synthetic.generate_earnings(cache, "ACME-DEMO")
    monkeypatch.setattr(watch_fields, "_calendar", lambda mtime: [])
    d = store.list_days("ACME-DEMO")
    if d:
        r = watch_fields.row("ACME-DEMO", d[-1], None, {"events"})
        assert r.get("earnings", {}).get("last") in (True, None)


def test_study_values_match_the_charts(cache):
    day = store.list_days("QQQ-DEMO")[-1]
    spec = {"type": "sma", "params": {"length": 50}, "output": "sma", "tf": 5}
    v = study_values.value("QQQ-DEMO", day, spec)["value"]
    ctx = engine.DayContext("QQQ-DEMO", day, 5)
    line = studies_base.run_study(ctx, "sma", {"length": 50})["lines"][0]["data"]
    assert v == pytest.approx(line[-1]["value"])
    assert study_values.value("QQQ-DEMO", day, {"type": "saty_atr", "output": "atr_up"})["value"] > 0     # a level, by plot
    assert study_values.value("QQQ-DEMO", day, {"type": "vwap"}, cursor=9 * 60)["value"] is None         # before 09:30
    assert study_values.value("NOPE", day, {"type": "vwap"})["note"].startswith("No cached bars")
    for bad in ({"type": "nope"}, {"type": "sma", "tf": 7}):
        with pytest.raises(ValueError):
            study_values.value("QQQ-DEMO", day, bad)


@pytest.fixture
def client(cache):
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_endpoints(client, cache):
    day = store.list_days("QQQ-DEMO")[-1]
    cat = client.get("/api/watch/columns").json()
    assert {c["id"] for c in cat["columns"]} >= {"spark", "day_range", "range52", "rvol", "vwap_state", "st_sma50_5m"}
    r = client.get("/api/quotes", params={"symbols": "QQQ-DEMO", "day": day, "cols": "symbol,gap_pct,spark,bogus"}).json()
    assert "gap_pct" in r["items"][0] and "spark" in r["items"][0] and "st_sma50_5m" not in r["items"][0]
    plain = client.get("/api/quotes", params={"symbols": "QQQ-DEMO", "day": day}).json()["items"][0]
    assert "gap_pct" not in plain                                       # only what's asked for
    v = client.get("/api/study-value", params={"symbol": "QQQ-DEMO", "day": day, "type": "sma", "params": '{"length": 50}',
                                               "tf": 5, "output": "sma"}).json()
    assert v["value"] == study_values.value("QQQ-DEMO", day, {"type": "sma", "params": {"length": 50}, "tf": 5, "output": "sma"})["value"]
    assert client.get("/api/study-value", params={"symbol": "QQQ-DEMO", "day": day, "type": "nope"}).status_code == 400
    assert client.get("/api/study-value", params={"symbol": "QQQ-DEMO", "day": day, "type": "sma", "params": "[1]"}).status_code == 400
