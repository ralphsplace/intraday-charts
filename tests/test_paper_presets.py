"""The recommended rules (app/paper/presets.py): every one is a valid rule, reads studies that don't look ahead,
says something on real-looking days, and opposite pairs never hold together; adding them is safe to repeat and
never writes over a rule of the same name."""
import pytest

import synthetic
from app import store
from app.paper import presets as P
from app.paper import rules as R
from app.paper import strategies as S

DAY = "2026-10-16"
REQUESTED = [f"Price {s} {x}" for x in ("VWAP", "SMA 50", "SMA 200", "EMA 9", "EMA 21", "ORH", "ORL") for s in ("above", "below")]


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("presets")
    synthetic.generate(d)
    return d


@pytest.fixture
def on_demo(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    import shutil
    shutil.rmtree(demo / "user", ignore_errors=True)
    return demo


def test_the_requested_rules_are_there_and_names_are_unique():
    names = [p["name"] for p in P.PRESETS]
    assert set(REQUESTED) <= set(names) and len(names) == len(set(names)) and len(names) >= 40


def test_every_recommended_rule_checks_reads_no_future_and_holds_on_some_bars(on_demo):
    P.add()
    saved = R.all_rules()
    assert set(saved) == set(P.BY_NAME)
    cache, days = {}, store.list_days("QQQ-DEMO")[-6:]
    for p in P.PRESETS:
        c = S.prepare({"buy": R.expr.text({"rule": p["name"]}), "tf": 3}, saved)
        specs = S.studies(c)
        R.check_no_repaint("QQQ-DEMO", DAY, 3, specs)
        held = 0
        for d in days:                                     # it says something on some bar of the last days
            key = (d, tuple(R._key(x) for x in specs))
            s = cache.setdefault(key, R.day_series("QQQ-DEMO", d, 3, specs))
            held += sum(R.holds(c["when"]["long"], s, i, {}) for i in range(len(s["bars"])))
            if held:
                break
        rare = p["name"].startswith(("RSI o", "Prior day"))   # extremes and yesterday's range: not every week
        assert held > 0 or rare, f"{p['name']} never holds in {days}"


def test_opposites_never_hold_on_the_same_bar(on_demo):
    P.add()
    saved = R.all_rules()
    pairs = [(f"Price above {x}", f"Price below {x}") for x in ("VWAP", "SMA 50", "SMA 200", "EMA 9", "EMA 21", "ORH", "ORL")]
    pairs += [("EMA 9 above EMA 21", "EMA 9 below EMA 21"), ("RSI above 50", "RSI below 50"), ("VWAP rising", "VWAP falling"),
              ("MACD above signal", "MACD below signal"), ("Bull trend", "Bear trend")]
    for up, down in pairs:
        c = S.prepare({"buy": R.expr.text({"rule": up}), "short": R.expr.text({"rule": down})}, saved)
        s = R.day_series("QQQ-DEMO", DAY, 3, S.studies(c))
        memo = {}
        both = [i for i in range(len(s["bars"])) if R.holds(c["when"]["long"], s, i, memo) and R.holds(c["when"]["short"], s, i, memo)]
        either = [i for i in range(len(s["bars"])) if R.holds(c["when"]["long"], s, i, memo) or R.holds(c["when"]["short"], s, i, memo)]
        assert both == [] and either, (up, down)


def test_adding_is_safe_to_repeat_and_keeps_yours(on_demo):
    R.save("Price above VWAP", {"conditions": [{"a": {"price": "close"}, "op": "above", "b": {"value": 1}}]})   # mine
    r = P.add(["Bull trend"])
    assert r == {"added": ["EMA 9 above EMA 21", "Bull trend"], "kept": ["Price above VWAP"]}     # what it's made of, first
    assert R.all_rules()["Price above VWAP"]["conditions"][0]["b"] == {"value": 1.0}              # not written over
    assert P.add(["Bull trend"])["added"] == []
    assert {x["name"]: x["added"] for x in P.listing()}["Bull trend"] is True
    with pytest.raises(KeyError):
        P.add(["Nope"])


def test_preset_endpoints(on_demo):
    from fastapi.testclient import TestClient

    from app.server import app
    c = TestClient(app, client=("192.168.1.20", 50000))
    ps = c.get("/api/paper/rules/presets").json()["presets"]
    assert len(ps) == len(P.PRESETS) and not any(p["added"] for p in ps)
    r = c.post("/api/paper/rules/presets", json={"names": ["Price above ORH", "Price below ORL"]}).json()
    assert r["added"] == ["Price above ORH", "Price below ORL"] and set(r["rules"]) == {"Price above ORH", "Price below ORL"}
    assert r["rules"]["Price above ORH"]["conditions"][0]["b"]["study"]["output"] == "level:OR high"
    assert c.post("/api/paper/rules/presets", json={"names": ["x"]}).status_code == 404
    assert len(c.post("/api/paper/rules/presets", json={}).json()["rules"]) == len(P.PRESETS)
