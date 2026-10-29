"""The two pages (a chart dashboard and /dashboards), driven in Chromium against the real server on SYNTHETIC bars.
Every test also fails on any JavaScript error (see the `tab` fixture)."""
import json


LAST = "2026-10-16"          # last synthetic day


def app_state(page, expr):
    return page.evaluate(f"(() => {{ const a = window.__chartApp; return {expr}; }})()")


def wait_state(page, expr, timeout=15000):
    """Wait until the expression is true (slower machines, e.g. GitHub's runners, need more than a fixed pause)."""
    page.wait_for_function(f"(() => {{ const a = window.__chartApp; return {expr}; }})()", timeout=timeout)


# ---------------------------------------------------------------- chart grid (QQQs)
def test_default_is_one_qqq_chart_with_no_studies(tab):
    p = tab.goto("/QQQs", 2500)
    assert p.title().startswith("QQQs")
    assert p.locator("#layout").input_value() == "1x1" and p.locator(".panel:visible").count() == 1
    assert p.locator("input.sym").first.input_value() == "QQQ"
    assert app_state(p, "[a.panels[0].tf, a.panels[0].days, a.panels[0].price.type, a.panels[0].studies.length]") == [3, 1, "candles", 0]
    assert p.locator("#day").input_value() == LAST
    assert app_state(p, "a.panels[0].view.bars.length > 100")
    assert p.locator(".panel .leg").count() == 0                                 # nothing drawn but the price
    assert p.locator(".brand").first.inner_text() == "RP"
    assert p.locator("a[href*='tradingview']").count() == 0          # the library's logo is off


SERIES = "a.panels[0].chart.panes()[0].getSeries()"
PRICE_SERIES = SERIES + ".filter((s) => s !== a.panels[0].candles)"


def open_price_settings(p):
    p.locator(".panel").first.locator(".pricebtn").click()
    p.wait_for_selector("#settingsDlg:not([hidden])")


def apply_price_settings(p, values):
    for key, v in values.items():
        box = p.locator(f"#settingsForm [data-key='{key}']")
        if isinstance(v, bool):
            box.set_checked(v)
        elif box.evaluate("(e) => e.tagName") == "SELECT":
            box.select_option(v)
        else:
            box.fill(str(v))
    p.locator("#settingsApply").click()
    p.wait_for_timeout(400)


def test_price_types(tab):
    p = tab.goto("/QQQs", 2000)
    assert p.locator(".pstyle option").all_inner_texts() == ["Candles", "Heikin-Ashi", "OHLC bars", "Line", "Area",
                                                             "Current price line"]
    bars = app_state(p, "a.panels[0].view.bars.length")
    real = app_state(p, "a.panels[0].view.bars.slice(5, 8).map((b) => [b.open, b.close])")
    for t, kind in (("heikin", "Custom"), ("bars", "Custom"), ("line", "Line"), ("area", "Area"), ("candles", "Custom")):
        p.select_option(".pstyle", t)
        p.wait_for_timeout(500)
        assert app_state(p, "a.panels[0].price.type") == t
        # exactly one series draws the price, next to the invisible anchor; it has every bar
        assert app_state(p, PRICE_SERIES + ".map((s) => s.seriesType())") == [kind], t
        assert app_state(p, PRICE_SERIES + "[0].data().length") == bars, t
        if t == "heikin":   # Heikin-Ashi bars are averages, not the real prices
            assert app_state(p, PRICE_SERIES + "[0].data().slice(5, 8).map((b) => [b.open, b.close])") != real
    assert app_state(p, "a.panels[0].candles.options().upColor") == "rgba(0,0,0,0)"   # the anchor is never drawn
    p.select_option(".pstyle", "line")
    p.wait_for_timeout(500)
    p.reload()
    p.wait_for_timeout(2000)                                          # kept in this browser
    assert p.locator(".pstyle").input_value() == "line" and app_state(p, PRICE_SERIES + "[0].seriesType()") == "Line"


def test_price_type_settings(tab):
    p = tab.goto("/QQQs", 2000)
    open_price_settings(p)
    assert p.locator("#settingsTitle").inner_text() == "Price: Candles"
    keys = p.evaluate("[...document.querySelectorAll('#settingsForm [data-key]')].map((e) => e.dataset.key)")
    assert {"up_color", "down_color", "color_by", "up_fill", "down_fill", "outline_width", "wick_width", "body_pct"} <= set(keys)
    # hollow candles are a setting of Candles, not a separate type
    apply_price_settings(p, {"up_fill": False, "color_by": "Previous close", "wick_width": 2, "up_color": "#112233"})
    assert app_state(p, "a.panels[0].price") == {"type": "candles", "params": {**app_state(p, "window.__priceTypes.defaults('candles')"),
                                                 "up_fill": False, "color_by": "Previous close", "wick_width": 2, "up_color": "#112233"}}
    assert app_state(p, PRICE_SERIES + ".length") == 1
    open_price_settings(p)
    p.locator("#settingsDefaults").click()
    p.locator("#settingsApply").click()
    p.wait_for_timeout(300)
    assert app_state(p, "a.panels[0].price.params") == app_state(p, "window.__priceTypes.defaults('candles')")
    # every type's settings open and apply cleanly
    for t in ("heikin", "bars", "line", "area", "current"):
        p.select_option(".pstyle", t)
        open_price_settings(p)
        p.locator("#settingsApply").click()
        p.wait_for_timeout(200)
        assert app_state(p, PRICE_SERIES + ".length") == 1, t


def test_old_saved_style_is_migrated(tab):
    p = tab.goto("/QQQs", 1500)
    p.evaluate("""localStorage.setItem('intraday-charts.layout.v5', JSON.stringify({ layout: '1x1',
        configs: [{ symbol: 'QQQ', tf: 3, days: 1, style: 'hollow', studies: [] }], prefs: {} }))""")
    p.reload()
    p.wait_for_timeout(2000)
    assert app_state(p, "[a.panels[0].price.type, a.panels[0].price.params.up_fill]") == ["candles", False]
    assert app_state(p, "a.configs[0].style") is None


def test_current_price_line(tab):
    p = tab.goto("/QQQs", 2000)
    p.select_option(".pstyle", "current")
    p.wait_for_timeout(600)
    data = app_state(p, PRICE_SERIES + "[0].data()")
    last = app_state(p, "a.panels[0].view.bars.at(-1)")
    assert len(data) == 1 and data[0]["value"] == last["close"]            # only the latest price, no history
    green, red = "#3fbf4f", "#ef5350"
    # direction follows the latest change: step the replay and compare with the price before
    seen = set()
    for _ in range(12):
        before = app_state(p, "a.panels[0].view.price")
        p.locator("#stepBack").click()
        p.wait_for_timeout(500)
        now = app_state(p, "a.panels[0].view.price")
        color = app_state(p, PRICE_SERIES + "[0].options().color")
        if now < before:
            assert color == red
        elif now > before:
            assert color == green
        seen.add(color)
        assert app_state(p, PRICE_SERIES + "[0].data().length") == 1
    assert seen == {green, red}


def test_no_study_draws_signal_arrows(tab):
    p = tab.goto("/QQQs", 1500)
    types = app_state(p, "a.catalog.map((s) => s.type)")
    assert not {"whale", "sde", "signals"} & set(types)
    # VZO is back as an indicator only: its own pane, no arrows on the price
    p.locator(".panel").first.locator(".fxbtn").click()
    p.locator("#catalogList button[aria-label='Add Volume Zone Oscillator (VZO)']").click()
    p.locator("#studiesDlg [data-close]").click()
    p.wait_for_timeout(1500)
    vzo = app_state(p, "Object.values(a.panels[0].view.studies)[0]")
    assert vzo["ok"] and vzo["lines"][0]["data"] and not vzo.get("markers")
    assert app_state(p, "a.panels[0].chart.panes().length") == 2
    # every study at once: none of them puts a marker (arrow) on the chart
    p.locator(".panel").first.locator(".fxbtn").click()
    for name in app_state(p, "a.catalog.map((s) => s.name)"):
        p.locator(f"#catalogList button[aria-label='Add {name}']").click()
        p.wait_for_timeout(150)
    p.locator("#studiesDlg [data-close]").click()
    p.wait_for_timeout(2500)
    assert app_state(p, "Object.values(a.panels[0].view.studies).every((r) => r.ok)")
    assert app_state(p, "Object.values(a.panels[0].view.studies).flatMap((r) => r.markers || []).length") == 0
    assert p.locator("#catalogList h4", has_text="Preset").count() == 0      # no preset study sets


def test_layout_timeframe_and_days(tab):
    p = tab.goto("/QQQs")
    p.select_option("#layout", "2x2")
    p.wait_for_timeout(1200)
    assert p.locator(".panel:visible").count() == 4
    first = p.locator(".panel").first
    first.locator("select.tf").select_option("5")
    first.locator("select.days").select_option("2")
    p.wait_for_timeout(1200)
    assert app_state(p, "[a.panels[0].tf, a.panels[0].days]") == [5, 2]
    p.reload()
    p.wait_for_timeout(2000)                                          # kept in this browser
    assert p.locator("#layout").input_value() == "2x2"
    assert app_state(p, "[a.panels[0].tf, a.panels[0].days]") == [5, 2]


def test_daily_weekly_and_monthly_candles(tab):
    """The duration menu: 1m ... 15m, then 1d / 1w / 1M candles from daily prices, with months or years shown."""
    p = tab.goto("/QQQs", 2500)
    first = p.locator(".panel").first
    assert first.locator("select.tf option").all_inner_texts() == ["1m", "3m", "5m", "15m", "1d", "1w", "1M"]
    first.locator("select.tf").select_option("1d")
    p.wait_for_timeout(1500)
    assert first.locator("select.days option").all_inner_texts() == \
        ["3 months", "6 months", "1 year", "2 years", "5 years", "10 years"]
    assert first.locator("select.days").input_value() == "6"                       # 1d shows 6 months to start
    assert first.locator(".ptitle b").inner_text() == "QQQ 6 months 1d"
    v = "a.panels[0].view"
    assert app_state(p, f"{v}.period && {v}.step === 86400 && {v}.bars.length > 100")
    days = app_state(p, f"{v}.bars.map((b) => b.day)")
    assert days == sorted(set(days)) and days[-1] == app_state(p, "a.day")          # one candle a day, up to the replay day
    assert not app_state(p, "a.panels[0].chart.options().timeScale.timeVisible")   # dates only on the axis
    first.locator("select.days").select_option("12")
    p.wait_for_timeout(1200)
    assert first.locator(".ptitle b").inner_text() == "QQQ 1 year 1d"
    first.locator("select.tf").select_option("1w")
    p.wait_for_timeout(1200)
    assert first.locator("select.days").input_value() == "24"                      # each duration keeps its own range
    weeks = app_state(p, f"{v}.bars.map((b) => new Date(b.time * 1000).getUTCDay())")
    assert set(weeks) <= {1, 2, 3, 4, 5} and app_state(p, f"{v}.step") == 7 * 86400
    first.locator("select.tf").select_option("1M")
    p.wait_for_timeout(1200)
    months = app_state(p, f"{v}.bars.map((b) => b.day.slice(0, 7))")
    assert months == sorted(set(months)) and first.locator(".ptitle b").inner_text() == "QQQ 10 years 1M"
    first.locator("select.tf").select_option("1d")
    p.wait_for_timeout(1200)
    assert first.locator("select.days").input_value() == "12"                      # 1d remembered its 1 year
    # back to minutes: the days menu returns with its own choice
    first.locator("select.tf").select_option("3")
    p.wait_for_timeout(1200)
    assert first.locator("select.days option").all_inner_texts() == ["Today", "2 days", "3 days", "5 days"]
    assert app_state(p, f"{v}.period") is False and app_state(p, "a.panels[0].chart.options().timeScale.timeVisible")
    first.locator("select.tf").select_option("1d")
    p.wait_for_timeout(1000)
    p.reload()
    p.wait_for_timeout(2500)                                                        # kept in this browser
    assert app_state(p, "[a.panels[0].tf, a.panels[0].range()]") == ["1d", 12]
    assert p.locator(".panel").first.locator(".ptitle b").inner_text() == "QQQ 1 year 1d"


def test_daily_candles_follow_replay_and_mark_intraday_studies(tab):
    p = tab.goto("/QQQs", 2500)
    p.select_option("#layout", "2x1")
    p.wait_for_timeout(1500)
    daily = p.locator(".panel").nth(1)
    daily.locator("select.tf").select_option("1d")
    p.wait_for_timeout(1500)
    # today's candle is built from the minutes up to the replay cursor
    p.evaluate("(() => { const a = window.__chartApp; a.cursor = 10 * 60 + 30; })()")
    p.evaluate("window.__chartApp.panels.forEach((x) => x.refresh())")
    p.wait_for_timeout(1500)
    early = app_state(p, "a.panels[1].view.bars.at(-1)")
    p.evaluate("(() => { const a = window.__chartApp; a.cursor = 15 * 60 + 59; })()")
    p.evaluate("window.__chartApp.panels.forEach((x) => x.refresh())")
    p.wait_for_timeout(1500)
    late = app_state(p, "a.panels[1].view.bars.at(-1)")
    assert early["day"] == late["day"] and early["open"] == late["open"]
    assert early["high"] <= late["high"] and early["low"] >= late["low"] and not early["complete"]
    # studies: an EMA draws; VWAP needs minutes, so it says so instead
    p.locator(".panel").nth(1).click(position={"x": 200, "y": 200})
    p.evaluate("""(() => { const pnl = window.__chartApp.panels[1]; pnl.addStudy("ema"); pnl.addStudy("vwap"); })()""")
    p.wait_for_timeout(1500)
    res = app_state(p, "Object.values(a.panels[1].view.studies).map((r) => [r.type, r.ok, r.note || null, (r.lines || []).length])")
    assert ["ema", True, None, 1] in res and ["vwap", True, "intraday charts only (1m to 15m)", 0] in res
    assert "intraday charts only" in daily.locator(".legends").inner_text()
    # the same studies on minutes draw normally
    daily.locator("select.tf").select_option("5")
    p.wait_for_timeout(1500)
    res = app_state(p, "Object.values(a.panels[1].view.studies).map((r) => [r.type, (r.lines || []).length > 0])")
    assert res == [["ema", True], ["vwap", True]]



def test_session_structure_studies(tab):
    """Initial Balance, anchored VWAP (from the VWAP button), relative volume and TPO on one chart."""
    p = tab.goto("/QQQs", 2500)
    first = p.locator(".panel").first
    first.locator(".tools button", has_text="VWAP").click()
    assert first.locator(".phint").inner_text() == "Click the bar to anchor a VWAP at"
    box = first.locator(".chart").bounding_box()
    t = app_state(p, "a.panels[0].view.bars.find((b) => b.session === 'rth').time + 3600")      # 10:30
    x = app_state(p, f"a.panels[0].chart.timeScale().timeToCoordinate({t})")
    p.mouse.click(box["x"] + x, box["y"] + box["height"] / 2)
    wait_state(p, "a.panels[0].studies.some((s) => s.type === 'anchored_vwap')")
    s = app_state(p, "a.panels[0].studies.find((s) => s.type === 'anchored_vwap').params")
    assert s["anchor"] == "Chosen time" and s["at"].endswith(" 10:30")
    assert app_state(p, "a.panels[0].tool") is None                       # one click, then the tool is off
    for type in ("initial_balance", "rvol", "tpo", "volume_profile", "cvd_estimate"):
        p.evaluate(f"window.__chartApp.panels[0].addStudy('{type}')")
    wait_state(p, "Object.keys(a.panels[0].view.studies).length === 6")
    res = app_state(p, "Object.values(a.panels[0].view.studies).map((r) => [r.type, r.ok, r.error || null])")
    assert all(ok for _, ok, _ in res), res
    legend = first.locator(".legends").inner_text()
    assert "Anchored VWAP" in legend and "Initial Balance (60m)" in legend and "RVOL (10 sessions)" in legend
    assert "TPO (today, RTH, 30m)" in legend and "CVD estimate (close location)" in legend
    assert "not exchange order flow" in legend                              # labelled as an estimate
    v = "a.panels[0].view.studies"
    avwap = app_state(p, f"Object.values({v}).find((r) => r.type === 'anchored_vwap')")
    assert avwap["lines"][0]["data"][0]["time"] == t and avwap["verticals"][0]["time"] == t
    sides = app_state(p, f"Object.values({v}).filter((r) => r.profile).map((r) => r.profile.side).sort()")
    assert sides == ["left", "right"]                                      # volume profile and TPO side by side
    assert app_state(p, "a.panels[0].chart.panes().length") == 3           # RVOL and CVD in their own panes
    # the anchor time is an ordinary setting
    first.locator(".fxbtn").click()
    p.wait_for_timeout(400)
    names = p.locator("#activeList").inner_text()
    assert "Anchored VWAP" in names and "TPO" in names
    p.keyboard.press("Escape")
    # the studies dialog lists the profiles in their own group
    first.locator(".fxbtn").click()
    p.wait_for_timeout(400)
    assert "Profiles" in p.locator("#catalogList h4").all_text_contents()
    p.keyboard.press("Escape")


def test_context_studies_ask_for_the_symbols_they_read(tab):
    """Relative strength and the heavyweights strip read other symbols: the page asks the collector for them."""
    p = tab.goto("/QQQs", 2500)
    asked = []
    p.on("request", lambda r: asked.append(json.loads(r.post_data)) if r.url.endswith("/api/fetch") else None)
    for type in ("relative_strength", "heavyweights", "range_meter"):
        p.evaluate(f"window.__chartApp.panels[0].addStudy('{type}')")
    wait_state(p, "Object.keys(a.panels[0].view.studies).length === 3")
    p.wait_for_timeout(800)
    syms = {s for a in asked for s in a["symbols"]}
    assert {"SPY", "NVDA", "AAPL", "MSFT"} <= syms and "QQQ" not in syms        # not the chart's own symbol
    legend = p.locator(".panel").first.locator(".legends")
    assert "Relative strength vs SPY" in legend.inner_text() and "QQQ vs SPY:" in legend.inner_text()
    boxes = legend.locator(".labels .lbl").all_inner_texts()
    assert boxes[0].startswith("Top 10:") and "NVDA \u2026" in boxes                 # no NVDA bars in the test data
    assert any(b.startswith("Day range") for b in boxes)
    assert "weights as of 2026-10-02" in legend.inner_text()


def test_windows_saved_under_the_old_project_name_carry_over(tab):
    """The project was called intraday-chart: a browser's saved windows and drawings move to the new names once."""
    p = tab.goto("/QQQs", 800)
    p.evaluate("""localStorage.clear();
      localStorage.setItem('intraday-chart.layout.v5', JSON.stringify({ layout: '2x1',
        configs: [{ symbol: 'QQQ', tf: 5, days: 1, studies: [] }, { symbol: 'SPY', tf: 3, days: 1, studies: [] }], prefs: {} }));
      localStorage.setItem('intraday-chart.drawings.v1', JSON.stringify({ QQQ: [{ id: 'd1', type: 'hline', price: 700 }] }));
      localStorage.setItem('intraday-chart.earnings.mode', JSON.stringify('price'));""")
    p = tab.goto("/QQQs", 2500)
    assert app_state(p, "[a.layout, a.panels.map((x) => [x.symbol, x.tf])]") == ["2x1", [["QQQ", 5], ["SPY", 3]]]
    keys = p.evaluate("Object.keys(localStorage).sort()")
    assert not any(k.startswith("intraday-chart.") for k in keys)
    assert {"intraday-charts.layout.v5", "intraday-charts.drawings.v1", "intraday-charts.earnings.mode"} <= set(keys)
    assert p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1')).QQQ[0].price") == 700
    # a newer value already saved under the new name is kept
    p.evaluate("""localStorage.setItem('intraday-chart.earnings.mode', JSON.stringify('relative'))""")
    p = tab.goto("/earnings", 800)
    assert p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.earnings.mode'))") == "price"
    assert p.evaluate("localStorage.getItem('intraday-chart.earnings.mode')") is None

def test_symbol_input_accepts_and_rejects(tab):
    p = tab.goto("/QQQs")
    box = p.locator("input.sym").first
    box.fill("bad sym!")
    box.press("Enter")
    p.wait_for_timeout(500)
    assert app_state(p, "a.panels[0].symbol") == "QQQ"
    box.fill("spy")
    box.press("Enter")
    p.wait_for_timeout(1500)
    assert app_state(p, "a.panels[0].symbol") == "SPY"


def test_add_configure_hide_and_remove_a_study(tab):
    p = tab.goto("/QQQs")
    n0 = app_state(p, "a.panels[0].studies.length")
    p.locator(".panel").first.locator(".fxbtn").click()
    p.fill("#studySearch", "RSI")
    p.locator("#catalogList button[aria-label='Add Relative Strength Index (RSI)']").click()
    p.wait_for_timeout(1200)
    assert app_state(p, "a.panels[0].studies.length") == n0 + 1
    p.locator("#activeList .arow").last.get_by_role("button", name="Settings").click()
    length = p.locator("#settingsForm input[data-key='length']")
    length.fill("21")
    p.click("#settingsApply")
    p.wait_for_timeout(1200)
    rsi = app_state(p, "a.panels[0].studies.find((s) => s.type === 'rsi')")
    assert rsi["params"]["length"] == 21
    assert app_state(p, "a.panels[0].view.studies[a.panels[0].studies.find((s) => s.type === 'rsi').uid].ok")
    p.locator("#activeList .arow").last.get_by_role("button", name="Hide").click()
    assert app_state(p, "a.panels[0].studies.find((s) => s.type === 'rsi').visible") is False
    p.locator("#activeList .arow").last.get_by_role("button", name="Remove").click()
    p.wait_for_timeout(800)
    assert app_state(p, "a.panels[0].studies.length") == n0


def test_copy_studies_to_all_charts(tab):
    p = tab.goto("/QQQs")
    p.select_option("#layout", "3x1")
    p.wait_for_timeout(1200)
    p.locator(".panel").nth(1).locator(".fxbtn").click()
    for name in ("ATR levels (Saty-style)", "Events"):
        p.locator(f"#catalogList button[aria-label='Add {name}']").click()
    p.wait_for_timeout(800)
    want = app_state(p, "a.panels[1].studies.map((s) => s.type)")
    p.once("dialog", lambda d: d.accept())                       # "Give every chart ... the same studies?"
    p.click("#copyStudies")
    p.wait_for_timeout(1500)
    assert app_state(p, "a.panels.map((x) => x.studies.map((s) => s.type))") == [want] * 3


def test_replay_steps_and_plays(tab):
    p = tab.goto("/QQQs")
    p.fill("#cursor", "700")
    p.dispatch_event("#cursor", "input")
    p.wait_for_timeout(800)
    assert p.inner_text("#cursorLabel") == "11:40"
    p.click("#stepFwd")
    p.wait_for_timeout(600)
    assert p.inner_text("#cursorLabel") != "11:40"
    p.click("#stepBack")
    p.click("#stepBack")
    p.wait_for_timeout(600)
    before = p.inner_text("#cursorLabel")
    p.click("#play")
    p.wait_for_timeout(1600)
    p.click("#play")
    assert p.inner_text("#cursorLabel") > before


def test_drawings_line_and_alert(tab):
    p = tab.goto("/QQQs")
    panel = p.locator(".panel").first
    panel.locator(".tools button", has_text="Line").click()
    box = panel.locator(".chart").bounding_box()
    p.mouse.click(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.3)
    p.wait_for_timeout(500)
    drawings = p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1'))")
    assert [d["type"] for d in drawings["QQQ"]] == ["hline"]
    assert panel.locator(".leg.drawing").count() == 1
    panel.locator(".leg.drawing").hover()                       # its buttons show on hover
    panel.locator(".leg.drawing button[aria-label^='Delete']").click()
    assert p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1'))")["QQQ"] == []


def test_drawing_tools_alert_trend_and_settings(tab):
    """Every tool from the registry: header buttons, a two-click trend line, an alert that fires going forward
    (and Re-arm), and a drawing's settings dialog."""
    p = tab.goto("/QQQs")
    panel = p.locator(".panel").first
    assert panel.locator(".tools button").all_inner_texts() == ["Alert", "Line", "Trend", "VWAP"]
    drawn = lambda: p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1') || '{}')").get("QQQ", [])
    # replay to 10:00, then put an alert just above the price there
    p.fill("#cursor", "600"); p.dispatch_event("#cursor", "input"); p.dispatch_event("#cursor", "change")
    p.wait_for_timeout(1200)
    box = panel.locator(".chart").bounding_box()
    price = app_state(p, "a.panels[0].view.price")
    y = app_state(p, f"a.panels[0].candles.priceToCoordinate({price} + 0.3)")
    panel.locator(".tools button", has_text="Alert").click()
    p.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + y)
    p.wait_for_timeout(400)
    alert = drawn()[0]
    assert alert["type"] == "alert" and alert["op"] == ">=" and "triggered" not in alert
    # the trend line takes two clicks; the hint changes in between
    panel.locator(".tools button", has_text="Trend").click()
    assert panel.locator(".phint").inner_text() == "Click the first point"
    p.mouse.click(box["x"] + 100, box["y"] + 300)
    assert panel.locator(".phint").inner_text() == "Click the second point"
    p.mouse.move(box["x"] + 200, box["y"] + 250)
    p.mouse.click(box["x"] + 220, box["y"] + 240)
    p.wait_for_timeout(400)
    trend = drawn()[1]
    assert trend["type"] == "trend" and trend["p1"] != trend["p2"] and panel.locator(".phint").inner_text() == ""
    # step forward until the price passes the alert: it fires once, a message shows, and Re-arm appears
    for _ in range(60):
        if drawn()[0].get("triggered"):
            break
        p.locator("#stepFwd").click()
        p.wait_for_timeout(250)
    assert drawn()[0].get("triggered")
    assert p.locator(".toast", has_text="MARK >=").count() >= 1
    row = panel.locator(".leg.drawing").first
    row.hover()
    row.locator("button", has_text="Re-arm").click()
    p.wait_for_timeout(300)
    assert "triggered" not in drawn()[0]
    # a drawing's settings come from its tool
    row = panel.locator(".leg.drawing").nth(1)
    row.hover()
    row.locator("button", has_text="Settings").click()
    assert p.locator("#settingsTitle").inner_text() == "Trend line"
    p.locator("#settingsForm [data-key='extend']").check()
    p.locator("#settingsApply").click()
    p.wait_for_timeout(300)
    assert drawn()[1]["extend"] is True and panel.locator(".leg.drawing .name").nth(1).inner_text() == "Trend line (extended)"


def test_saved_layout_round_trip(tab):
    p = tab.goto("/QQQs")
    p.select_option("#layout", "3x1")
    p.wait_for_timeout(1200)
    p.click("#layoutsBtn")
    p.fill("#savedMenu input[type=text]", "Three across")
    p.locator("#savedMenu button", has_text="Save").click()
    p.wait_for_timeout(500)
    saved = p.evaluate("fetch('/api/saved/layouts').then((r) => r.json())")
    assert saved["Three across"]["layout"] == "3x1"
    p.mouse.click(700, 500)                                     # a click elsewhere closes the menu
    p.select_option("#layout", "1x1")
    p.wait_for_timeout(800)
    p.click("#layoutsBtn")
    p.locator("#savedMenu .mload", has_text="Three across").click()
    p.wait_for_timeout(1500)
    assert p.locator("#layout").input_value() == "3x1" and p.locator(".panel:visible").count() == 3


def test_load_data_dialog_queues_a_request(tab, data):
    p = tab.goto("/QQQs")
    p.click("#openData")
    p.fill("#dataSyms", "NVDA, AMD")
    p.fill("#dataDay", "2026-10-15")
    p.click("#dataFetch")
    p.wait_for_timeout(800)
    reqs = [json.loads(f.read_text()) for f in (data / "control" / "requests").glob("*.json")]
    assert any(r["symbols"] == ["NVDA", "AMD"] and r["day"] == "2026-10-15" for r in reqs)
    assert p.inner_text("#dataMsg")


def test_live_mode_toggles(tab):
    p = tab.goto("/QQQs")
    assert p.locator("#replayBar").is_visible()
    height = p.locator("#grid").bounding_box()["height"]
    p.click("#modeLive")
    p.wait_for_timeout(1000)
    assert "active" in p.get_attribute("#modeLive", "class")
    assert p.locator("#day").is_disabled()
    assert p.locator("#replayBar").is_hidden()                       # no replay controls in Live
    assert p.locator("#grid").bounding_box()["height"] > height + 20  # the charts take the room
    p.click("#modeReplay")
    p.wait_for_timeout(800)
    assert not p.locator("#day").is_disabled() and p.locator("#replayBar").is_visible()
    assert abs(p.locator("#grid").bounding_box()["height"] - height) < 2


def collector_status(data, connected=True):
    """What the collector would report (control/status.json), so the page sees TWS as reachable or not."""
    import json
    import time
    (data / "control").mkdir(exist_ok=True)
    (data / "control" / "status.json").write_text(json.dumps({"connected": connected, "heartbeat": time.time(),
                                                                "message": "" if connected else "TWS refused the connection"}))


def is_live(p):
    return "active" in (p.get_attribute("#modeLive", "class") or "") and p.locator("#day").is_disabled()


def test_live_stays_on_across_dashboards_and_pages(tab, data):
    collector_status(data)
    p = tab.goto("/QQQs")
    assert not is_live(p)                                             # Replay at first
    p.click("#modeLive")
    wait_state(p, "a.live")
    p.select_option(".dashsel", "Internals")                         # another dashboard: still Live
    p.wait_for_url("**/Internals")
    wait_state(p, "a.live")
    assert is_live(p) and p.locator("#replayBar").is_hidden()
    p.select_option(".dashsel", "\u0000earnings")                    # a page without charts, and back
    p.wait_for_url("**/earnings*")
    p = tab.goto("/QQQs", 1000)
    wait_state(p, "a.live")
    assert is_live(p)
    p.click("#modeReplay")                                            # back to Replay by hand: stays Replay
    p = tab.goto("/Internals", 2000)
    assert not is_live(p) and not app_state(p, "a.live")


def test_a_new_tab_starts_in_replay(tab, browser, server, data):
    collector_status(data)
    p = tab.goto("/QQQs")
    p.click("#modeLive")
    wait_state(p, "a.live")
    other = browser.new_page()
    other.goto(server + "/QQQs")
    other.wait_for_timeout(2000)
    assert other.evaluate("window.__chartApp.live") is False and "active" in (other.get_attribute("#modeReplay", "class") or "")
    other.close()


def test_live_drops_to_replay_when_tws_goes_away(tab, data):
    collector_status(data)
    p = tab.goto("/QQQs")
    p.click("#modeLive")
    wait_state(p, "a.live")
    collector_status(data, connected=False)                          # TWS gone: two polls (about 10 s), then Replay
    wait_state(p, "!a.live", timeout=20000)
    assert not is_live(p) and p.locator("#replayBar").is_visible()
    assert "Live stopped: the collector can't reach TWS" in p.inner_text("#toasts")
    p = tab.goto("/QQQs", 2000)                                       # and it stays in Replay
    assert not app_state(p, "a.live")


def test_live_isnt_restored_without_tws(tab, data):
    collector_status(data)
    p = tab.goto("/QQQs")
    p.click("#modeLive")
    wait_state(p, "a.live")
    (data / "control" / "status.json").unlink()                       # the collector has stopped
    p = tab.goto("/Internals", 2500)
    assert not app_state(p, "a.live") and "Live stopped: the TWS collector isn't running" in p.inner_text("#toasts")


# ---------------------------------------------------------------- dashboards
def test_switcher_and_addresses(tab):
    p = tab.goto("/")
    assert p.title().startswith("QQQs")
    assert p.locator(".dashsel option").all_inner_texts() == ["QQQs  (default)", "Internals", "Earnings", "Expected move",
                                                                 "Manage dashboards…"]
    p.select_option(".dashsel", "\u0000manage")
    p.wait_for_url("**/dashboards")
    p.wait_for_function("document.querySelectorAll('table.dash tbody tr').length > 0")   # the list loads after the page
    assert p.locator("table.dash tbody tr").count() == 2          # QQQs and the built-in Internals
    assert p.locator("#newType").count() == 0                    # one kind of dashboard: no type to pick
    p.select_option(".dashsel", "QQQs")
    p.wait_for_url("**/QQQs")


def test_create_rename_default_duplicate_delete(tab):
    p = tab.goto("/QQQs")
    p.select_option("#layout", "3x1")                         # this browser's QQQs window, to be duplicated
    p.wait_for_timeout(1200)
    p = tab.goto("/dashboards", 800)
    p.fill("#newName", "two words")
    p.click("button:has-text('Create and open')")
    p.wait_for_timeout(500)
    assert "letters, digits" in p.inner_text("#msg")
    p.fill("#newName", "Swing")
    p.click("button:has-text('Create and open')")
    p.wait_for_url("**/Swing")
    p = tab.goto("/dashboards", 800)
    p.locator("tr:has-text('QQQs') button:has-text('Duplicate')").click()
    p.wait_for_timeout(800)
    copy = next(i for i in p.evaluate("fetch('/api/dashboards').then((r) => r.json())")["items"] if i["name"] == "QQQs-2")
    stored = p.evaluate(f"[localStorage.getItem('intraday-charts.layout.v5'), localStorage.getItem('intraday-charts.layout.v5@{copy['id']}')]")
    assert stored[1] and stored[1] == stored[0]                # the dashboards page copied this browser's window
    p = tab.goto("/QQQs-2", 2000)
    assert p.locator("#layout").input_value() == "3x1"
    p = tab.goto("/dashboards", 800)
    p.locator("tr:has-text('QQQs-2') button:has-text('Rename')").click()
    p.fill("input.rename", "Scalp")
    p.press("input.rename", "Enter")
    p.wait_for_timeout(600)
    p.locator("tr:has-text('Swing') button:has-text('Make default')").click()
    p.wait_for_timeout(600)
    assert p.locator("tr:has-text('Swing') .badge").count() == 1
    p.locator("tr:has-text('Scalp') button:has-text('Delete')").click()
    p.locator("tr:has-text('Scalp') button:has-text('Confirm delete')").click()
    p.wait_for_timeout(600)
    names = [n.strip() for n in p.locator("table.dash tbody tr td:first-child a").all_inner_texts()]
    assert names == ["QQQs", "Internals", "Swing"]
    p = tab.goto("/", 1500)
    assert p.title().startswith("Swing")


def test_charts_dashboard_from_saved_layout(tab):
    p = tab.goto("/dashboards", 500)
    p.evaluate("""fetch('/api/saved/layouts/Solo', {method: 'PUT', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({layout: '1x1', configs: [{symbol: 'SPY', tf: 15, days: 1, studies: [{type: 'vwap'}]}]})})""")
    p = tab.goto("/dashboards", 800)
    p.fill("#newName", "Solo")
    p.select_option("#newStart", "layout:Solo")
    p.click("button:has-text('Create and open')")
    p.wait_for_url("**/Solo")
    p.wait_for_timeout(2000)
    assert app_state(p, "[a.layout, a.panels[0].symbol, a.panels[0].tf, a.panels[0].studies.map((s) => s.type)]") == \
        ["1x1", "SPY", 15, ["vwap"]]


def test_unknown_dashboard_page_is_escaped(tab):
    p = tab.goto("/%3Cb%3Ehi%3Cb%3E", 300)                      # /<b>hi<b>: shown as text, not as markup
    assert "There is no dashboard called <b>hi<b>." in p.inner_text("body")
    assert p.locator("body b b").count() == 0


# ---------------------------------------------------------------- environment check
def test_environment_check_on_the_dashboards_page(tab):
    p = tab.goto("/dashboards", 1200)
    rows = p.locator("#env .pill")
    assert rows.count() >= 6
    names = p.locator("#env div:nth-child(3n+2)").all_inner_texts()
    assert "Who can connect" in names and "Read-only trading data" in names
    assert p.locator("#env .pill.fail").count() == 0
    p.click("#recheck")
    p.wait_for_timeout(500)
    assert p.locator("#env .pill").count() == rows.count()


def test_checks_needing_attention_are_linked_from_every_page(tab):
    for path in ("/QQQs", "/dashboards"):          # no collector in the tests: TWS connection is "Check"
        p = tab.goto(path, 1500)
        assert p.evaluate("document.querySelector('header.toolbar').offsetHeight") < 60, path   # one line at 1500 px
        # how many need attention depends on the machine (e.g. running as root here, not on GitHub's runners)
        n = p.evaluate("fetch('/api/environment').then((r) => r.json()).then((d) => d.checks.filter((c) => c.status !== 'ok').length)")
        link = p.locator(".dashnav a.envwarn")
        assert n >= 1 and link.count() == 1 and link.get_attribute("aria-label").startswith(f"Environment check: {n}"), path
    link.click()
    p.wait_for_url("**/dashboards#environment")


def test_charts_added_with_layout_open_on_qqq_without_studies(tab):
    p = tab.goto("/QQQs", 1500)
    p.select_option("#layout", "2x2")
    p.wait_for_timeout(2000)
    assert app_state(p, "a.panels.map((x) => [x.symbol, x.studies.length, x.price.type])") == [["QQQ", 0, "candles"]] * 4
    assert p.locator(".legtoggle:visible").count() == 0                        # no empty "Studies (0)" tag
    assert max(p.evaluate("[...document.querySelectorAll('.panel .phead')].map((h) => h.offsetHeight)")) < 60


# ---------------------------------------------------------------- Ralph's window (the screenshot of 2026-10-26)
def test_screenshot_layout_renders(tab):
    """Three charts side by side: trend studies with VZO, a current-price-line levels chart, and a second symbol.
    Any change that breaks this window fails here."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import screenshot_layout
    p = tab.goto("/QQQs", 800)
    p.evaluate("(cfgs) => localStorage.setItem('intraday-charts.layout.v5', JSON.stringify({ layout: '3x1', configs: cfgs, "
               "prefs: { fitLevels: false, extShade: true, sync: true } }))", screenshot_layout.configs())
    p.reload()
    p.wait_for_timeout(3500)
    assert p.locator(".panel:visible").count() == 3
    assert app_state(p, "a.panels.map((x) => [x.symbol, x.tf, x.price.type])") == [["QQQ", 3, "candles"], ["QQQ", 1, "current"],
                                                                                   ["SPY", 3, "candles"]]
    assert app_state(p, "a.panels.every((x) => Object.values(x.view.studies).every((r) => r.ok))")
    assert app_state(p, "a.panels.map((x) => x.chart.panes().length)") == [2, 1, 2]           # VZO in its own pane
    legends = [p.locator(".panel").nth(i).locator(".leg .name").all_inner_texts() for i in range(3)]
    assert any(t.startswith("VZO") for t in legends[0]) and any(t.startswith("VZO") for t in legends[2])
    assert any(t.startswith("Volume profile") for t in legends[1]) and any(t.startswith("Session levels") for t in legends[1])
    mid = app_state(p, "a.panels[1].view.studies")
    vp = next(r for r in mid.values() if r.get("profile"))
    assert {lv["label"] for lv in vp.get("levels", [])} >= {"POC", "VAH", "VAL"}
    assert any(r.get("labels") for r in mid.values())                                      # ATR level boxes
    assert app_state(p, PRICE_SERIES.replace("panels[0]", "panels[1]") + "[0].data().length") == 1   # price line only


# ---------------------------------------------------------------- earnings page
def earn_state(page, expr):
    return page.evaluate(f"(() => {{ const e = window.__earnings; return {expr}; }})()")


def test_earnings_page_overlays_six_quarters(tab):
    p = tab.goto("/earnings?symbol=ACME-DEMO", 2000)
    assert p.locator("#demoBanner").is_visible()                              # synthetic data is labelled
    assert p.locator(".dashsel").input_value() == "\u0000earnings"           # the page switcher shows where we are
    rows = p.locator("#legend .eq")
    assert rows.count() == 6
    colors = earn_state(p, "e.chart.series.map((s) => s.options().color)")
    assert len(set(colors)) == 6                                              # one colour per quarter
    swatches = p.evaluate("[...document.querySelectorAll('#legend .eq .sw')].map((e) => getComputedStyle(e).backgroundColor)")
    assert len(set(swatches)) == 6
    assert p.locator("#ends span").count() == 6                               # each line labelled at its end
    assert earn_state(p, "e.chart.series.every((s) => s.data().find((d) => d.time === -1).value === 0)")   # all start at 0% on day -1
    assert rows.first.locator(".val").inner_text().startswith("Day 0")
    # hovering the chart shows every quarter's value at that day
    box = p.locator("#chart").bounding_box()
    x = earn_state(p, "e.chart.chart.timeScale().timeToCoordinate(-3)")
    p.mouse.move(box["x"] + x, box["y"] + box["height"] / 2)
    p.wait_for_timeout(300)
    assert all(t.startswith("\u22123") for t in p.locator("#legend .eq .val").all_inner_texts())
    # hovering a legend row highlights its line
    rows.nth(2).hover()
    p.wait_for_timeout(200)
    assert earn_state(p, "e.chart.series.map((s) => s.options().lineWidth)") == [2, 2, 3, 2, 2, 2]
    p.mouse.move(5, 5)
    p.wait_for_timeout(200)
    assert earn_state(p, "e.chart.series.map((s) => s.options().lineWidth)") == [2] * 6


def test_earnings_page_days_before_and_after(tab):
    p = tab.goto("/earnings?symbol=ACME-DEMO", 2000)
    assert (p.locator("#daysBefore").input_value(), p.locator("#daysAfter").input_value()) == ("10", "5")
    span = "[Math.min(...e.chart.series.map((s) => s.data()[0].time)), Math.max(...e.chart.series.map((s) => s.data().at(-1).time))]"
    assert earn_state(p, span) == [-10, 5]
    p.fill("#daysBefore", "20")
    p.locator("#daysBefore").press("Enter")
    p.fill("#daysAfter", "12")                                        # typed while the first reply is on its way
    p.locator("#daysAfter").press("Enter")
    p.wait_for_timeout(1200)
    assert earn_state(p, span) == [-20, 12]
    assert "20 trading days before day 0 and 12 after" in p.locator("#status").inner_text()
    assert p.locator("#legend .eq").count() == 6 and p.locator("#ends span").count() == 6
    assert earn_state(p, "e.chart.series.every((s) => s.data().find((d) => d.time === -1).value === 0)")
    # an impossible number is marked and changes nothing
    p.fill("#daysAfter", "0")
    p.locator("#daysAfter").dispatch_event("change")
    p.wait_for_timeout(600)
    assert "bad" in p.locator("#daysAfter").get_attribute("class") and earn_state(p, span) == [-20, 12]
    # remembered in this browser, also in Price $ mode
    p = tab.goto("/earnings?symbol=ACME-DEMO", 2000)
    assert (p.locator("#daysBefore").input_value(), p.locator("#daysAfter").input_value()) == ("20", "12")
    p.click("#modes button[data-mode=price]")
    p.wait_for_timeout(500)
    assert earn_state(p, span) == [-20, 12]
    p.fill("#daysBefore", "10"); p.locator("#daysBefore").dispatch_event("change")
    p.fill("#daysAfter", "5"); p.locator("#daysAfter").dispatch_event("change")
    p.click("#modes button[data-mode=relative]")
    p.wait_for_timeout(1000)
    assert earn_state(p, span) == [-10, 5]


def test_earnings_page_relative_and_price_views(tab):
    p = tab.goto("/earnings?symbol=ACME-DEMO", 2000)
    assert earn_state(p, "e.mode") == "relative"
    assert p.locator("#modes button.active").inner_text() == "Relative %"
    view = earn_state(p, "e.view")
    newest = view["quarters"][0]["points"]
    assert earn_state(p, "e.chart.series[0].data().map((d) => d.value)") == [pt["pct"] for pt in newest]
    p.locator("#modes button", has_text="Price $").click()
    p.wait_for_timeout(400)
    assert earn_state(p, "e.chart.series[0].data().map((d) => d.value)") == [pt["price"] for pt in newest]
    assert "split" in p.inner_text("#explain") and p.locator("#legend .eq").count() == 6
    levels = earn_state(p, "e.chart.series.map((s) => s.data()[0].value)")
    assert max(levels) / min(levels) > 1.5                     # each quarter at its own price level (the stock tripled)
    box = p.locator("#chart").bounding_box()
    x = earn_state(p, "e.chart.chart.timeScale().timeToCoordinate(2)")
    p.mouse.move(box["x"] + x, box["y"] + box["height"] / 2)
    p.wait_for_timeout(300)
    hover = p.locator("#legend .eq .val").first.inner_text()
    assert "$" in hover and "%" in hover                       # price, with the move in % beside it
    p.reload()
    p.wait_for_timeout(2000)
    assert earn_state(p, "e.mode") == "price"                  # remembered in this browser
    p.locator("#modes button", has_text="Relative %").click()
    p.wait_for_timeout(300)
    assert earn_state(p, "e.chart.series[0].data().map((d) => d.value)") == [pt["pct"] for pt in newest]


def test_earnings_page_messages(tab):
    p = tab.goto("/earnings?symbol=NVDA", 1500)
    assert "SEC_CONTACT" in p.inner_text("#msg") and p.locator("#legend .eq").count() == 0   # lookups are off here
    p.fill("#sym", "not valid!")
    p.press("#sym", "Enter")
    assert "isn't a stock symbol" in p.inner_text("#msg")
    p.fill("#sym", "acme-demo")
    p.press("#sym", "Enter")
    p.wait_for_timeout(1500)
    assert p.locator("#legend .eq").count() == 6 and "symbol=ACME-DEMO" in p.url
    p = tab.goto("/earnings", 1500)                                            # remembers the last symbol
    assert p.input_value("#sym") == "ACME-DEMO"


def test_page_switcher_reaches_the_earnings_page(tab):
    p = tab.goto("/QQQs", 1500)
    p.select_option(".dashsel", "\u0000earnings")
    p.wait_for_url("**/earnings*")
    assert p.locator("#symForm").is_visible()


# ---------------------------------------------------------------- expected-move page
def test_expected_move_page(tab):
    p = tab.goto("/expected-move?symbols=ACME-DEMO,NVDA-DEMO&date=2026-10-30", 2000)
    assert p.locator("#demoBanner").is_visible()                              # synthetic data is labelled
    assert p.locator(".dashsel").input_value() == "\u0000expected-move"
    rows = p.locator("#emSummary tr")
    assert rows.count() == 3                                                  # header, ACME-DEMO, NVDA-DEMO
    acme = rows.nth(1).inner_text()
    assert "ACME-DEMO" in acme and "Fri, Oct 30" in acme and "±" in acme and "IV 30% →" in acme
    assert "no synthetic quotes" in rows.nth(2).inner_text()                  # nothing invented for this one
    card = p.locator(".em-card[data-symbol=ACME-DEMO]")
    assert card.count() == 1 and p.locator(".em-card").count() == 1
    text = card.inner_text()
    for want in ("Straddle (expected move)", "0.85 x straddle", "1 sigma", "2 sigma", "usually earnings",
                 "Diagonal legs: short Fri, Oct 30, long Fri, Nov 6", "Both sides"):
        assert want in text, want
    assert card.locator(".em-legs tr").count() == 4                           # header, call, put, both
    assert "1 of 2 with quotes" in p.inner_text("#emStatus")


def test_expected_move_page_form_and_memory(tab):
    p = tab.goto("/expected-move", 1000)
    assert "Type one or more stock symbols" in p.inner_text("#emMsg")
    p.fill("#emSyms", "acme-demo")
    p.fill("#emDate", "2026-10-30")
    p.press("#emSyms", "Enter")
    p.wait_for_function("document.querySelectorAll('.em-card').length === 1")
    assert "symbols=ACME-DEMO" in p.url and "date=2026-10-30" in p.url
    p = tab.goto("/expected-move", 1500)                                      # remembers the last request
    assert p.input_value("#emSyms") == "ACME-DEMO" and p.input_value("#emDate") == "2026-10-30"
    assert p.locator(".em-card").count() == 1


# ---------------------------------------------------------------- Internals dashboard (2 charts over 4 internals)
def test_internals_dashboard(tab):
    p = tab.goto("/Internals", 4000)
    assert p.locator("#layout").input_value() == "2/4" and p.locator(".panel:visible").count() == 6
    assert app_state(p, "a.panels.map((x) => [x.symbol, x.price.type])") == [
        ["QQQ", "candles"], ["SPY", "candles"], ["VOLD-NYSE", "line"], ["-VIX", "candles"], ["TICK-NYSE", "line"],
        ["ADD-NYSE", "candles"]]
    wait_state(p, "a.panels.every((x) => x.view && x.view.bars.length && Object.values(x.view.studies).every((r) => r.ok))")
    rows = p.evaluate("[...document.querySelectorAll('#grid .gridrow')].map((r) => r.querySelectorAll('.panel').length)")
    assert rows == [2, 4]                                                               # 2 wide charts over 4
    assert p.evaluate("[...document.querySelectorAll('.splitter')].map((e) => e.dataset.kind + e.dataset.r)") == \
        ["col0", "col1", "col1", "col1", "row0"]                                        # each row has its own columns
    assert app_state(p, "a.panels[3].view.bars.every((b) => b.close < 0)")              # -VIX: VIX upside down
    vold = p.locator(".panel").nth(2)
    assert vold.locator(".ptitle span").inner_text().strip().endswith("M")              # 25.04M, not 25042025.00
    assert vold.locator("input.sym").evaluate("(e) => e.scrollWidth <= e.clientWidth")  # the whole name shows
    assert "2 over 4" in p.locator("#layout option").all_inner_texts()
    # any dashboard can use the layout
    p = tab.goto("/QQQs", 1500)
    p.select_option("#layout", "2/4")
    p.wait_for_timeout(2500)
    assert p.locator(".panel:visible").count() == 6


def test_dashboard_from_the_internals_template(tab):
    p = tab.goto("/dashboards", 1500)
    assert "Market internals" in " ".join(p.locator("#newStart option").all_inner_texts())
    p.fill("#newName", "Breadth")
    p.select_option("#newStart", "template:internals")
    p.click("button:has-text('Create and open')")
    p.wait_for_url("**/Breadth")
    p.wait_for_timeout(3000)
    assert app_state(p, "a.layout") == "2/4" and app_state(p, "a.panels.length") == 6


def test_dashboard_from_top_and_bottom_counts(tab):
    p = tab.goto("/dashboards", 1500)
    assert p.locator("#rowsWrap").is_hidden()
    p.fill("#newName", "Wide")
    p.select_option("#newStart", "rows:")
    assert p.locator("#rowsWrap").is_visible()
    p.fill("#newTop", "3")
    p.fill("#newBottom", "5")
    p.click("button:has-text('Create and open')")
    p.wait_for_url("**/Wide")
    p.wait_for_timeout(3000)
    assert app_state(p, "a.layout") == "3/5" and app_state(p, "a.panels.length") == 8
    assert p.locator("#layout option:checked").inner_text() == "3 over 5"
    widths = p.evaluate("[...document.querySelectorAll('#grid .panel')].map((e) => Math.round(e.getBoundingClientRect().width))")
    assert max(widths[:3]) - min(widths[:3]) <= 1 and max(widths[3:]) - min(widths[3:]) <= 1 and widths[0] > widths[3]
    tops = p.evaluate("[...document.querySelectorAll('#grid .panel')].map((e) => Math.round(e.getBoundingClientRect().top))")
    assert len(set(tops[:3])) == 1 and len(set(tops[3:])) == 1 and tops[3] > tops[0]
    p.select_option("#layout", "2x2")                                 # the named layouts are still there
    p.wait_for_timeout(800)
    assert app_state(p, "a.panels.length") == 4


def test_mixed_layout_columns_resize_row_by_row(tab):
    """In 2 over 4 each row has its own column splitters: dragging one in the bottom row leaves the top row alone."""
    p = tab.goto("/Internals", 3000)
    rects = "[...document.querySelectorAll('#grid .panel')].map((e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.width)]; })"
    before = p.evaluate(rects)
    sp = p.locator(".splitter.col[data-r='1'][data-i='0']")         # between VOLD and -VIX
    box = sp.bounding_box()
    assert box["height"] < p.locator("#grid").bounding_box()["height"] / 2 + 5          # only as tall as its row
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    p.mouse.move(x, y)
    p.mouse.down()
    p.mouse.move(x + 120, y, steps=6)
    p.mouse.up()
    p.wait_for_timeout(500)
    after = p.evaluate(rects)
    assert after[:2] == before[:2]                                   # top row unchanged
    assert after[2][1] > before[2][1] + 100 and after[3][1] < before[3][1] - 100
    assert after[4:] == before[4:]                                   # only the pair either side of the splitter
    assert sp.bounding_box()["x"] > box["x"] + 100                   # the splitter followed
    # the top row's splitter works the same way
    top = p.locator(".splitter.col[data-r='0']")
    tb = top.bounding_box()
    p.mouse.move(tb["x"] + 3, tb["y"] + 50)
    p.mouse.down()
    p.mouse.move(tb["x"] - 150, tb["y"] + 50, steps=6)
    p.mouse.up()
    p.wait_for_timeout(500)
    moved = p.evaluate(rects)
    assert moved[0][1] < before[0][1] - 100 and moved[2:] == after[2:]
    # kept in this browser, and a double-click makes that row's charts equal again
    p = tab.goto("/Internals", 3000)
    assert p.evaluate(rects) == moved
    p.locator(".splitter.col[data-r='1'][data-i='0']").dblclick()
    p.wait_for_timeout(500)
    again = p.evaluate(rects)
    assert again[:2] == moved[:2] and max(w for _, w in again[2:]) - min(w for _, w in again[2:]) <= 1
    # maximize still shows just the one chart
    p.locator(".panel").nth(4).locator(".maxbtn").click()
    p.wait_for_timeout(500)
    assert p.locator(".panel:visible").count() == 1 and p.locator(".splitter:visible").count() == 0
    full = p.locator(".panel").nth(4).bounding_box()["width"]
    assert full > p.locator("#grid").bounding_box()["width"] - 20

