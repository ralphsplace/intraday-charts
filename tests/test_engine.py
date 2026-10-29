import numpy as np
import pandas as pd
import pytest

from app import engine, store, studies

ET = "America/New_York"


def make_day(day, closes_by_min, vol=1000.0):
    """Bars at the given minute->close map; open = previous close, high/low +/-0.05."""
    rows, prev = [], None
    for m, c in sorted(closes_by_min.items()):
        o = c if prev is None else prev
        rows.append({"time": pd.Timestamp(day, tz=ET) + pd.Timedelta(minutes=m), "open": o,
                     "high": max(o, c) + 0.05, "low": min(o, c) - 0.05, "close": c, "volume": vol})
        prev = c
    return pd.DataFrame(rows)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return tmp_path


def flat_day(day, price, hi=None, lo=None):
    closes = {m: price for m in range(570, 960)}
    if hi:
        closes[600] = hi
    if lo:
        closes[700] = lo
    return make_day(day, closes)


def view(symbol, day, cursor, *types, tf=5, params=None):
    lay = [{"uid": t, "type": t, "params": (params or {}).get(t, {})} for t in types]
    return engine.build_view(symbol, day, tf=tf, cursor=cursor, studies=lay)


def test_aggregate_aligns_to_session_open_and_keeps_wall_clock():
    df = make_day("2026-10-16", {m: 100 + i * 0.01 for i, m in enumerate(range(565, 600))})
    agg = engine.aggregate(df, 15)
    assert list(agg["bucket"]) == [555, 570, 585]
    assert agg["time"].iloc[1].strftime("%H:%M") == "09:30"          # timezone kept (regression)
    assert engine.chart_time(agg["time"].iloc[1]) % 86400 == 9 * 3600 + 30 * 60
    src = df[(df["time"].dt.hour * 60 + df["time"].dt.minute).between(570, 584)]
    assert agg[agg["bucket"] == 570].iloc[0]["volume"] == src["volume"].sum()


def test_aggregate_across_days():
    a = make_day("2026-10-15", {570: 1.0, 571: 2.0})
    b = make_day("2026-10-16", {570: 3.0})
    agg = engine.aggregate(pd.concat([a, b], ignore_index=True), 5)
    assert len(agg) == 2 and list(agg["close"]) == [2.0, 3.0]


def test_vwap_matches_hand_calculation():
    df = make_day("2026-10-16", {570: 10.0, 571: 20.0})
    df["volume"] = [1.0, 3.0]
    vw = engine.vwap_frame(df)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    assert vw["vwap"].iloc[-1] == pytest.approx((tp[0] * 1 + tp[1] * 3) / 4)
    assert vw["time"].iloc[0].tz is not None


def test_atr_simple_average_of_true_range():
    daily = pd.DataFrame({"high": [10, 12, 11], "low": [9, 10, 8], "close": [9.5, 11, 9]})
    atr, n = engine.atr_from_daily(daily)
    assert n == 3 and atr == pytest.approx((1 + 2.5 + 3) / 3)


def test_replay_never_sees_future_bars(cache):
    store.write_day("TST", "2026-10-15", flat_day("2026-10-15", 100, hi=101, lo=99))
    day = make_day("2026-10-16", {m: 98.0 for m in range(240, 960)})
    store.write_day("TST", "2026-10-16", day)
    types = ("prior_day", "sr_ladder", "session_levels", "events", "ema", "rsi", "vwap", "macd")
    before = view("TST", "2026-10-16", 11 * 60, *types)
    later = day.copy()
    mask = (later["time"].dt.hour * 60 + later["time"].dt.minute) >= 11 * 60
    later.loc[mask, ["open", "high", "low", "close"]] = 150.0
    store.write_day("TST", "2026-10-16", later)
    after = view("TST", "2026-10-16", 11 * 60, *types)
    assert before["bars"] == after["bars"]
    assert before["studies"] == after["studies"]


def test_level_flips_after_two_closes_beyond(cache):
    store.write_day("TST", "2026-10-15", flat_day("2026-10-15", 100, hi=102, lo=99))   # PL 98.95
    closes = {m: 99.5 for m in range(570, 960)}
    for m in range(600, 960):
        closes[m] = 98.0
    store.write_day("TST", "2026-10-16", make_day("2026-10-16", closes))
    pl = lambda v: next(x for x in v["studies"]["prior_day"]["levels"] if x["label"].startswith("PL"))
    assert not pl(view("TST", "2026-10-16", 600, "prior_day"))["flipped"]
    late = pl(view("TST", "2026-10-16", 620, "prior_day"))
    assert late["flipped"] and late["role"] == "resistance" and late["label"] == "PL (flipped)"


def test_opening_range_locks_and_premarket_levels(cache):
    store.write_day("TST", "2026-10-15", flat_day("2026-10-15", 100))
    closes = {m: 100.0 for m in range(240, 960)}
    closes[300], closes[575], closes[700] = 103.0, 101.0, 105.0
    store.write_day("TST", "2026-10-16", make_day("2026-10-16", closes))
    r = view("TST", "2026-10-16", 800, "session_levels")["studies"]["session_levels"]
    assert r["box"]["complete"] and r["box"]["high"] == pytest.approx(101.05)
    labels = {x["label"]: x for x in r["levels"]}
    assert labels["PM high"]["price"] == pytest.approx(103.05)
    building = view("TST", "2026-10-16", 578, "session_levels")["studies"]["session_levels"]
    assert not building["box"]["complete"]
    assert any(x["label"] == "OR high (building)" for x in building["levels"])


def test_indicator_warmup_uses_prior_days(cache):
    for d in ("2026-10-13", "2026-10-14", "2026-10-15"):
        store.write_day("TST", d, flat_day(d, 100))
    store.write_day("TST", "2026-10-16", flat_day("2026-10-16", 100))
    v = view("TST", "2026-10-16", 600, "sma", params={"sma": {"length": 50}})
    pts = v["studies"]["sma"]["lines"][0]["data"]
    assert len(pts) == len(v["bars"])          # defined from today's first bar thanks to warm-up


def test_every_study_runs_on_demo_data(demo):
    types = list(studies.REGISTRY)
    for cursor in (300, 575, 640, 900):        # premarket, building OR, morning, afternoon
        for tf in (1, 3, 5, 15):
            v = view("QQQ-DEMO", "2026-10-16", cursor, *types, tf=tf)
            bad = {k: r.get("error") for k, r in v["studies"].items() if not r["ok"]}
            assert not bad, (cursor, tf, bad)


def test_params_are_coerced_and_clamped():
    spec = studies.REGISTRY["rsi"]
    p = studies.coerce(spec, {"length": "9999", "source": "nonsense", "overbought": 65})
    assert p["length"] == 100 and p["source"] == "close" and p["overbought"] == 65


def test_unknown_study_reports_error(demo):
    r = view("QQQ-DEMO", "2026-10-16", 640, "nope")["studies"]["nope"]
    assert not r["ok"] and "Unknown" in r["error"]


def test_ma_cloud_daily_mode_uses_daily_history_file(demo):
    r = view("QQQ-DEMO", "2026-10-16", 640, "ma_cloud",
             params={"ma_cloud": {"timeframe": "Daily", "type1": "SMA", "type2": "SMA", "len1": 50, "len2": 200}})["studies"]["ma_cloud"]
    assert [x["label"] for x in r["levels"]] == ["DSMA 50", "DSMA 200"]


def levels_of(cursor, *types, params=None):
    v = view("QQQ-DEMO", "2026-10-16", cursor, *types, params=params)
    out = {}
    for t in types:
        for x in v["studies"][t]["levels"]:
            out[x["label"].split(" (")[0]] = x
    return out


def test_prior_day_lines_and_ladder_ordering(demo):
    for method in ("Fibonacci extension (1.272 / 1.618)", "ATR extension (0.5 / 1.0 ATR)"):
        for cursor in (500, 640, 900):
            lv = levels_of(cursor, "prior_day", "sr_ladder", params={"sr_ladder": {"method": method}})
            assert {"PH", "PL", "PC", "PO", "Pivot", "R1", "R2", "S1", "S2"} <= set(lv)
            assert lv["R2"]["price"] > lv["R1"]["price"] > lv["PH"]["price"], (method, cursor)
            assert lv["S2"]["price"] < lv["S1"]["price"] < lv["PL"]["price"], (method, cursor)


def test_dynamic_ladder_moves_past_new_lows(demo):
    lv = levels_of(900, "prior_day", "sr_ladder", "session_levels")
    assert lv["S1"]["price"] < lv["LOD"]["price"] < lv["PL"]["price"]
    assert lv["S1"]["label"] == "S1 (moving)"
    static = levels_of(900, "sr_ladder", params={"sr_ladder": {"dynamic": False}})
    assert static["S1"]["price"] > lv["S1"]["price"]


def test_level_style_settings_apply(demo):
    lv = levels_of(640, "prior_day", params={"prior_day": {"ph_color": "#ff0000", "ph_style": "dashed", "ph_width": 3}})
    assert (lv["PH"]["color"], lv["PH"]["style"], lv["PH"]["width"]) == ("#ff0000", "dashed", 3)


def test_line_style_settings_apply(demo):
    p = {"vwap": {"vwap_color": "#ff0000", "vwap_style": "dashed", "vwap_width": 3, "band1_color": "#00ff00"}}
    r = view("QQQ-DEMO", "2026-10-16", 640, "vwap", params=p)["studies"]["vwap"]
    main = next(x for x in r["lines"] if x["id"] == "vwap")
    assert (main["color"], main["style"], main["width"]) == ("#ff0000", "dashed", 3)
    assert all(x["color"] == "#00ff00" for x in r["lines"] if x["id"].startswith("band1_"))
    rsi = view("QQQ-DEMO", "2026-10-16", 640, "rsi", params={"rsi": {"ob_color": "#123456", "ob_width": 2}})
    ob = next(h for h in rsi["studies"]["rsi"]["hlines"] if h["plot"] == "ob")
    mid = next(h for h in rsi["studies"]["rsi"]["hlines"] if h["plot"] == "mid")
    assert (ob["color"], ob["width"]) == ("#123456", 2) and mid["color"] != "#123456"


def test_every_line_study_has_style_settings():
    for t, spec in studies.REGISTRY.items():
        keys = {p["key"] for p in spec["params"]}
        for pl in spec["plots"]:
            assert {f"{pl['id']}_color", f"{pl['id']}_style", f"{pl['id']}_width"} <= keys, t


def test_every_drawn_line_follows_its_style_settings(demo):
    """Turn every option on, set every plot to the same unusual style, and check nothing drawn ignores it."""
    for t, spec in studies.REGISTRY.items():
        raw = {p["key"]: True for p in spec["params"] if p["type"] == "bool"}
        for pl in spec["plots"]:
            raw.update({f"{pl['id']}_color": "#abcdef", f"{pl['id']}_style": "large_dashed", f"{pl['id']}_width": 3})
        for cursor in (640, 900):
            r = view("QQQ-DEMO", "2026-10-16", cursor, t, params={t: raw})["studies"][t]
            assert r["ok"], (t, r.get("error"))
            items = [*r.get("lines", []), *r.get("hlines", []), *r.get("verticals", []), *r.get("levels", [])]
            if r.get("box"):
                items.append(r["box"])
            for it in items:
                assert (it["color"], it["style"], it["width"]) == ("#abcdef", "large_dashed", 3), (t, it.get("id") or it.get("label"))


def test_atr_ladder_matches_tos_screenshot():
    """Prior close 709.80 and ATR 10.55 gave these levels on the user's thinkorswim chart (Oct 19)."""
    lad = studies.atr_ladder(709.80, 10.55, 23.6)
    expect = {0.236: 712.29, -0.236: 707.31, 1.0: 720.35, -1.0: 699.25, 0.382: 713.83, 0.5: 715.08,
              0.618: 716.32, 1.236: 722.84, 1.382: 724.38, 1.5: 725.62, 1.618: 726.87, 1.786: 728.64, 2.0: 730.90}
    for r, price in expect.items():
        assert round(lad[r], 2) == pytest.approx(price, abs=0.01), r


def test_new_studies_run_on_one_and_several_days(demo):
    for days in (1, 3, 5):
        lay = [{"uid": t, "type": t, "params": {}} for t in ("saty_atr", "volume_profile", "ma_cloud", "vwap")]
        v = engine.build_view("QQQ-DEMO", "2026-10-16", tf=3, cursor=700, studies=lay, days=days)
        assert len(v["shown_days"]) == days and v["shown_days"][-1] == "2026-10-16"
        times = [b["time"] for b in v["bars"]]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert all(r["ok"] for r in v["studies"].values()), {k: r.get("error") for k, r in v["studies"].items()}
        shown = set(times)
        for r in v["studies"].values():
            for line in r.get("lines", []):
                assert {pt["time"] for pt in line["data"]} <= shown
            for m in r.get("markers", []):
                assert m["time"] in shown


def test_vwap_resets_each_shown_day(demo):
    v = engine.build_view("QQQ-DEMO", "2026-10-16", tf=5, cursor=700, studies=[{"uid": "v", "type": "vwap"}], days=2)
    first_rth = {}
    for b in v["bars"]:
        if b["session"] == "rth":
            first_rth.setdefault(b["day"], b)
    pts = {p["time"]: p["value"] for p in v["studies"]["v"]["lines"][0]["data"]}
    for b in first_rth.values():   # VWAP at each day's first bar sits on that bar, not yesterday's average
        assert b["low"] - 0.01 <= pts[b["time"]] <= b["high"] + 0.01


def test_volume_profile_value_area(demo):
    r = view("QQQ-DEMO", "2026-10-16", 900, "volume_profile", params={"volume_profile": {"va_pct": 70}})["studies"]["volume_profile"]
    bins = r["profile"]["bins"]
    total = sum(b["vol"] for b in bins)
    in_va = sum(b["vol"] for b in bins if b["va"])
    assert 0.70 <= in_va / total < 0.9
    lv = {x["label"]: x["price"] for x in r["levels"]}
    assert lv["VAL"] < lv["POC"] < lv["VAH"]


def test_signal_studies_are_gone():
    for gone in ("signals", "whale", "sde", "premarket_scan"):   # signal studies, and the premarket scan
        assert gone not in studies.REGISTRY, gone
    assert not [t for t in studies.REGISTRY if "arrow" in str(studies.REGISTRY[t]["params"]).lower()]
    assert not hasattr(studies, "PRESETS")                         # no preset study sets


def test_vzo_is_an_indicator_only(demo):
    spec = studies.REGISTRY["vzo"]
    assert spec["category"] == "Oscillators" and spec["pane"] == "own"
    assert not [p["key"] for p in spec["params"] if "arrow" in p["key"] or "exit" in p["key"]]
    v = view("QQQ-DEMO", "2026-10-16", 640, "vzo")["studies"]["vzo"]
    assert v["ok"] and not v.get("markers")
    data = v["lines"][0]["data"]
    assert data and all(-100 <= pt["value"] <= 100 for pt in data)
    assert [h["price"] for h in v["hlines"]] == [60, 40, 0, -40, -60]


def test_pfe_study(demo):
    spec = studies.REGISTRY["pfe"]
    assert spec["category"] == "Oscillators" and spec["pane"] == "own"
    v = view("QQQ-DEMO", "2026-10-16", 640, "pfe")["studies"]["pfe"]
    assert v["ok"] and v["lines"][0]["data"]
    assert all(-100 <= pt["value"] <= 100 for pt in v["lines"][0]["data"])
    assert [h["price"] for h in v["hlines"]] == [50, 0, -50]


def test_dmi_stochastic_study_draws_lines_only(demo):
    spec = studies.REGISTRY["dmi_stoch"]
    assert spec["category"] == "Oscillators" and spec["pane"] == "own"
    v = view("QQQ-DEMO", "2026-10-16", 640, "dmi_stoch")["studies"]["dmi_stoch"]
    assert v["ok"] and v["lines"][0]["data"] and not v.get("markers")              # no crossing arrows
    assert all(0 <= pt["value"] <= 100 for pt in v["lines"][0]["data"])
    assert [h["price"] for h in v["hlines"]] == [90, 10]


def test_studies_package_has_one_module_per_family():
    import inspect
    family = {"overlays": "Overlays", "oscillators": "Oscillators", "levels": "Levels",
              "internals": "Market internals", "volume": "Volume", "profiles": "Profiles"}
    for t, spec in studies.REGISTRY.items():
        mod = inspect.getmodule(spec["compute"]).__name__.rsplit(".", 1)[-1]
        assert family.get(mod) == spec["category"], (t, mod, spec["category"])


def test_study_setting_keys_are_unique():
    for t, spec in studies.REGISTRY.items():
        keys = [p["key"] for p in spec["params"]]
        assert len(keys) == len(set(keys)), t


def test_ma_cloud_fill_follows_which_line_is_on_top(demo):
    p = {"ma_cloud": {"up_color": "#00ff00", "up_transp": 60, "down_color": "#ff0000", "down_transp": 20,
                      "type1": "EMA", "len1": 5, "type2": "SMA", "len2": 20}}
    r = view("QQQ-DEMO", "2026-10-16", 900, "ma_cloud", params=p)["studies"]["ma_cloud"]
    assert r["cloud"]["up"] == "rgba(0,255,0,0.4)" and r["cloud"]["down"] == "rgba(255,0,0,0.8)"
    lines = {l["id"]: {pt["time"]: pt["value"] for pt in l["data"]} for l in r["lines"]}
    pts = r["cloud"]["points"]
    assert len(pts) > 50
    for pt in pts:   # cloud edges are exactly the two drawn lines
        assert pt["a"] == pytest.approx(lines["ma1"][pt["time"]]) and pt["b"] == pytest.approx(lines["ma2"][pt["time"]])
    assert any(pt["a"] > pt["b"] for pt in pts) and any(pt["a"] < pt["b"] for pt in pts)   # crosses on the demo day


def test_line_transparency_setting(demo):
    r = view("QQQ-DEMO", "2026-10-16", 640, "ema", params={"ema": {"ema_color": "#102030", "ema_transp": 50}})
    assert r["studies"]["ema"]["lines"][0]["color"] == "rgba(16,32,48,0.5)"
    for t, spec in studies.REGISTRY.items():
        keys = {p["key"] for p in spec["params"]}
        for pl in spec["plots"]:
            assert f"{pl['id']}_transp" in keys, t


def test_unknown_study_is_reported_not_raised(demo):
    r = view("QQQ-DEMO", "2026-10-16", 640, "no_such_study")["studies"]["no_such_study"]
    assert not r["ok"] and "Unknown study" in r["error"]


def test_backtest_vzo_tos_entries_are_vzo_crossings(demo):
    import backtest_signals as bt
    bars = bt.load_bars("QQQ-DEMO", 3, "2026-10-16", "2026-10-16")
    entry, _, _ = bt.signals(bars, "vzo_tos")
    v = bt.ind.vzo(bars, 20).to_numpy()
    for i in np.nonzero(entry)[0]:
        assert (v[i - 1] < 5 <= v[i]) if entry[i] > 0 else (v[i - 1] > -5 >= v[i])


def test_whale_line_turns_only_after_clearing_the_carried_level():
    import signals as sg
    # falls for 30 bars, then rises 0.30 a bar: the line must stay flat after CCI turns, then turn up
    c = np.r_[np.linspace(110, 100, 30), np.linspace(100.3, 109, 30)]
    h, l = c + 0.1, c - 0.1
    cci = sg.cci_close(c, 10)
    line = sg.cci_atr_line(h, l, c, cci, 2, 1.0)
    flip = 15 + int(np.argmax(cci[15:] >= 0))       # first bar CCI is back above 0 after the fall
    turns = sg.line_turns(line)
    turn = flip + int(np.argmax(turns[flip:]))       # first bar after that the line moves up
    assert turn > flip
    assert np.allclose(line[flip:turn], line[flip - 1])          # carried over, flat
    assert line[turn] > line[turn - 1] and line[turn] < l[turn]  # turns once low - ATR clears it


def test_tick_studies_run_and_count_extremes(demo):
    v = engine.build_view("QQQ-DEMO", "2026-10-16", tf=3, cursor=900, days=2,
                          studies=[{"uid": t, "type": t} for t in ("tick", "cum_tick")])
    r = v["studies"]
    assert all(x["ok"] for x in r.values()), r
    t = store.read_day("TICK-NYSE", "2026-10-16")
    m = t["time"].dt.hour * 60 + t["time"].dt.minute
    t = t[(m >= 570) & (m < 900)]
    assert r["tick"]["note"].startswith(f"today +1000: {int((t['high'] >= 1000).sum())}, -1000: {int((t['low'] <= -1000).sum())}")
    cum = r["cum_tick"]["lines"][0]["data"]
    assert cum and all(abs(p["value"]) < 1e7 for p in cum)
    first_today = [p for p in cum if p["time"] >= engine.chart_time(pd.Timestamp("2026-10-16 09:30", tz=ET))][0]
    t930 = t.iloc[:3]
    assert first_today["value"] == round(float(((t930["high"] + t930["low"] + t930["close"]) / 3).sum()), 0)
    missing = engine.build_view("SPY-DEMO", "2026-10-16", tf=3, cursor=900,
                                studies=[{"uid": "x", "type": "tick", "params": {"symbol": "TICK-NDX"}}])["studies"]["x"]
    assert missing["ok"] and "no TICK-NDX bars" in missing["note"]


def test_vzo_exit_rule_plus_40_descending_and_macd_not_above_signal():
    import signals as sg
    from app import indicators as ind
    n = 60
    close = np.r_[np.linspace(100, 104, 40), np.linspace(104, 101, 20)]   # MACD below signal late in the run
    line, sig, _ = ind.macd(pd.Series(close), 12, 26, 9)
    below = next(i for i in range(41, n) if line[i] < sig[i])             # first bar MACD is under its signal
    above = 37                                                            # a bar where MACD is above signal
    assert line[above] > sig[above]
    v = np.full(n, 20.0)
    v[above - 1], v[above] = 50.0, 45.0                                   # descending from above +40 ...
    v[below - 1], v[below] = 50.0, 45.0
    x = sg.vzo_macd_exits(v, close)
    assert list(np.flatnonzero(x)) == [below]                             # ... exits only where MACD isn't above
    v2 = np.full(n, 20.0)
    v2[below - 1], v2[below] = -30.0, -35.0                               # descending below 40: never an exit
    assert not sg.vzo_macd_exits(v2, close).any()
    v3 = np.full(n, 20.0)
    v3[below - 1:below + 3] = [60.0, 55.0, 50.0, 45.0]                    # several bars in a row: one signal
    assert list(np.flatnonzero(sg.vzo_macd_exits(v3, close))) == [below]


def test_backtest_vzo_tos_x_uses_the_exit_rule(demo):
    import backtest_signals as bt
    bars = bt.load_bars("QQQ-DEMO", 3, None, None)
    e1, xl, xs = bt.signals(bars, "vzo_tos_x")
    e0, _, _ = bt.signals(bars, "vzo_tos")
    assert (e1 == e0).all() and xl.any() and not xs.any()
    a = bt.Arrays(bars)
    t0, t1 = bt.simulate(bars, a, "vzo_tos", 0.30), bt.simulate(bars, a, "vzo_tos_x", 0.30)
    assert len(t1) >= len(t0) and t1["planned_bars"].mean() <= t0["planned_bars"].mean()


def test_volume_profile_row_modes(demo):
    def vp(**params):
        return engine.build_view("QQQ-DEMO", "2026-10-16", tf=3, cursor=900,
                                 studies=[{"uid": "v", "type": "volume_profile", "params": params}])["studies"]["v"]
    rows = vp()
    assert len(rows["profile"]["bins"]) == 60
    t1 = vp(row_mode="Tick size")
    b = t1["profile"]["bins"]
    assert all(abs((x["hi"] - x["lo"]) - 0.01) < 1e-6 for x in b)               # one cent per row
    for lv in t1["levels"]:                                                      # POC / VAH / VAL on whole cents
        assert abs(lv["price"] * 100 - round(lv["price"] * 100)) < 1e-6
    vah, val = [lv["price"] for lv in t1["levels"][1:]]
    assert val <= t1["levels"][0]["price"] <= vah
    total = sum(x["vol"] for x in b)
    va = sum(x["vol"] for x in b if x["va"])
    assert 0.69 <= va / total <= 0.75                                            # value area ~70%
    assert abs(total - sum(x["vol"] for x in rows["profile"]["bins"])) / total < 1e-3   # same volume either way
    t5 = vp(row_mode="Tick size", ticks=5)
    assert all(abs((x["hi"] - x["lo"]) - 0.05) < 1e-6 for x in t5["profile"]["bins"])
    c = vp(row_mode="Custom price per row", row_price=0.25)
    assert all(abs((x["hi"] - x["lo"]) - 0.25) < 1e-6 for x in c["profile"]["bins"])
    wide = vp(row_mode="Tick size", tick_size=0.0001)                           # far too many rows: widened
    assert len(wide["profile"]["bins"]) <= studies.VP_MAX_ROWS and "widened" in wide["note"]
