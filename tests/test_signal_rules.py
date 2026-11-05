"""Signal rules and strategies (app/signals/rules.py, expr.py, strategies.py): conditions on hand-built series,
nested true / false expressions of conditions and of other rules, rules refused with a reason, study lines and levels
from the same code as the charts, and the check that refuses a study that repaints."""
import pytest

import synthetic
from app import store
from app.signals import expr as E
from app.signals import rules as R
from app.signals import strategies as S
from app.studies import base as studies_base
from signal_help import strategy

DAY = "2026-10-16"
CLOSE = {"price": "close"}


def series(closes, line=None):
    bars = [{"start": 570 + i, "end": 571 + i, "ct": i, "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(closes)]
    s = {"bars": bars}
    if line is not None:
        s["sma:sma:[('length', 3), ('source', 'close')]"] = line
    return s


def above(v):
    return {"a": CLOSE, "op": "above", "b": {"value": v}}


def test_comparisons_and_crossings():
    s = series([99, 101, 102, 98, 103])
    holds = lambda op: [R._holds({"a": CLOSE, "op": op, "b": {"value": 100}}, s, i) for i in range(5)]   # noqa: E731
    assert holds("above") == [False, True, True, False, True]
    assert holds("below") == [True, False, False, True, False]
    assert holds("crosses_above") == [False, True, False, False, True]
    assert holds("crosses_below") == [False, False, False, True, False]


def test_signals_are_read_at_the_close_and_go_in_on_the_next_minute():
    r = strategy(long=[{"a": CLOSE, "op": "crosses_above", "b": {"value": 100}}])
    sig = S.signals(r, series([99, 101, 102, 98, 103]))
    assert [(x["minute"], x["what"]) for x in sig] == [(572, "long"), (575, "long")]


def test_conditions_within_n_bars():
    a = {"a": CLOSE, "op": "crosses_above", "b": {"value": 100}}
    b = {"a": CLOSE, "op": "above", "b": {"value": 104}}
    s = series([99, 101, 102, 105, 106])
    assert S.signals(strategy(long=[a, b], within=1), s) == []
    assert [x["minute"] for x in S.signals(strategy(long=[a, b], within=3), s)] == [574]    # 105 is within 3 bars of the cross
    assert S.signals(strategy(long=[a, b], within=2), s) == []


def test_rules_are_checked_with_reasons():
    for bad, why in (({}, "needs conditions"), ({"conditions": [{"a": CLOSE, "op": "near", "b": CLOSE}]}, "op is one of"),
                     ({"conditions": [{"a": {"price": "mid"}, "op": "above", "b": CLOSE}]}, "price is one of"),
                     ({"conditions": [{"a": {"study": {"type": "nope"}}, "op": "above", "b": CLOSE}]}, "unknown study"),
                     ({"conditions": [{"a": {"study": {"type": "sma", "output": "x"}}, "op": "above", "b": CLOSE}]}, "pick one of"),
                     ({"conditions": [{"a": {"study": {"type": "events"}}, "op": "above", "b": CLOSE}]}, "no line or level"),
                     ({"conditions": [above(1)], "when": "A AND B"}, "uses B, but the rule has conditions A to A"),
                     ({"conditions": [above(1)], "when": "A AND (B"}, "Expected"),
                     ({"conditions": [above(1)], "when": "A AND Nope"}, 'no rule called "Nope"'),
                     ({"conditions": [above(1)] * 27}, "at most 26")):
        with pytest.raises(ValueError, match=why):
            R.check(bad, {})
    r = R.check({"conditions": [{"a": {"study": {"type": "sma"}}, "op": "above", "b": CLOSE}, above(1)]}, {})
    assert r["conditions"][0]["a"]["study"]["params"]["length"] == studies_base.REGISTRY["sma"]["params"][0]["default"]
    assert r["when"] == "A AND B"                                          # every condition, by default
    for bad, why in (({"buy": ""}, "Buy if, Sell short if"), ({"buy": "A"}, "would be a rule's own condition"),
                     ({"buy": "Nope"}, 'no rule called "Nope"'), ({"buy": "R1", "tf": 4}, "tf is one of"),
                     ({"buy": "R1", "exits": {"stop": 1, "trail": 1}}, "one stop"),
                     ({"buy": "R1", "exits": {"trail": 1, "trail_atr": 2}}, "one stop"), ({"buy": "R1", "exits": {"trail_atr": 25}}, "0 to 20"),
                     ({"buy": "R1", "hours": {"from": 900, "to": 600}}, "hours"), ({"buy": "R1 OR"}, "Buy if: The expression ends")):
        with pytest.raises(ValueError, match=why):
            S.check(bad, {"R1": r})
    st = S.check({"buy": "R1"}, {"R1": r})
    assert st["hours"] == {"from": 570, "to": 950} and st["order"] == {"type": "market"} and st["qty"] == 100 and st["short"] == ""


# ---------------------------------------------------------------- nested expressions (#67)
def test_expressions_parse_print_and_say_where_they_are_wrong():
    t = E.parse("(A OR B) AND !(X OR (S AND H))")
    assert t == {"and": [{"or": [{"cond": "A"}, {"cond": "B"}]},
                         {"not": {"or": [{"cond": "X"}, {"and": [{"cond": "S"}, {"cond": "H"}]}]}}]}
    assert E.text(t) == "(A OR B) AND NOT (X OR (S AND H))"
    t = E.parse('((Rule1 and !"Rule 3") || Rule5)')
    assert E.text(t) == '(Rule1 AND NOT "Rule 3") OR Rule5' and E.refs(t) == ([], ["Rule1", "Rule 3", "Rule5"])
    assert E.parse("a & b | c") == E.parse("(a AND b) OR c")             # AND before OR
    assert E.text(E.parse('"A" OR "my \\"best\\" rule"')) == '"A" OR "my \\"best\\" rule"'   # a rule called A, quotes in names
    assert E.parse("WITHIN 3 (A AND B)") == {"within": 3, "of": {"and": [{"cond": "A"}, {"cond": "B"}]}}
    for bad, where in (("A B", 3), ("(A OR B", 8), ("A AND", 6), ("A $ B", 3), ('"open', 1), ("WITHIN 99 A", 8), ("", None)):
        with pytest.raises(E.ExprError) as e:
            E.parse(bad)
        assert e.value.pos == (where - 1 if where else None), bad
    assert E.rename(E.parse('"Rule 1" OR NOT ("Rule 1" AND B)'), "Rule 1", "Trend") == E.parse("Trend OR NOT (Trend AND B)")


def test_nested_conditions_hold_as_written():
    """(A OR B) AND NOT (X OR (S AND H)), bar by bar, against the same logic in Python."""
    conds = {k: above(v) for k, v in zip("ABXSH", (100, 101, 102, 103, 104), strict=True)}
    closes = [99, 100.5, 101.5, 102.5, 103.5, 104.5]
    s = series(closes)
    r = R.check({"conditions": list(conds.values()), "when": "(A OR B) AND !(C OR (D AND E))"}, {})
    tree = R.expand(E.parse(r["when"]), {}, r["conditions"], [])
    memo = {}
    for i, c in enumerate(closes):
        a, b, x, s_, h = (c > v for v in (100, 101, 102, 103, 104))
        assert R.holds(tree, s, i, memo) == ((a or b) and not (x or (s_ and h))), c
    assert sum(R.holds(tree, s, i, memo) for i in range(len(closes))) == 2


def test_rules_use_rules(tmp_path, monkeypatch):
    """Buy if ("Rule 1" AND NOT "Rule 3") OR Rule5: rules by name, nested, renamed everywhere, never in a loop."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    R.save("Rule 1", {"conditions": [above(100)]})
    R.save("Rule 3", {"conditions": [above(102)]})
    R.save("Rule5", {"conditions": [above(104)]})
    R.save("Middle", {"conditions": [], "when": '"Rule 1" AND NOT "Rule 3"'})
    n, st = S.save(None, {"buy": '("Rule 1" AND !"Rule 3") OR Rule5', "exit_long": "NOT Middle"})
    s = series([99, 101, 103, 105, 101])
    c = S.prepare(S.all_strategies()[n])
    longs = [x["bar"] for x in S.signals(c, s) if x["what"] == "long"]
    exits = [x["bar"] for x in S.signals(c, s) if x["what"] == "exit_long"]
    assert longs == [1, 3, 4] and exits == [0, 2, 3]
    with pytest.raises(ValueError, match='can\'t use itself: "Rule 1" uses "Middle" uses "Rule 1"'):
        R.save("Rule 1", {"conditions": [above(100)], "when": "A AND Middle"})
    with pytest.raises(ValueError, match='used by rule "Middle", strategy "Strategy 1"'):
        R.delete("Rule 3")
    R.rename("Rule 3", "Too high")
    assert R.all_rules()["Middle"]["when"] == '"Rule 1" AND NOT "Too high"'
    assert S.all_strategies()[n]["buy"] == '("Rule 1" AND NOT "Too high") OR Rule5'
    assert S.prepare(S.all_strategies()[n])["when"] == c["when"]           # the same rules, under the new name
    R.save("Unused", {"conditions": [above(1)]})
    R.delete("Unused")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("rules")
    synthetic.generate(d)
    return d


def test_study_lines_come_from_the_chart_code(demo, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    r = strategy(long=[{"a": CLOSE, "op": "crosses_above", "b": {"study": {"type": "vwap", "output": "vwap"}}}])
    s = R.day_series("QQQ-DEMO", DAY, 3, S.studies(r))
    vw = s[R._key(S.studies(r)[0])]
    assert len(vw) == len(s["bars"]) and sum(v is not None for v in vw) > 100
    R.check_no_repaint("QQQ-DEMO", DAY, 3, S.studies(r))               # VWAP never changes its past
    assert all(x["what"] == "long" for x in S.signals(r, s))


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
    r = strategy(long=[{"a": CLOSE, "op": "above", "b": {"study": {"type": "sma"}}}])
    with pytest.raises(ValueError, match="changes its past values"):
        R.check_no_repaint("QQQ-DEMO", DAY, 3, S.studies(r))


def test_saved_rules_are_named(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    n, item = R.save(None, {"conditions": [above(1)]})
    assert n == "Rule 1" and item["when"] == "A"
    n2, item2 = R.save("Rule 1", {"conditions": [above(1), above(2)], "when": "A OR B"})
    assert n2 == "Rule 1" and item2["id"] == item["id"] and item2["when"] == "A OR B"


def test_rule_and_strategy_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.server import app
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    c = TestClient(app, client=("192.168.1.20", 50000))
    r = c.post("/api/signal-rules", json={"rule": {"conditions": [above(1), above(2)], "when": "A OR NOT B"}}).json()
    assert r["name"] == "Rule 1" and r["rules"]["Rule 1"]["tree"] == {"or": [{"cond": "A"}, {"not": {"cond": "B"}}]}
    assert "crosses_above" in c.get("/api/signal-rules").json()["ops"]
    assert c.post("/api/signal-rules", json={"rule": {}}).status_code == 400
    x = c.post("/api/signal-expr", json={"text": "(a or b) and not c"}).json()
    assert x["text"] == "(a OR b) AND NOT c" and x["rules"] == ["a", "b", "c"]
    assert c.post("/api/signal-expr", json={"tree": x["tree"]}).json()["text"] == x["text"]
    bad = c.post("/api/signal-expr", json={"text": "A AND (B"})
    assert bad.status_code == 400 and bad.json()["detail"]["pos"] == 8
    s = c.post("/api/signal-strategies", json={"strategy": {"buy": '"Rule 1"', "qty": 7}}).json()
    assert s["name"] == "Strategy 1" and s["strategies"]["Strategy 1"]["trees"]["buy"] == {"rule": "Rule 1"}
    assert c.post("/api/signal-rules/Rule 1/rename", json={"to": "VWAP pullback"}).json()["strategies"]["Strategy 1"]["buy"] == '"VWAP pullback"'
    assert c.delete("/api/signal-rules/VWAP pullback").status_code == 409                 # the strategy uses it
    assert c.post("/api/signal-strategies/Strategy 1/rename", json={"to": "Pullbacks"}).json()["name"] == "Pullbacks"
    assert c.delete("/api/signal-strategies/Pullbacks").json()["strategies"] == {}
    assert c.delete("/api/signal-rules/VWAP pullback").json()["rules"] == {}


def test_rules_from_before_strategies_are_upgraded(tmp_path, monkeypatch):
    """Each old rule's long, short and exit conditions become rules; a strategy of its name trades on them."""
    import json

    from app import upgrade
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    (tmp_path / "user").mkdir()
    a, b = {"a": CLOSE, "op": "crosses_above", "b": {"value": 100}}, above(104)
    old = {"tf": 3, "long": [a, b], "short": [], "within": 3, "order": {"type": "market"}, "qty": 10,
           "exits": {"stop": 0.5, "exit_long": [above(110)], "exit_short": [], "reverse": True}, "hours": {"from": 570, "to": 950}}
    (tmp_path / "user" / "config.json").write_text(json.dumps({"paper_rules": {"Rule 1": {"id": "x", "rule": old}}}))
    assert upgrade.run() == ['config section "paper_rules" is now "signal_rules"',
                             'rule "Rule 1" from before strategies became rules Rule 1 long, Rule 1 exit long and strategy "Rule 1"']
    assert upgrade.run() == []
    rs, st = R.all_rules(), S.all_strategies()["Rule 1"]
    assert rs["Rule 1 long"]["when"] == "WITHIN 3 A AND WITHIN 3 B AND (A OR B)"
    assert st["buy"] == '"Rule 1 long"' and st["exit_long"] == '"Rule 1 exit long"' and st["short"] == ""
    assert st["exits"] == {"stop": 0.5, "reverse": True} and st["qty"] == 10
    s = series([99, 101, 102, 105, 106])                                   # the same signals as the old rule gave
    assert [x["minute"] for x in S.signals(S.prepare(st), s) if x["what"] == "long"] == [574]


# ---------------------------------------------------------------- levels (#65): opening range high, PH, IB high...
def level_rule(study, output, op="crosses_above", **params):
    return strategy(long=[{"a": CLOSE, "op": op, "b": {"study": {"type": study, "params": params, "output": output}}}])


def level_spec(r):
    return S.studies(r)[0]


def test_every_level_a_rule_offers_is_one_the_study_draws(demo, monkeypatch):
    """The names in the rule form match the levels the charts draw (with every part of the study switched on)."""
    from app import engine
    monkeypatch.setattr(store, "DATA_DIR", demo)
    ctx = engine.DayContext("QQQ-DEMO", DAY, 3, None)
    offered = 0
    for t, spec in studies_base.REGISTRY.items():
        if spec["levels"] is None:
            continue
        for name, plot, _ in spec["levels"]:
            params = studies_base.rule_params(t, "level:" + name, studies_base.effective_params(t, {}))   # as a rule runs it
            drawn = {studies_base.level_name(lv["label"]) for lv in studies_base.run_study(ctx, t, params).get("levels") or []}
            assert name in drawn, f"{t}: '{name}' isn't one of {sorted(drawn)}"
            assert plot in [p["id"] for p in spec["plots"]], (t, plot)
            offered += 1
    assert offered >= 30
    cat = {s["type"]: s for s in studies_base.catalog(user=False)}
    assert [x["id"] for x in cat["session_levels"]["lines"]][:2] == ["level:OR high", "level:OR low"]
    assert cat["events"]["lines"] == [] and cat["vwap"]["lines"][0]["id"] == "vwap"     # lines as before
    assert cat["session_levels"]["rule_settings"] == ["or_minutes"] and cat["vwap"]["rule_settings"] is None


def test_the_opening_range_high_is_read_once_its_complete_and_never_ahead(demo, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", demo)
    from app.backtesting import orders
    r = level_rule("session_levels", "level:OR high", or_minutes="15")
    s = R.day_series("QQQ-DEMO", DAY, 3, S.studies(r))
    orh = s[R._key(level_spec(r))]
    first = next(i for i, v in enumerate(orh) if v is not None)
    assert s["bars"][first]["start"] == 9 * 60 + 45                       # the first bar after the 15-minute range
    want = max(b["high"] for b in orders.bars("QQQ-DEMO", DAY) if 570 <= b["minute"] < 585)
    assert orh[first] == pytest.approx(want) and all(v == orh[first] for v in orh[first:] if v is not None)
    R.check_no_repaint("QQQ-DEMO", DAY, 3, S.studies(r))
    for x in S.signals(r, s):                                             # each long: the close above the range, not before
        i = x["bar"]
        assert s["bars"][i]["close"] > orh[i] and (orh[i - 1] is None or s["bars"][i - 1]["close"] <= orh[i - 1])


def test_a_level_is_the_one_the_bar_traded_against(demo, monkeypatch):
    """HOD read at a bar is the high before it, so "close crosses above HOD" can happen (the bar's own high would
    always be above its close)."""
    monkeypatch.setattr(store, "DATA_DIR", demo)
    r = level_rule("session_levels", "level:HOD")
    s = R.day_series("QQQ-DEMO", DAY, 3, S.studies(r))
    hod = s[R._key(level_spec(r))]
    for i in range(len(s["bars"])):
        if hod[i] is not None:
            assert hod[i] == pytest.approx(max(x["high"] for x in s["bars"][:i] if x["start"] >= 570))
    assert all(v is None for b, v in zip(s["bars"], hod, strict=True) if not 570 <= b["start"] < 960)


def test_a_level_is_drawn_for_the_rule_whatever_the_charts_show():
    """The study defaults may hide a level on the charts (or show only near ones): a rule reading it still gets it."""
    p = level_spec(level_rule("session_levels", "level:POC", profile=False, near_only=True))["params"]
    assert p["profile"] is True and p["near_only"] is False and p["or_minutes"] == "15"


def test_level_rules_saved_before_levels_were_named_still_work():
    r = level_rule("session_levels", "orl")                               # the plot id, as saved before #65
    assert level_spec(r)["output"] == "level:OR high"
    assert level_spec(level_rule("prior_day", ""))["output"] == "level:PH"


def test_a_level_rule_backtests(demo, monkeypatch):
    from app.backtesting import backtest
    monkeypatch.setattr(store, "DATA_DIR", demo)
    r = strategy(long=[{"a": CLOSE, "op": "crosses_above", "b": {"study": {"type": "session_levels", "output": "level:OR high"}}}],
                 short=[{"a": CLOSE, "op": "crosses_below", "b": {"study": {"type": "session_levels", "output": "level:OR low"}}}],
                 qty=10, exits={"stop": 0.5, "target": 1.0})
    days = store.list_days("QQQ-DEMO")[:4]
    rep = backtest.run(r, "QQQ-DEMO", days, 100_000, backtest.engine.DEFAULT_SETTINGS, baseline_runs=1)
    assert rep["stats"]["trades"] >= 1 and all(t["entry_minute"] > 585 for t in rep["trades"])


# ---------------------------------------------------------------- direction: rising, falling, bars ago (#73)
def test_rising_falling_and_values_bars_ago():
    """VZO > -40 and current > previous, the way a rule says it: "is above -40" and "is rising"; "is above itself
    1 bar ago" says the same; "over N bars" compares with N bars before."""
    s = series([99, 101, 100.5, 102, 101, 103, 104])
    rising = R.condition({"a": CLOSE, "op": "rising"}, "A")
    assert rising == {"a": CLOSE, "op": "rising", "bars": 1}
    assert [R._holds(rising, s, i) for i in range(7)] == [False, True, False, True, False, True, True]
    falling = R.condition({"a": CLOSE, "op": "falling"}, "A")
    assert [R._holds(falling, s, i) for i in range(7)] == [False, False, True, False, True, False, False]
    vs_prev = R.condition({"a": CLOSE, "op": "above", "b": {**CLOSE, "ago": 1}}, "A")
    assert [R._holds(vs_prev, s, i) for i in range(7)] == [R._holds(rising, s, i) for i in range(7)]
    over3 = R.condition({"a": CLOSE, "op": "rising", "bars": 3}, "A")
    assert [R._holds(over3, s, i) for i in range(7)] == [False, False, False, True, False, True, True]
    up = R.check({"conditions": [above(100), {"a": CLOSE, "op": "rising"}], "when": "A AND B"}, {})
    assert [x["bar"] for x in S.signals(S.prepare({"buy": "Up"}, {"Up": up}), s)] == [1, 3, 5, 6]
    for bad, why in (({"a": {"value": 1}, "op": "rising"}, "never rising or falling"),
                     ({"a": CLOSE, "op": "rising", "bars": 0}, "compares with 1 to 50 bars back"),
                     ({"a": CLOSE, "op": "above", "b": {"value": 1, "ago": 2}}, "no value bars ago"),
                     ({"a": {**CLOSE, "ago": 51}, "op": "above", "b": {"value": 1}}, "0 to 50 bars back")):
        with pytest.raises(ValueError, match=why):
            R.condition(bad, "A")
    assert R.condition({"a": {**CLOSE, "ago": 0}, "op": "above", "b": {"value": 1}}, "A")["a"] == CLOSE   # 0: now


def test_a_studys_direction_uses_its_own_line(demo, monkeypatch):
    """VZO is rising: its value at each bar against the bar before, from the same line the chart draws."""
    monkeypatch.setattr(store, "DATA_DIR", demo)
    vzo = {"study": {"type": "vzo", "output": "vzo"}}
    r = strategy(long=[{"a": vzo, "op": "above", "b": {"value": -40}}, {"a": vzo, "op": "rising"}])
    s = R.day_series("QQQ-DEMO", DAY, 3, S.studies(r))
    line = s[R._key(S.studies(r)[0])]
    want = [i for i in range(1, len(line)) if line[i] is not None and line[i - 1] is not None and line[i] > -40 and line[i] > line[i - 1]]
    assert [x["bar"] for x in S.signals(r, s)] == want and want
