"""Paper trading rules (app/paper/rules.py): conditions on hand-built series, the N-bar window, rules refused with
a reason, study lines from the same code as the charts, and the check that refuses a study that repaints."""
import pytest

import synthetic
from app import store
from app.paper import rules as R
from app.studies import base as studies_base

DAY = "2026-10-16"
CLOSE = {"price": "close"}


def series(closes, line=None):
    bars = [{"start": 570 + i, "end": 571 + i, "ct": i, "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(closes)]
    s = {"bars": bars}
    if line is not None:
        s["sma:sma:[('length', 3), ('source', 'close')]"] = line
    return s


def rule(**kw):
    return R.check({"long": [{"a": CLOSE, "op": "above", "b": {"value": 100}}], **kw})


def test_comparisons_and_crossings():
    s = series([99, 101, 102, 98, 103])
    holds = lambda op: [R._holds({"a": CLOSE, "op": op, "b": {"value": 100}}, s, i) for i in range(5)]   # noqa: E731
    assert holds("above") == [False, True, True, False, True]
    assert holds("below") == [True, False, False, True, False]
    assert holds("crosses_above") == [False, True, False, False, True]
    assert holds("crosses_below") == [False, False, False, True, False]


def test_signals_are_read_at_the_close_and_go_in_on_the_next_minute():
    r = rule(long=[{"a": CLOSE, "op": "crosses_above", "b": {"value": 100}}])
    sig = R.signals(r, series([99, 101, 102, 98, 103]))
    assert [(x["minute"], x["what"]) for x in sig] == [(572, "long"), (575, "long")]


def test_conditions_within_n_bars():
    a = {"a": CLOSE, "op": "crosses_above", "b": {"value": 100}}
    b = {"a": CLOSE, "op": "above", "b": {"value": 104}}
    s = series([99, 101, 102, 105, 106])
    assert R.signals(rule(long=[a, b], within=1), s) == []
    assert [x["minute"] for x in R.signals(rule(long=[a, b], within=3), s)] == [574]    # 105 is within 3 bars of the cross
    assert R.signals(rule(long=[a, b], within=2), s) == []


def test_rules_are_checked_with_reasons():
    for bad, why in (({}, "entry conditions"), ({"long": [{"a": CLOSE, "op": "near", "b": CLOSE}]}, "op is one of"),
                     ({"long": [{"a": {"price": "mid"}, "op": "above", "b": CLOSE}]}, "price is one of"),
                     ({"long": [{"a": {"study": {"type": "nope"}}, "op": "above", "b": CLOSE}]}, "unknown study"),
                     ({"long": [{"a": {"study": {"type": "sma", "output": "x"}}, "op": "above", "b": CLOSE}]}, "has the lines"),
                     ({"long": [{"a": CLOSE, "op": "above", "b": CLOSE}], "tf": 4}, "tf is one of"),
                     ({"long": [{"a": CLOSE, "op": "above", "b": CLOSE}], "exits": {"stop": 1, "trail": 1}}, "not both"),
                     ({"long": [{"a": CLOSE, "op": "above", "b": CLOSE}], "hours": {"from": 900, "to": 600}}, "hours")):
        with pytest.raises(ValueError, match=why):
            R.check(bad)
    r = R.check({"long": [{"a": {"study": {"type": "sma"}}, "op": "above", "b": CLOSE}]})
    assert r["long"][0]["a"]["study"]["params"]["length"] == studies_base.REGISTRY["sma"]["params"][0]["default"]
    assert r["hours"] == {"from": 570, "to": 950} and r["order"] == {"type": "market"} and r["qty"] == 100


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("rules")
    synthetic.generate(d)
    return d


def test_study_lines_come_from_the_chart_code(demo, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    r = R.check({"tf": 3, "long": [{"a": CLOSE, "op": "crosses_above", "b": {"study": {"type": "vwap", "output": "vwap"}}}]})
    s = R.day_series("QQQ-DEMO", DAY, 3, r)
    vw = s[R._key(r["long"][0]["b"]["study"])]
    assert len(vw) == len(s["bars"]) and sum(v is not None for v in vw) > 100
    R.check_no_repaint("QQQ-DEMO", DAY, 3, r)                          # VWAP never changes its past
    assert all(x["what"] == "long" for x in R.signals(r, s))


def test_a_study_that_repaints_is_refused(demo, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    spec = studies_base.REGISTRY["sma"]
    real = spec["compute"]

    def repaints(ctx, p):                                                # shifts its whole line by the last price
        out = real(ctx, p)
        for ln in out["lines"]:
            ln["data"] = [{**pt, "value": pt["value"] + ctx.price} for pt in ln["data"]]
        return out
    monkeypatch.setitem(spec, "compute", repaints)
    r = R.check({"long": [{"a": CLOSE, "op": "above", "b": {"study": {"type": "sma"}}}]})
    with pytest.raises(ValueError, match="changes its past values"):
        R.check_no_repaint("QQQ-DEMO", DAY, 3, r)


def test_saved_rules_are_named(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    n, item = R.save(None, {"long": [{"a": CLOSE, "op": "above", "b": {"value": 1}}]})
    assert n == "Rule 1" and item["rule"]["qty"] == 100
    n2, item2 = R.save("Rule 1", {"long": [{"a": CLOSE, "op": "above", "b": {"value": 2}}], "qty": 5})
    assert n2 == "Rule 1" and item2["id"] == item["id"] and item2["rule"]["qty"] == 5


def test_rule_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.server import app
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    c = TestClient(app, client=("192.168.1.20", 50000))
    r = c.post("/api/paper/rules", json={"rule": {"long": [{"a": CLOSE, "op": "above", "b": {"value": 1}}]}}).json()
    assert r["name"] == "Rule 1" and "crosses_above" in c.get("/api/paper/rules").json()["ops"]
    assert c.post("/api/paper/rules", json={"rule": {}}).status_code == 400
    assert c.post("/api/paper/rules/Rule 1/rename", json={"to": "VWAP pullback"}).json()["name"] == "VWAP pullback"
    assert c.delete("/api/paper/rules/VWAP pullback").json()["rules"] == {}
