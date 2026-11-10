"""The two pages (a chart dashboard and /dashboards), driven in Chromium against the real server on SYNTHETIC bars.
Every test also fails on any JavaScript error (see the `tab` fixture)."""
import json
import re
import time


LAST = "2026-10-16"          # last synthetic day


WIDE = 1840   # Ralph's screen: the chart page's top bar fits one line there with any font (at 1500 it depends on the font)


def app_state(page, expr):
    return page.evaluate(f"(() => {{ const a = window.__intraday.chart; return {expr}; }})()")


def wait_state(page, expr, timeout=15000):
    """Wait until the expression is true (slower machines, e.g. GitHub's runners, need more than a fixed pause)."""
    page.wait_for_function(f"(() => {{ const a = window.__intraday.chart; return {expr}; }})()", timeout=timeout)


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
    brand = p.locator(".brand").first                                            # the mark: a link to the repository
    assert brand.inner_text() == "RP" and brand.get_attribute("target") == "_blank"
    assert brand.get_attribute("href") == "https://github.com/ralphsplace/intraday-charts"
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
    assert app_state(p, "a.panels[0].price") == {"type": "candles", "params": {**app_state(p, "window.__intraday.priceTypes.defaults('candles')"),
                                                 "up_fill": False, "color_by": "Previous close", "wick_width": 2, "up_color": "#112233"}}
    assert app_state(p, PRICE_SERIES + ".length") == 1
    open_price_settings(p)
    p.locator("#settingsDefaults").click()
    p.locator("#settingsApply").click()
    p.wait_for_timeout(300)
    assert app_state(p, "a.panels[0].price.params") == app_state(p, "window.__intraday.priceTypes.defaults('candles')")
    # every type's settings open and apply cleanly
    for t in ("heikin", "bars", "line", "area", "current"):
        p.select_option(".pstyle", t)
        open_price_settings(p)
        p.locator("#settingsApply").click()
        p.wait_for_timeout(200)
        assert app_state(p, PRICE_SERIES + ".length") == 1, t


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
    # Draw as: dots (the default), a line, or both
    for choice, line, dots in (("Dots", False, True), ("Line & dots", True, True), ("Line", True, False)):
        p.evaluate(f"""() => {{ const pn = window.__intraday.chart.panels[0];
                              pn.studies[0].params.draw = {choice!r}; pn.changed(); }}""")
        wait_state(p, f"Object.values(a.panels[0].rendered)[0]?.res?.lines?.[0]?.draw === {dict(Dots='dots', Line='line').get(choice, 'both')!r}")
        o = app_state(p, "Object.values(a.panels[0].rendered)[0].lines.vzo.options()")
        assert (o["lineVisible"], o["pointMarkersVisible"]) == (line, dots), choice
    p.screenshot(path="/tmp/vzo-line-dots.png")
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
    p.evaluate("(() => { const a = window.__intraday.chart; a.cursor = 10 * 60 + 30; })()")
    p.evaluate("window.__intraday.chart.panels.forEach((x) => x.refresh())")
    p.wait_for_timeout(1500)
    early = app_state(p, "a.panels[1].view.bars.at(-1)")
    p.evaluate("(() => { const a = window.__intraday.chart; a.cursor = 15 * 60 + 59; })()")
    p.evaluate("window.__intraday.chart.panels.forEach((x) => x.refresh())")
    p.wait_for_timeout(1500)
    late = app_state(p, "a.panels[1].view.bars.at(-1)")
    assert early["day"] == late["day"] and early["open"] == late["open"]
    assert early["high"] <= late["high"] and early["low"] >= late["low"] and not early["complete"]
    # studies: an EMA draws; VWAP needs minutes, so it says so instead
    p.locator(".panel").nth(1).click(position={"x": 200, "y": 200})
    p.evaluate("""(() => { const pnl = window.__intraday.chart.panels[1]; pnl.addStudy("ema"); pnl.addStudy("vwap"); })()""")
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
    p.locator("#drawTools button", has_text="VWAP").click()
    first.locator(".chart").hover()                                       # the hint shows on the chart under the mouse
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
        p.evaluate(f"window.__intraday.chart.panels[0].addStudy('{type}')")
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
        p.evaluate(f"window.__intraday.chart.panels[0].addStudy('{type}')")
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
    p.locator("#drawTools button", has_text="Line").click()
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
    """Every tool from the registry: the top bar's buttons, a two-click trend line, an alert that fires going forward
    (and Re-arm), and a drawing's settings dialog."""
    p = tab.goto("/QQQs")
    panel = p.locator(".panel").first
    assert p.locator("#drawTools button").all_inner_texts() == ["Alert", "Line", "Trend", "VWAP"]
    assert panel.locator(".phead button", has_text="Alert").count() == 0          # not in the chart headers
    drawn = lambda: p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1') || '{}')").get("QQQ", [])
    # replay to 10:00, then put an alert just above the price there
    p.fill("#cursor", "600"); p.dispatch_event("#cursor", "input"); p.dispatch_event("#cursor", "change")
    p.wait_for_timeout(1200)
    box = panel.locator(".chart").bounding_box()
    price = app_state(p, "a.panels[0].view.price")
    y = app_state(p, f"a.panels[0].candles.priceToCoordinate({price} + 0.3)")
    p.locator("#drawTools button", has_text="Alert").click()
    p.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + y)
    p.wait_for_timeout(400)
    alert = drawn()[0]
    assert alert["type"] == "alert" and alert["op"] == ">=" and "triggered" not in alert
    # the trend line takes two clicks; the hint changes in between
    p.locator("#drawTools button", has_text="Trend").click()
    panel.locator(".chart").hover()
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
    # a drawing's settings come from its tool (move off the first row first: its buttons stay open under the pointer)
    p.mouse.move(5, 5)
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
    assert other.evaluate("window.__intraday.chart.live") is False and "active" in (other.get_attribute("#modeReplay", "class") or "")
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
                                                                 "Option chain", "Backtesting", "Config", "Manage dashboards…"]
    p.select_option(".dashsel", "\u0000manage")
    p.wait_for_url("**/config?tab=dashboards")
    p.wait_for_function("document.querySelectorAll('table.dash tbody tr').length > 0")   # the list loads after the page
    assert p.locator("table.dash tbody tr").count() == 2          # QQQs and the built-in Internals
    assert p.locator("#newType").count() == 0                    # one kind of dashboard: no type to pick
    p.select_option(".dashsel", "QQQs")
    p.wait_for_url("**/QQQs")


def test_create_rename_default_duplicate_delete(tab):
    p = tab.goto("/QQQs")
    p.select_option("#layout", "3x1")                         # this browser's QQQs window, to be duplicated
    p.wait_for_timeout(1200)
    p = tab.goto("/config?tab=dashboards", 800)
    p.fill("#newName", "two words")
    p.click("button:has-text('Create and open')")
    p.wait_for_timeout(500)
    assert "letters, digits" in p.inner_text("#msg")
    p.fill("#newName", "Swing")
    p.click("button:has-text('Create and open')")
    p.wait_for_url("**/Swing")
    p = tab.goto("/config?tab=dashboards", 800)
    p.locator("tr:has-text('QQQs') button:has-text('Duplicate')").click()
    p.wait_for_timeout(800)
    copy = next(i for i in p.evaluate("fetch('/api/dashboards').then((r) => r.json())")["items"] if i["name"] == "QQQs-2")
    stored = p.evaluate(f"[localStorage.getItem('intraday-charts.layout.v5'), localStorage.getItem('intraday-charts.layout.v5@{copy['id']}')]")
    assert stored[1] and stored[1] == stored[0]                # the dashboards page copied this browser's window
    p = tab.goto("/QQQs-2", 2000)
    assert p.locator("#layout").input_value() == "3x1"
    p = tab.goto("/config?tab=dashboards", 800)
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
    p = tab.goto("/config?tab=dashboards", 500)
    p.evaluate("""fetch('/api/saved/layouts/Solo', {method: 'PUT', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({layout: '1x1', configs: [{symbol: 'SPY', tf: 15, days: 1, studies: [{type: 'vwap'}]}]})})""")
    p = tab.goto("/config?tab=dashboards", 800)
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
    p = tab.goto("/config?tab=dashboards", 1200)
    rows = p.locator("#env .pill")
    assert rows.count() >= 6
    names = p.locator("#env div:nth-child(3n+2)").all_inner_texts()
    assert "Who can connect" in names and "Orders" in names
    assert p.locator("#env .pill.fail").count() == 0
    p.click("#recheck")
    p.wait_for_timeout(500)
    assert p.locator("#env .pill").count() == rows.count()


def test_checks_needing_attention_are_linked_from_every_page(tab):
    tab.page.set_viewport_size({"width": WIDE, "height": 850})
    for path in ("/QQQs", "/config?tab=dashboards"):          # no collector in the tests: TWS connection is "Check"
        p = tab.goto(path, 1500)
        assert p.evaluate("document.querySelector('header.toolbar').offsetHeight") < 60, path   # one line on Ralph's screen
        # how many need attention depends on the machine (e.g. running as root here, not on GitHub's runners)
        n = p.evaluate("fetch('/api/environment').then((r) => r.json()).then((d) => d.checks.filter((c) => c.status !== 'ok').length)")
        link = p.locator(".dashnav a.envwarn")
        assert n >= 1 and link.count() == 1 and link.get_attribute("aria-label").startswith(f"Environment check: {n}"), path
    link.click()
    p.wait_for_url("**/config?tab=dashboards#environment")


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
    return page.evaluate(f"(() => {{ const e = window.__intraday.earnings; return {expr}; }})()")


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


# ---------------------------------------------------------------- option-chain page
def oc(page, expr):
    return page.evaluate(f"(() => {{ const o = window.__intraday.options; return {expr}; }})()")


def wait_oc(page, expr, timeout=15000):
    page.wait_for_function(f"(() => {{ const o = window.__intraday.options; return {expr}; }})()", timeout=timeout)


def test_option_chain_page_builds_and_evaluates_a_template(tab):
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    assert p.locator("#demoBanner").is_visible()                              # synthetic data is labelled
    assert p.locator(".dashsel").input_value() == "\u0000options"
    assert p.locator("#ocStrip .oc-chip").count() == 8
    assert "active" in p.get_attribute("#ocStrip .oc-chip[data-expiry='20261030']", "class")
    assert p.locator("#ocChain tbody tr[data-strike]").count() == 19 and p.locator("#ocChain .oc-priceline").count() == 1
    assert p.locator("#ocChain tr.oc-inem").count() > 0                        # rows inside the expected move
    assert p.input_value("#ocBack") == "20261106"                              # the next weekly
    p.select_option("#ocTemplate", "double_diagonal")
    p.click("#ocFill")
    wait_oc(p, "o.ev && o.ev.status === 'ok' && o.state.legs.length === 4")
    assert p.locator("#ocLegs tr[data-leg]").count() == 4
    assert p.locator("#ocChain td.oc-sell").count() == 2                       # the front expiry's sold legs
    assert "Fri, Nov 6" in p.inner_text("#ocLegs") and "Net debit" in p.inner_text("#ocLegs")
    assert p.locator("#ocStats .oc-stat").count() == 8
    assert p.locator("#ocGraph polyline").count() == 2 and p.locator("#ocGraph .oc-emband").count() == 1
    assert p.locator("#ocGrid tr").count() == 12 and p.locator("#ocGrid tr.oc-nowrow").count() == 1
    times = p.locator("#ocAt option").all_inner_texts()
    assert times[0].startswith("Now") and "front expiry" in times[-1]
    p.select_option("#ocAt", "front_noon")
    wait_oc(p, "o.ev.at === 'front_noon'")
    p.select_option("#ocIv", "-2")
    wait_oc(p, "o.ev.iv_shift === -0.02")
    p = tab.goto("/options", 2000)                                             # remembered in this browser
    assert oc(p, "o.state.symbol") == "ACME-DEMO" and oc(p, "o.state.legs.length") == 4
    wait_oc(p, "o.ev && o.ev.at === 'front_noon'")


def test_option_chain_redraws_keep_the_page_scrolled_where_it_was(tab):
    """Scrolled to the bottom and left there, a refresh mustn't pull the page back up (the panels are emptied and
    rebuilt on every refresh; measuring the graph's width meanwhile used to clamp the scroll position)."""
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    p.select_option("#ocTemplate", "double_diagonal")
    p.click("#ocFill")
    wait_oc(p, "o.ev && o.ev.status === 'ok' && o.state.legs.length === 4")
    p.add_style_tag(content="main.oc { overflow-anchor: none; }")   # as browsers that don't anchor the scroll (Firefox here)
    bottom = p.evaluate("(() => { const m = document.querySelector('main.oc'); m.scrollTop = m.scrollHeight; return m.scrollTop; })()")
    assert bottom > 100
    for step in range(3):                                                # a full refresh: chain, profile, structure, graph
        p.click("#ocStrip .oc-chip.active")
        p.select_option("#ocIv", ("-2", "0", "2")[step])
        wait_oc(p, f"o.ev.iv_shift === {(-2, 0, 2)[step] / 100}")
        p.evaluate("window.dispatchEvent(new Event('resize'))")
        p.wait_for_timeout(400)
        assert abs(p.evaluate("document.querySelector('main.oc').scrollTop") - bottom) <= 1, step


def test_option_chain_panels_scroll_under_a_fixed_expiry_strip(tab):
    """One column (chain, strike profile, structure, evaluation, grid) that scrolls on its own; the toolbar and the
    expiry strip stay."""
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    p.click("#ocFill")
    wait_oc(p, "o.ev && o.ev.status === 'ok'")
    lefts = p.evaluate("[...document.querySelectorAll('main.oc > .oc-box')].map((e) => Math.round(e.getBoundingClientRect().left))")
    assert len(lefts) == 5 and len(set(lefts)) == 1                                  # stacked, one column
    assert p.evaluate("document.documentElement.scrollHeight <= window.innerHeight")    # the page itself doesn't scroll
    strip = p.locator("#ocStrip").bounding_box()["y"]
    p.evaluate("document.querySelector('main.oc').scrollTop = 99999")
    p.wait_for_timeout(200)
    assert p.evaluate("document.querySelector('main.oc').scrollTop") > 0
    assert p.locator("#ocStrip").bounding_box()["y"] == strip and p.locator("#ocStrip").is_visible()
    assert p.locator("#ocGrid").is_visible()
    w = p.evaluate("document.querySelector('#ocGraph svg').getBoundingClientRect().width")
    assert abs(w - p.evaluate("document.querySelector('#ocGraph').clientWidth")) < 2          # the graph fills its panel


def test_option_chain_strike_profile(tab):
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    assert p.inner_text("#ocProfileTitle") == "Strike profile · Fri Oct 30"
    assert "active" in p.get_attribute("#ocProfileNear", "class")                 # Near by default
    near = p.locator("#ocProfile rect").count()
    p.click("#ocProfileAll")
    assert p.locator("#ocProfile rect").count() > near
    assert p.locator("#ocProfile .oc-gcall").count() and p.locator("#ocProfile .oc-gput").count()
    assert p.locator("#ocProfile .oc-pricel").count() == 1
    assert "most call gamma at" in p.inner_text("#ocProfileNote")
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)                               # remembered
    assert "active" in p.get_attribute("#ocProfileAll", "class")
    
    
def test_refreshes_leave_a_symbol_being_typed_alone(tab):
    """While a page polls for data (no collector here: the requests wait), what someone types in its symbol box stays
    until Enter; Escape puts the page's symbol back. Option chain and expected-move pages (the earnings page uses
    the same rule, but only polls when SEC_CONTACT is set)."""
    p = tab.goto("/options?symbol=QQQ", 1500)
    wait_oc(p, "o.state.symbol === 'QQQ'")
    p.click("#ocSym")
    p.fill("#ocSym", "SP")                                          # typing, not submitted
    p.wait_for_timeout(6000)                                        # two polls (every 2.5 s)
    assert p.input_value("#ocSym") == "SP"
    p.click("#ocRefresh")                                           # still kept after clicking elsewhere
    p.wait_for_timeout(3000)
    assert p.input_value("#ocSym") == "SP"
    p.focus("#ocSym")
    p.keyboard.press("Escape")
    assert p.input_value("#ocSym") == "QQQ"
    p.fill("#ocSym", "SPY")
    p.press("#ocSym", "Enter")
    wait_oc(p, "o.state.symbol === 'SPY'")
    p = tab.goto("/expected-move?symbols=NVDA&date=2026-10-30", 1500)
    p.fill("#emSyms", "AMZN LL")
    p.wait_for_timeout(7000)                                        # two polls (every 3 s)
    assert p.input_value("#emSyms") == "AMZN LL"
    p.keyboard.press("Escape")
    assert p.input_value("#emSyms") == "NVDA"


def test_option_chain_clicks_reverse_and_loss_limit(tab):
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    p.click("#ocClear")
    p.locator("#ocChain tr[data-strike='55'] td.oc-q").nth(1).click()        # the 55 call's ask: buy
    p.locator("#ocChain tr[data-strike='55'] td.oc-q").nth(1).click()        # again: 2 contracts
    p.locator("#ocChain tr[data-strike='51'] td.oc-q").nth(2).click()        # the 51 put's bid: sell
    wait_oc(p, "o.ev && o.ev.status === 'ok' && o.state.legs.length === 2")
    assert oc(p, "o.state.legs.map((l) => [l.qty, l.strike, l.right])") == [[2, 55, "C"], [-1, 51, "P"]]
    assert p.locator("#ocChain td.oc-buy").count() == 1 and p.locator("#ocChain td.oc-sell").count() == 1
    assert "Unlimited" in p.inner_text("#ocStats")                             # long calls
    p.click("#ocReverse")
    wait_oc(p, "o.state.legs[0].qty === -2")
    wait_oc(p, "o.ev && o.ev.max_loss.unlimited")
    p.fill("#ocStop", "-150")
    p.press("#ocStop", "Tab")
    wait_oc(p, "o.ev && o.ev.stop && o.ev.stop.above != null")
    assert "loss at" in p.inner_text("#ocStopText")
    p.locator("#ocLegs tr[data-leg] button.oc-x").first.click()               # remove a leg
    wait_oc(p, "o.state.legs.length === 1")


def test_option_chain_save_open_and_levels_on_the_chart(tab):
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    p.select_option("#ocTemplate", "iron_condor")
    p.click("#ocFill")
    wait_oc(p, "o.ev && o.ev.status === 'ok' && o.state.legs.length === 4")
    p.fill("#ocName", "ACME condor")
    p.click("#ocSaveForm button[type=submit]")
    p.wait_for_function("[...document.querySelectorAll('#ocSaved option')].some((o) => o.value === 'ACME condor')")
    p.click("#ocClear")
    wait_oc(p, "o.state.legs.length === 0")
    p.select_option("#ocSaved", "ACME condor")
    wait_oc(p, "o.state.legs.length === 4 && o.ev && o.ev.status === 'ok'")
    p.fill("#ocStop", "-100")
    p.press("#ocStop", "Tab")
    wait_oc(p, "o.ev.stop && o.ev.stop.below != null")
    p.click("#ocLevels")
    assert "6 lines drawn on every ACME-DEMO chart" in p.inner_text("#ocLevelsMsg")   # 2 short strikes, 2 breakevens, 2 limits
    p.click("#ocLevels")                                                      # again: replaces, doesn't add
    drawn = p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1'))['ACME-DEMO']")
    assert len(drawn) == 6 and {d["type"] for d in drawn} == {"hline"}
    assert sorted(d["label"] for d in drawn)[:2] == ["Breakeven", "Breakeven"]
    p.click("#ocDelete")
    p.wait_for_function("![...document.querySelectorAll('#ocSaved option')].some((o) => o.value === 'ACME condor')")


def test_structure_levels_show_on_a_chart(tab):
    p = tab.goto("/QQQs", 2500)
    p.evaluate("""import('/static/js/options/levels.js').then((m) => m.showOnChart('QQQ',
                  [{price: 691, label: 'Breakeven', color: '#8a8f98', style: 'dashed'}]))""")
    p = tab.goto("/QQQs", 2500)
    assert app_state(p, "a.panels[0].toolState.hline.length") == 1


# ---------------------------------------------------------------- Internals dashboard (2 charts over 4 internals)
def test_top_bar_drawing_tools_on_any_chart(tab):
    """The top bar's tools arm every chart: the next click on any chart (here a small one at the bottom of the 2-over-4
    Internals dashboard) places the drawing there, and the tool is then disarmed everywhere. Escape and the button
    again disarm it too, and a tool stays armed across a layout change."""
    p = tab.goto("/Internals", 3000)
    alert = p.locator("#drawTools button", has_text="Alert")
    alert.click()
    assert "active" in alert.get_attribute("class")
    assert app_state(p, "a.panels.every((x) => x.tool === 'alert')")
    p.locator(".panel").nth(4).locator(".chart").hover()                               # only the chart under the mouse
    assert p.locator(".panel").nth(4).locator(".phint").inner_text() == "Click to place an alert line"
    assert not p.locator(".panel").nth(0).locator(".phint").is_visible()
    box = p.locator(".panel").nth(4).locator(".chart").bounding_box()                   # TICK-NYSE
    p.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.4)
    p.wait_for_timeout(400)
    drawn = p.evaluate("JSON.parse(localStorage.getItem('intraday-charts.drawings.v1') || '{}')")
    assert [d["type"] for d in drawn.get("TICK-NYSE", [])] == ["alert"] and not drawn.get("QQQ")
    assert app_state(p, "a.panels.every((x) => !x.tool)") and "active" not in (alert.get_attribute("class") or "")
    p.locator("#drawTools button", has_text="Line").click()
    p.keyboard.press("Escape")
    assert app_state(p, "a.panels.every((x) => !x.tool)")
    p.locator("#drawTools button", has_text="Line").click()
    p.locator("#drawTools button", has_text="Line").click()                             # again: off
    assert app_state(p, "a.panels.every((x) => !x.tool)")
    p.locator("#drawTools button", has_text="Trend").click()
    p.select_option("#layout", "1x1")
    p.wait_for_timeout(800)
    assert app_state(p, "a.panels.every((x) => x.tool === 'trend')")


# ---------------------------------------------------------------- adding and removing charts and watch lists
def cell_symbols(p):
    return app_state(p, "a.cells.map((c) => c.symbol || 'watch list')")


def layout_action(p, cell, action):
    p.locator("#grid .panel").nth(cell).locator(".viewsbtn").click()
    box = p.locator("#savedMenu").bounding_box()                           # the menu stays inside the window
    assert box["y"] >= 0 and box["y"] + box["height"] <= p.viewport_size["height"]
    p.click(f"#savedMenu button[data-action='{action}']")
    p.wait_for_timeout(800)


def test_splitters_follow_the_grid_when_the_top_bar_grows(tab):
    """The top bar can grow after the charts are laid out (a late warning badge, wider fonts): the row splitter must
    move with the charts, or it sits on the bottom charts' headers and takes their clicks."""
    p = tab.goto("/Internals", 3000)
    gap = "(() => { const s = document.querySelector('.splitter.row').getBoundingClientRect(); "\
          "const top = window.__intraday.chart.cells[0].root.getBoundingClientRect(); return Math.abs(s.top - top.bottom); })()"
    assert p.evaluate(gap) < 4
    p.add_style_tag(content="header.toolbar { padding-bottom: 40px; }")
    p.wait_for_timeout(500)
    assert p.evaluate(gap) < 4
    p.locator("#grid .panel").nth(2).locator(".viewsbtn").click()              # not covered by the splitter
    assert p.locator("#savedMenu").is_visible()


def test_add_spy_far_left_turns_two_over_four_into_two_over_five(tab):
    p = tab.goto("/Internals", 3000)
    assert app_state(p, "a.layout") == "2/4"
    layout_action(p, 2, "chart-left")                                       # left of VOLD-NYSE: the bottom row's far left
    assert p.evaluate("document.activeElement === window.__intraday.chart.cells[2].symIn")    # type the symbol straight away
    p.keyboard.type("SPY")
    p.keyboard.press("Enter")
    wait_state(p, "a.cells[2].symbol === 'SPY' && a.cells[2].view")
    assert app_state(p, "a.layout") == "2/5" and p.locator("#layout option:checked").inner_text() == "2 over 5"
    assert cell_symbols(p) == ["QQQ", "SPY", "SPY", "VOLD-NYSE", "-VIX", "TICK-NYSE", "ADD-NYSE"]
    assert app_state(p, "[a.cells[2].tf, a.cells[2].price.type]") == app_state(p, "[a.cells[3].tf, a.cells[3].price.type]")  # a copy
    assert app_state(p, "JSON.stringify(a.prefs.sizes['2/5'].cols[1])") == "[1,1,1,1,1]"            # equal widths stay equal
    p = tab.goto("/Internals", 3000)                                         # kept in this browser
    assert app_state(p, "a.layout") == "2/5" and cell_symbols(p)[2] == "SPY"
    layout_action(p, 2, "remove")                                           # remove it: back to 2 over 4, with Undo
    assert app_state(p, "a.layout") == "2/4" and "SPY" not in cell_symbols(p)[2:]
    assert "SPY chart removed." in p.inner_text("#toasts")
    p.locator("#toasts .toastbtn").click()
    wait_state(p, "a.layout === '2/5' && a.cells[2].symbol === 'SPY'")


def test_add_a_watch_list_right_of_the_top_row_turns_two_over_four_into_three_over_four(tab):
    p = tab.goto("/Internals", 3000)
    layout_action(p, 1, "watchlist-right")
    assert app_state(p, "a.layout") == "3/4" and p.locator("#layout option:checked").inner_text() == "3 over 4"
    assert cell_symbols(p) == ["QQQ", "SPY", "watch list", "VOLD-NYSE", "-VIX", "TICK-NYSE", "ADD-NYSE"]
    wl = p.locator(".panel.wl")
    assert wl.locator("tr:first-child th").all_inner_texts() == ["Symbol", "Last", "Chg", "Chg %", "Volume", "High", "Low"]
    assert wl.locator("tr.wlr").evaluate_all("(rs) => rs.map((r) => r.dataset.symbol)") == \
        ["QQQ", "SPY", "VOLD-NYSE", "-VIX", "TICK-NYSE", "ADD-NYSE"]            # starts with the symbols on screen
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr td').length > 20")      # the numbers arrived
    assert wl.locator("tr[data-symbol='TICK-NYSE'] td").nth(3).inner_text() == "–"            # no % change for internals
    # a row click shows it on the active chart (the first); the arrow keys move through the list
    p.locator("#grid .panel").first.click(position={"x": 300, "y": 200})
    wl.locator("tr[data-symbol='SPY']").click()
    wait_state(p, "a.cells[0].symbol === 'SPY'")
    assert wl.locator("tr.sel").get_attribute("data-symbol") == "SPY"
    wl.locator(".wlbody").focus()
    p.keyboard.press("ArrowDown")
    wait_state(p, "a.cells[0].symbol === 'VOLD-NYSE'")
    # linked: it drives the charts of its colour instead (test_symbol_links covers the groups)
    set_link(p, 2, "blue")
    set_link(p, 1, "blue")
    wl.locator("tr[data-symbol='QQQ']").click()
    wait_state(p, "a.cells[1].symbol === 'QQQ'")
    assert app_state(p, "a.cells[0].symbol") == "VOLD-NYSE"
    # its own list
    wl.locator("button.wledit").click()
    wl.locator("textarea").fill("SPY, QQQ")
    wl.locator(".wleditor button[type=submit]").click()
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 2")
    p = tab.goto("/Internals", 3000)                                         # kept in this browser
    assert app_state(p, "a.layout") == "3/4"
    assert p.locator(".panel.wl tr.wlr").evaluate_all("(rs) => rs.map((r) => r.dataset.symbol)") == ["SPY", "QQQ"]
    layout_action(p, 2, "remove")
    assert app_state(p, "a.layout") == "2/4" and "Watch list removed." in p.inner_text("#toasts")


def set_link(p, cell, group):
    p.locator("#grid .panel").nth(cell).locator("select.linksel").select_option(group)


def test_symbol_links_are_colour_groups_across_charts_and_watch_lists(tab):
    p = tab.goto("/Internals", 3000)
    layout_action(p, 1, "watchlist-right")                                   # 3 over 4: QQQ, SPY, watch list, 4 internals
    for i, g in ((0, "red"), (3, "red"), (4, "red"), (1, "green"), (2, "green")):
        set_link(p, i, g)
    assert app_state(p, "a.cells.map((c) => c.link)") == ["red", "green", "green", "red", "red", "", ""]
    box = p.locator("#grid .panel").nth(0).locator(".linkbox")
    assert box.get_attribute("title").startswith("Linked: Red (2 others)")
    assert p.locator("#grid .panel").nth(5).locator(".linkbox").get_attribute("title").startswith("Not linked")
    # typing a symbol into a red chart changes every red chart, and nothing else
    sym = p.locator("#grid .panel").nth(3).locator("input.sym")
    sym.fill("SPY")
    sym.press("Enter")
    wait_state(p, "a.cells[0].symbol === 'SPY' && a.cells[4].symbol === 'SPY'")
    assert cell_symbols(p) == ["SPY", "SPY", "watch list", "SPY", "SPY", "TICK-NYSE", "ADD-NYSE"]
    # the green watch list drives the green chart only, and highlights what its group shows
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length > 3")
    wl.locator("tr[data-symbol='QQQ']").click()
    wait_state(p, "a.cells[1].symbol === 'QQQ'")
    assert app_state(p, "[a.cells[0].symbol, a.cells[3].symbol]") == ["SPY", "SPY"]
    sym = p.locator("#grid .panel").nth(1).locator("input.sym")               # and follows the green chart back
    sym.fill("SPY")
    sym.press("Enter")
    p.wait_for_function("document.querySelector('.panel.wl tr.sel')?.dataset.symbol === 'SPY'")
    # moved to red: a click now changes the three red charts
    set_link(p, 2, "red")
    wl.locator("tr[data-symbol='QQQ']").click()
    wait_state(p, "a.cells[0].symbol === 'QQQ' && a.cells[3].symbol === 'QQQ' && a.cells[4].symbol === 'QQQ'")
    assert app_state(p, "a.cells[1].symbol") == "SPY"
    # kept with the dashboard; a copy of a linked chart starts unlinked
    p = tab.goto("/Internals", 3000)
    assert app_state(p, "a.cells.map((c) => c.link)") == ["red", "green", "red", "red", "red", "", ""]
    layout_action(p, 0, "chart-right")
    assert app_state(p, "a.cells[1].link") == "" and app_state(p, "a.cells[0].link") == "red"


def col_box(wl, label):
    """A column's checkbox in the watch list's column chooser, by its exact label."""
    return wl.locator("label.wlcol").filter(has_text=re.compile(rf"^\s*{re.escape(label)}$")).locator("input")


def wl_rows(p):
    return p.locator(".panel.wl tr.wlr").evaluate_all("(rs) => rs.map((r) => r.dataset.symbol)")


def test_watch_list_tabs_show_named_app_wide_lists(tab, data):
    p = tab.goto("/QQQs", 1500)
    layout_action(p, 0, "watchlist-right")
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
    assert wl.locator("button.wltabx").count() == 0
    # + : a new list, "Watch list 2", typed straight away
    wl.locator("button.wltabadd").click()
    p.wait_for_function("document.querySelectorAll('.panel.wl button.wltab').length === 2")
    assert wl.locator(".wleditor").is_visible()
    wl.locator("textarea").fill("SPY QQQ")
    wl.locator(".wleditor button[type=submit]").click()
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 2")
    assert wl_rows(p) == ["SPY", "QQQ"] and wl.locator("button.wltab").all_inner_texts() == ["Watch list 1", "Watch list 2"]
    # renamed with a double-click: a unique name, app-wide
    wl.locator("button.wltab.on").dblclick()
    wl.locator("input.wltabname").fill("Watch list 1")
    wl.locator("input.wltabname").press("Enter")
    assert "already a watch list" in p.inner_text("#toasts")
    wl.locator("button.wltab.on").dblclick()
    wl.locator("input.wltabname").fill("Index ETFs")
    wl.locator("input.wltabname").press("Enter")
    p.wait_for_function("[...document.querySelectorAll('.panel.wl button.wltab')].map((b) => b.textContent).join() === 'Watch list 1,Index ETFs'")
    lists = json.loads((data / "user" / "config.json").read_text())["watchlists"]
    assert set(lists) == {"Watch list 1", "Index ETFs"} and lists["Index ETFs"]["symbols"] == ["SPY", "QQQ"]
    wl.locator("button.wltab").first.click()
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 1")
    assert wl_rows(p) == ["QQQ"]
    wl.locator("button.wltab").nth(1).click()
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 2")
    # the same list in another watch list panel: one list, edited in one place
    layout_action(p, 0, "watchlist-right")
    wl2 = p.locator(".panel.wl").first
    wl2.locator("select.wllist").select_option("Index ETFs")
    p.wait_for_function("document.querySelectorAll('.panel.wl')[0].querySelectorAll('tr.wlr').length === 2")
    wl2.locator("button.wledit").click()
    wl2.locator("textarea").fill("SPY QQQ NVDA")
    wl2.locator(".wleditor button[type=submit]").click()
    p.wait_for_function("document.querySelectorAll('.panel.wl')[1].querySelectorAll('tr.wlr').length === 3")
    layout_action(p, 1, "remove")
    # columns: per tab, from the registry; Defaults puts them back
    wl = p.locator(".panel.wl")
    wl.locator("button.wlcolbtn").click()
    col_box(wl, "Volume").uncheck()
    col_box(wl, "High").uncheck()
    assert wl.locator("tr:first-child th").all_inner_texts() == ["Symbol", "Last", "Chg", "Chg %", "Low"]
    assert wl.locator(".wlcols label:has-text('Qty')").count() == 0          # position columns: Holdings only
    # kept with the dashboard: tabs, the tab on view and its columns
    p = tab.goto("/QQQs", 2000)
    wl = p.locator(".panel.wl")
    assert wl.locator("button.wltab").all_inner_texts() == ["Watch list 1", "Index ETFs"]
    assert wl.locator("button.wltab.on").inner_text() == "Index ETFs"
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 3")
    assert wl.locator("tr:first-child th").all_inner_texts() == ["Symbol", "Last", "Chg", "Chg %", "Low"]
    wl.locator("button.wlcolbtn").click()
    wl.locator("button.wlcolreset").click()
    assert len(wl.locator("tr:first-child th").all_inner_texts()) == 7
    # closing a tab keeps the list; Undo brings the tab back
    wl.locator("button.wltabx").click()
    assert wl.locator("button.wltab").all_inner_texts() == ["Watch list 1"]
    assert "the watch list itself is kept" in p.inner_text("#toasts")
    assert "Index ETFs" in wl.locator("select.wllist option").all_inner_texts()
    p.locator("#toasts .toastbtn").last.click()
    p.wait_for_function("document.querySelectorAll('.panel.wl button.wltab').length === 2")
    assert wl.locator("button.wltab.on").inner_text() == "Index ETFs"


def test_when_the_watch_lists_cant_load_nothing_is_changed_and_the_page_says_why(tab, data):
    """The lists failed to load: a note in the corner says why, tabs don't claim their list was deleted, and no
    new list is made (a new watch list panel is refused) until they load."""
    p = tab.goto("/QQQs", 1500)
    layout_action(p, 0, "watchlist-right")
    p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
    p.route("**/api/watchlists", lambda r: r.fulfill(status=500, body='{"detail": "disk unavailable"}'))
    p.reload()
    p.wait_for_selector("#problems .problem")
    assert "Watch lists: disk unavailable" in p.inner_text("#problems")
    assert "couldn't be loaded" in p.inner_text(".panel.wl .wlfoot") and "deleted" not in p.inner_text(".panel.wl .wlfoot")
    layout_action(p, 0, "watchlist-right")
    p.wait_for_function("document.querySelector('#toasts')?.innerText.includes(\"couldn't be loaded\")")
    assert p.locator(".panel.wl").count() == 1
    assert set(json.loads((data / "user" / "config.json").read_text())["watchlists"]) == {"Watch list 1"}
    p.unroute("**/api/watchlists")
    p.reload()
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 1")
    assert p.locator("#problems .problem").count() == 0

def test_renaming_moves_a_list_deleting_removes_it_and_columns_drag(tab, data):
    p = tab.goto("/QQQs", 1500)
    layout_action(p, 0, "watchlist-right")
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
    # the name being typed is readable: light text on a dark field
    wl.locator("button.wltab.on").dblclick()
    box = wl.locator("input.wltabname")
    fg, bg = box.evaluate("(e) => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]")
    lum = lambda c: sum(int(x) for x in re.findall(r"\d+", c)[:3])                    # noqa: E731
    assert lum(fg) - lum(bg) > 300
    box.fill("Dashboard")
    box.press("Enter")
    p.wait_for_function("document.querySelector('.panel.wl button.wltab.on')?.textContent === 'Dashboard'")
    lists = json.loads((data / "user" / "config.json").read_text())["watchlists"]
    assert list(lists) == ["Dashboard"]                                                 # a move, not a copy
    assert wl.locator("select.wllist option").all_inner_texts().count("Watch list 1") == 0
    # columns: drag Low onto Last
    head = lambda: [x.split(" ")[0] for x in wl.locator("tr:first-child th").all_inner_texts()]   # noqa: E731
    assert head()[:3] == ["Symbol", "Last", "Chg"]
    wl.locator("th", has_text=re.compile(r"^Low$")).drag_to(wl.locator("th", has_text=re.compile(r"^Last$")))
    assert head() == ["Symbol", "Low", "Last", "Chg", "Chg", "Volume", "High"]
    p = tab.goto("/QQQs", 2000)                                                         # kept
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length >= 1")
    assert head()[1] == "Low"
    # delete from the list menu, asked first on the message
    wl.locator("select.wllist").select_option("@delete")
    assert 'Delete the watch list "Dashboard"' in p.inner_text("#toasts")
    p.locator("#toasts .toastbtn").last.click()
    p.wait_for_function("document.querySelector('.panel.wl .wlfoot')?.textContent.includes('was deleted')")
    assert json.loads((data / "user" / "config.json").read_text())["watchlists"] == {}


def test_the_config_page_edits_lists_columns_and_study_defaults(tab, data):
    p = tab.goto("/QQQs", 1500)
    layout_action(p, 0, "watchlist-right")
    p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
    p = tab.goto("/config?tab=lists", 1500)
    assert p.locator(".dashsel").input_value() == "\u0000config"
    # watch lists: rename and delete
    row = p.locator("#cfgLists tr[data-name='Watch list 1']")
    row.locator("button.cfg-rename").click()
    row.locator("input.cfg-input").fill("Core")
    row.locator("input.cfg-input").press("Enter")
    p.wait_for_selector("#cfgLists tr[data-name='Core']")
    p.locator("#cfgLists tr[data-name='Core'] button.cfg-delete").click()
    p.locator("#cfgLists tr[data-name='Core'] button.cfg-delete").click()               # the second click deletes
    p.wait_for_selector("#cfgLists tr[data-name='Core']", state="detached")
    # watch list columns: add Gap %, move it up, and new tabs start with them
    p.click(".cfg-tabs button[data-sec=columns]")
    p.click(".cfg-avail button[data-id=gap_pct]")
    p.wait_for_selector(".cfg-col[data-id=gap_pct]")
    for _ in range(6):
        p.click(".cfg-col[data-id=gap_pct] .cfg-up")
    p.wait_for_function("document.querySelectorAll('.cfg-col')[1]?.dataset.id === 'gap_pct'")       # at once
    saved = lambda: json.loads((data / "user" / "config.json").read_text())["watch_columns"]["quote"][:2]   # noqa: E731
    for _ in range(50):                                                    # the saves go one after another
        if saved() == ["symbol", "gap_pct"]:
            break
        p.wait_for_timeout(100)
    assert saved() == ["symbol", "gap_pct"]
    # study defaults: SMA length 21 for new studies
    p.click(".cfg-tabs button[data-sec=studies]")
    p.fill("#cfgFind", "simple")
    p.click("button.cfg-study[data-type=sma]")
    p.fill("#cfgStudyForm [data-key=length]", "21")
    p.click("#cfgStudySave")
    p.wait_for_function("document.querySelector('#cfgStudyMsg').textContent.startsWith('Saved')")
    assert "•" in p.locator("button.cfg-study[data-type=sma]").inner_text()
    p = tab.goto("/QQQs", 2000)
    assert app_state(p, "a.catalog.find((s) => s.type === 'sma').params.find((x) => x.key === 'length').default") == 21
    wl = p.locator(".panel.wl")
    wl.locator("button.wltabadd").click()
    p.wait_for_function("document.querySelectorAll('.panel.wl button.wltab').length === 2")
    assert [x.split(" ")[0] for x in wl.locator("tr:first-child th").all_inner_texts()][:2] == ["Symbol", "Gap"]
    p = tab.goto("/config", 1500)
    p.click(".cfg-tabs button[data-sec=studies]")
    p.click("button.cfg-study[data-type=sma]")
    p.click("#cfgStudyReset")
    p.wait_for_function("!document.querySelector('button.cfg-study[data-type=sma]').textContent.includes('•')")


def test_a_thinkorswim_link_says_why_it_cant_be_read(tab):
    p = tab.goto("/QQQs", 1500)
    layout_action(p, 0, "watchlist-right")
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
    wl.locator("button.wledit").click()
    wl.locator("textarea").fill("HTTP://TOS.MX/!FDKFI2MJ")
    wl.locator(".wleditor button[type=submit]").click()
    p.wait_for_function("document.querySelector('.panel.wl .wleditor .muted').textContent.includes('thinkorswim')")
    assert wl.locator(".wleditor").is_visible() and wl_rows(p) == ["QQQ"]          # nothing changed, no "HTTP"


def test_watch_list_columns_graphics_sorting_and_heat(tab):
    p = tab.goto("/Internals", 3000)
    layout_action(p, 1, "watchlist-right")
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr td').length > 20")
    wl.locator("button.wlcolbtn").click()
    sections = wl.locator(".wlcolsec > b").all_inner_texts()
    assert sections == ["Price and volume", "The day so far", "Daily history", "Earnings and options", "Study values"]
    assert wl.locator(".wlcols label.wlcol").filter(has_text="Qty").count() == 0           # Holdings only
    for label in ("Gap %", "Day range", "Today", "Rel vol", "52w range", "vs VWAP", "ATR zone", "SMA 50 (5m)"):
        col_box(wl, label).check()
    wl.locator(".wlcols input[aria-label='Shade Chg % by value']").check()
    wl.locator("button.wlcolbtn").click()
    p.wait_for_function("""() => {                       // the fetch with every chosen column (each tick fetches)
      const r = document.querySelector('.panel.wl tr[data-symbol=QQQ]');
      return r && r.querySelector('svg[aria-label*="52-week range"]') && r.querySelector('svg[aria-label*="today"]')
        && [...r.querySelectorAll('td.state')].length === 2 && /\\d/.test(r.lastElementChild.textContent);
    }""")
    qqq = wl.locator("tr[data-symbol='QQQ']")
    assert qqq.locator("svg[aria-label*=\"today's range\"]").count() == 1                    # day-range bar
    assert qqq.locator("svg[aria-label*='52-week range']").count() == 1
    assert qqq.locator("svg polyline").count() >= 1                                          # sparkline
    assert re.match(r"^\d+\.\d\d×$", qqq.locator("svg text").first.text_content())          # rel vol data bar
    states = qqq.locator("td.state").all_inner_texts()
    assert any("VWAP" in x for x in states) and not any(w in " ".join(states).lower() for w in ("buy", "sell"))
    assert "background" in (qqq.locator("td.wlchg").nth(1).get_attribute("style") or "")      # heat on Chg %
    tick = wl.locator("tr[data-symbol='TICK-NYSE'] td").all_inner_texts()
    assert tick[headers(wl).index("Gap %")] == "–"                                           # no gap for an internal
    # sorting: by Chg % up, down, then the list's own order
    own = wl_rows(p)
    th = wl.locator("th").filter(has_text=re.compile(r"^Chg %"))
    th.click()
    pct = [float(x.replace("−", "-").rstrip("%")) for x in wl.locator("tr.wlr").evaluate_all(
        f"(rs) => rs.map((r) => r.children[{headers(wl).index('Chg %')}].textContent)") if x != "–"]
    assert pct == sorted(pct) and "▴" in th.inner_text()
    th.click()
    assert wl_rows(p) != own and "▾" in th.inner_text()
    th.click()
    assert wl_rows(p) == own
    th.click()
    p = tab.goto("/Internals", 3000)                                          # kept: columns, heat and sort
    wl = p.locator(".panel.wl")
    p.wait_for_function("document.querySelector('.panel.wl tr[data-symbol=QQQ] svg')")
    assert "Day range" in headers(wl) and "▴" in wl.locator("th.on").inner_text()


def headers(wl):
    return [re.sub(r" [▴▾]$", "", x) for x in wl.locator("tr:first-child th").all_inner_texts()]


def test_a_holdings_tab_shows_positions_with_cost_value_and_pnl(tab, data):
    from types import SimpleNamespace as NS

    import positions as reader
    from app import positions, store
    old, store.DATA_DIR = store.DATA_DIR, data
    try:
        held = [NS(account="U1234567", contract=NS(symbol=s, secType=t, currency="USD"), position=q, avgCost=c)
                for s, q, c, t in (("QQQ", 100, 600.0, "STK"), ("SPY", -20, 650.0, "STK"), ("NVDA", 10, 150.0, "STK"),
                                   ("QQQ", 2, 310.0, "OPT"))]
        positions.write(reader.read_positions(NS(reqPositions=lambda: held)))
        p = tab.goto("/QQQs", 1500)
        layout_action(p, 0, "watchlist-right")
        wl = p.locator(".panel.wl")
        p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
        wl.locator("select.wllist").select_option("@new-holdings")
        p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 3")
        assert wl_rows(p) == ["QQQ", "SPY", "NVDA"]                               # biggest first
        assert wl.locator("tr:first-child th").all_inner_texts() == \
            ["Symbol", "Qty", "Avg cost", "Last", "Mkt value", "Unrl P/L", "Unrl P/L %", "Day P/L", "Chg %"]
        assert wl.locator("button.wltab.on").inner_text() == "Watch list 2"
        qqq = wl.locator("tr[data-symbol='QQQ'] td").all_inner_texts()
        last = float(qqq[3])
        assert qqq[1] == "100" and qqq[2] == "600.00"
        assert qqq[4] == f"{100 * last:,.2f}"
        assert qqq[5] == ("+" if last > 600 else "−") + f"{abs(100 * (last - 600)):,.2f}"
        spy = wl.locator("tr[data-symbol='SPY'] td").all_inner_texts()
        assert spy[1] == "-20" and spy[4].startswith("−")                        # a short: negative value
        nvda = wl.locator("tr[data-symbol='NVDA'] td").all_inner_texts()
        assert nvda[1] == "10" and nvda[3] == "–"                                 # no bars cached: quantity only
        foot = wl.locator(".wlfoot").inner_text()
        assert "Value" in foot and "Unrl" in foot and "1 other position" in foot and "Fetch 1 from TWS" in foot
        wl.locator("tr[data-symbol='SPY']").click()                               # a row still drives the chart
        wait_state(p, "a.cells[0].symbol === 'SPY'")
        wl.locator("button.wlcolbtn").click()
        assert wl.locator(".wlcols label:has-text('Cost basis')").count() == 1
    finally:
        store.DATA_DIR = old


def test_a_watch_list_from_a_finviz_screen(tab, data):
    from app import list_sources, store
    old, store.DATA_DIR = store.DATA_DIR, data
    try:
        address = "https://elite.finviz.com/screener.ashx?v=111&f=ta_topgainers&auth=NOT-A-REAL-TOKEN"
        ref = list_sources.normalize("finviz", address)
        list_sources.write(ref, {"status": "ok", "symbols": ["QQQ", "SPY", "AAPL"], "total": 3, "fetched": time.time()})
        p = tab.goto("/QQQs", 1500)
        layout_action(p, 0, "watchlist-right")
        wl = p.locator(".panel.wl")
        p.wait_for_function("document.querySelector('.panel.wl button.wltab')?.textContent === 'Watch list 1'")
        wl.locator("select.wllist").select_option("@new-finviz")              # a new list: its address first
        assert wl.locator(".wleditor").is_visible()
        wl.locator("textarea").fill("https://example.com/screener.ashx?f=x")
        wl.locator(".wleditor button[type=submit]").click()
        p.wait_for_function("document.querySelector('.panel.wl .wleditor .muted').textContent.includes('finviz.com')")
        wl.locator("textarea").fill(address)
        wl.locator(".wleditor button[type=submit]").click()
        p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 3")
        assert "Asking FinViz" in wl.locator(".wlfoot").inner_text()
        reqs = [json.loads(f.read_text()) for f in (data / "control" / "requests").glob("*.json")]
        assert [r["list"] for r in reqs if r.get("list")] == [ref]               # the collector was asked
        assert "auth" not in json.dumps(app_state(p, "a.cells[1].config()"))     # the token isn't kept
        lists = json.loads((data / "user" / "config.json").read_text())["watchlists"]
        assert lists["Watch list 2"]["source"] == "finviz" and "auth" not in json.dumps(lists)
        assert wl.locator("button.wltab.on").inner_text() == "Watch list 2"
        assert wl.locator("a.wlfeedlabel").get_attribute("href") == "https://finviz.com/screener.ashx?v=111&f=ta_topgainers"
        # the collector's answer arrives: the list follows
        list_sources.write(ref, {"status": "ok", "symbols": ["NVDA", "QQQ"], "total": 2, "fetched": time.time() + 1})
        p.wait_for_function("[...document.querySelectorAll('.panel.wl tr.wlr')].map((r) => r.dataset.symbol).join() === 'NVDA,QQQ'",
                            timeout=15000)
        assert "fetched" in wl.locator(".wlfoot").inner_text()
        p = tab.goto("/QQQs", 2000)                                             # kept with the dashboard
        p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length === 2")
        assert p.locator(".panel.wl select.wllist").input_value() == "Watch list 2"
    finally:
        store.DATA_DIR = old


def test_layout_limits(tab):
    p = tab.goto("/QQQs", 2000)
    p.locator("#grid .panel").first.locator(".viewsbtn").click()
    assert p.locator("#savedMenu button[data-action='remove']").is_disabled()            # the last chart stays
    p.keyboard.press("Escape")
    for _ in range(5):
        layout_action(p, 0, "chart-right")
    assert app_state(p, "a.layout") == "6/1" or app_state(p, "a.cells.length") == 6
    p.locator("#grid .panel").first.locator(".viewsbtn").click()
    b = p.locator("#savedMenu button[data-action='chart-right']")
    assert b.is_disabled() and "at most 6" in b.get_attribute("title")


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
    p = tab.goto("/config?tab=dashboards", 1500)
    assert "Market internals" in " ".join(p.locator("#newStart option").all_inner_texts())
    p.fill("#newName", "Breadth")
    p.select_option("#newStart", "template:internals")
    p.click("button:has-text('Create and open')")
    p.wait_for_url("**/Breadth")
    p.wait_for_timeout(3000)
    assert app_state(p, "a.layout") == "2/4" and app_state(p, "a.panels.length") == 6


def test_dashboard_from_top_and_bottom_counts(tab):
    p = tab.goto("/config?tab=dashboards", 1500)
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
    tab.page.set_viewport_size({"width": WIDE, "height": 850})    # the top bar on one line, whatever the fonts
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



def test_numbers_and_times_are_written_the_same_way_on_every_page(tab):
    """app/static/js/format.js: the one place numbers, money, percentages and ages become text."""
    p = tab.goto("/QQQs", 500)
    out = p.evaluate("""async () => {
        const f = await import("/static/js/format.js");
        return {
            price: [f.price(691.234), f.price(25040000), f.price(null)],
            signed: [f.signed(1.25), f.signed(-0.4, 1), f.signed(0), f.signed(undefined)],
            pct: [f.pct(1.234), f.signedPct(-2.5), f.signedPct(0.04, 2), f.pct(NaN)],
            dollars: [f.dollars(1250.4), f.dollars(-80), f.dollars(-0.4), f.dollars(-1234567, { compact: true }), f.dollars(null)],
            amount: [f.amount(-12345.6), f.amount(1999.5, 0)],
            ago: [f.ago(45), f.ago(720), f.ago(10800), f.ago(null)],
            other: [f.fmtMin(570), f.fixed(0.456), f.expiryDate("20261030"), f.expiryDate("")],
        };
    }""")
    assert out == {
        "price": ["691.23", "25.04M", "–"],
        "signed": ["+1.25", "−0.4", "0.00", "–"],
        "pct": ["1.2%", "−2.5%", "+0.04%", "–"],
        "dollars": ["+$1,250", "−$80", "$0", "−$1.23M", "–"],
        "amount": ["12,345.60", "2,000"],
        "ago": ["45 s ago", "12 min ago", "3 h ago", "never"],
        "other": ["09:30", "0.46", "Fri, Oct 30", ""],
    }


def test_a_refresh_keeps_the_legend_watch_list_and_chain_on_screen(tab, data):
    """Stepping Replay redraws everything, but keeps the elements under the pointer (a legend row and its buttons, a
    watch list's tabs, headers and rows) and updates them in place, so a click, drag or double-click that spans a
    refresh still lands. Same for the option chain's rows."""
    p = tab.goto("/QQQs", 2000)
    p.evaluate("window.__intraday.chart.panels[0].addStudy('vwap')")
    wait_state(p, "a.panels[0].view.studies && Object.keys(a.panels[0].view.studies).length === 1")
    layout_action(p, 0, "watchlist-right")
    p.wait_for_function("document.querySelectorAll('.panel.wl tr.wlr').length >= 1")
    p.click("#stepBack")
    p.wait_for_timeout(1200)
    keep = """() => { window._kept = ['.panel .leg', '.panel .leg button', '.panel.wl button.wltab', '.panel.wl th',
                      '.panel.wl tr.wlr'].map((s) => document.querySelector(s)); }"""
    p.evaluate(keep)
    last = p.locator(".panel.wl tr.wlr td").nth(1).inner_text()
    p.click("#stepBack")
    p.wait_for_function(f"document.querySelectorAll('.panel.wl tr.wlr td')[1].innerText !== {json.dumps(last)}")
    assert p.evaluate("window._kept.every((e) => e && e.isConnected)")
    # a double-click spanning a refresh still renames the tab
    p.locator(".panel.wl button.wltab").dblclick()
    assert p.locator(".panel.wl input.wltabname").count() == 1
    p.keyboard.press("Escape")
    # the option chain: its rows stay while the chain is drawn again
    p = tab.goto("/options?symbol=ACME-DEMO", 2000)
    wait_oc(p, "o.view && o.view.status === 'ok'")
    p.evaluate("() => { window._row = document.querySelector('#ocChain tbody tr[data-strike]'); }")
    p.click("#ocStrip .oc-chip[data-expiry='20261106']")
    wait_oc(p, "o.state.expiry === '20261106'")
    p.click("#ocStrip .oc-chip[data-expiry='20261030']")
    wait_oc(p, "o.state.expiry === '20261030'")
    assert p.evaluate("window._row.isConnected")


def test_the_config_page_makes_and_sets_up_backtesting_accounts(tab, data):
    p = tab.goto("/config", 1500)
    p.click(".cfg-tabs button[data-sec=accounts]")
    assert "No backtesting accounts yet" in p.inner_text("#cfgAcct")
    # the defaults for new accounts: $30,000, long only
    p.fill("#cfgAcctForm [data-key=start_cash]", "30000")
    p.uncheck("#cfgAcctForm [data-key=shorting]")
    p.click("#cfgAcctSave")
    p.wait_for_function("document.querySelector('#cfgAcctMsg').textContent.startsWith('Saved the defaults')")
    p.click("#cfgAcctNew")
    p.wait_for_selector("#cfgAcct tr[data-name='Account 1']")
    row = p.locator("#cfgAcct tr[data-name='Account 1']")
    assert "$30,000" in row.inner_text() and "long only" in row.inner_text()
    assert p.locator("#cfgAcctFor").input_value() == "Account 1"                # the new account's settings on view
    # one account's own settings
    p.fill("#cfgAcctForm [data-key=slippage]", "0.03")
    p.click("#cfgAcctSave")
    p.wait_for_function("document.querySelector('#cfgAcctMsg').textContent === 'Saved \"Account 1\".'")
    acct = json.loads((data / "user" / "config.json").read_text())["backtest_accounts"]["Account 1"]
    assert acct["settings"]["slippage"] == 0.03 and acct["settings"]["shorting"] is False and acct["start_cash"] == 30000
    # rename, then delete with two clicks
    row.locator("button.cfg-rename").click()
    p.fill("#cfgAcct input.cfg-input", "Morning practice")
    p.press("#cfgAcct input.cfg-input", "Enter")
    p.wait_for_selector("#cfgAcct tr[data-name='Morning practice']")
    row = p.locator("#cfgAcct tr[data-name='Morning practice']")
    row.locator("button.danger").click()
    assert row.locator("button.danger").inner_text() == "Delete? Yes"
    row.locator("button.danger").click()
    p.wait_for_function("document.querySelector('#cfgAcct').innerText.includes('No backtesting accounts yet')")
    p.screenshot(path="/tmp/cfg-accounts.png", full_page=True)


def test_a_chart_shows_a_signal_strategys_entries_and_exits(tab, data):
    """A chart's ≡ menu, Signals: a signal strategy's entries and exits as arrows on the chart's bars, with a strip
    naming it; in Replay only what had happened before the cursor; × takes it off. Signals only: nothing is traded."""
    p = tab.goto("/QQQs", 2000)
    p.evaluate("""async () => {
        const post = (u, b) => fetch(u, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
        const vw = {study: {type: 'vwap', params: {}, output: 'vwap'}};
        await post('/api/signal-rules', {name: 'Up', rule: {conditions: [{a: {price: 'close'}, op: 'crosses_above', b: vw}], when: 'A'}});
        await post('/api/signal-rules', {name: 'Down', rule: {conditions: [{a: {price: 'close'}, op: 'crosses_below', b: vw}], when: 'A'}});
        await post('/api/signal-strategies', {name: 'Crosses', strategy: {tf: 1, buy: 'Up', short: 'Down', qty: 10, exits: {stop: 0.5, target: 1}}});
    }""")
    p.locator(".panel").first.locator(".viewsbtn").click()
    p.wait_for_selector("#savedMenu select.sigsel option[value='Crosses']", state="attached")
    p.select_option("#savedMenu select.sigsel", "Crosses")
    p.keyboard.press("Escape")
    p.wait_for_function("document.querySelector('.panel .sigbar .siginfo')?.innerText.includes('trade')", timeout=20000)

    def cursor(minute):                                                  # Replay, at that minute of the day
        p.evaluate(f"""() => {{ const c = document.querySelector('#cursor'); c.value = {minute};
                              c.dispatchEvent(new Event('input')); c.dispatchEvent(new Event('change')); }}""")
        wait_state(p, f"a.panels[0].view && a.panels[0].view.cursor === {minute}")
        wait_state(p, f"(a.panels[0].sigShown || '').includes('|{minute}|')", 20000)
    cursor(16 * 60)                                                      # the whole session
    full = app_state(p, "a.panels[0].markers.length")
    assert full >= 2 and app_state(p, "a.panels[0].markerApi.markers().length") == full
    assert app_state(p, "a.panels[0].config().signals") == "Crosses" and "Crosses" in p.inner_text(".panel .sigbar")
    assert app_state(p, "a.panels[0].markers.every((m) => m.shape.startsWith('arrow'))")
    # in Replay, at 10:00: only the arrows before it
    cursor(600)
    assert "so far" in p.inner_text(".panel .sigbar")
    assert app_state(p, "a.panels[0].markers.length") < full
    assert app_state(p, "a.panels[0].markers.every((m) => Math.floor((m.time % 86400) / 60) < 600)")
    p.screenshot(path="/tmp/signals.png")
    # kept with the window; × takes it off
    p = tab.goto("/QQQs", 2000)
    assert app_state(p, "a.panels[0].signals") == "Crosses"
    p.locator(".panel .sigbar button.sigoff").click()
    assert p.locator(".panel .sigbar").is_hidden() and app_state(p, "a.panels[0].config().signals") is None
    wait_state(p, "!a.panels[0].markerApi || a.panels[0].markerApi.markers().length === 0")


def test_a_trade_panel_sends_orders_to_the_ibkr_paper_account(tab):
    """The trade panel next to the chart follows its symbol, shows what TWS says for the paper account (position,
    working orders, fills) and sends Buy, cancel and flatten as actions (app/live_orders.py; the server's answers
    stand in for TWS here). Orders go only in Live and only when the server says they can."""
    import json as _json
    p = tab.goto("/QQQs", 2000)
    view = {"on": False, "ready": False, "why_not": "Orders are off. Set LIVE_ORDERS=paper in .env", "account": None,
            "paper": False, "max_shares": 1000, "symbol": "QQQ", "position": {"symbol": "QQQ", "qty": 0, "avg": None},
            "orders": [], "fills": [], "updated": 1}
    sent = []

    def live(route):
        if route.request.method == "POST":
            body = _json.loads(route.request.post_data)
            sent.append(body)
            if body["action"] == "order":
                view["orders"] = [{"id": 101, "symbol": "QQQ", "side": "buy", "type": "market", "qty": body["order"]["qty"],
                                   "price": None, "parent": None, "status": "Submitted"}]
            route.fulfill(content_type="application/json", body=_json.dumps({"ok": True, "message": f"{body['action']} sent", "view": view}))
        else:
            route.fulfill(content_type="application/json", body=_json.dumps(view))
    p.route("**/api/live**", live)
    layout_action(p, 0, "trade-right")
    tp = p.locator(".panel.tp")
    assert tp.count() == 1 and tp.locator(".tpsym").inner_text() == "QQQ"
    p.wait_for_function("document.querySelector('.panel.tp .tpnotice').innerText.includes('LIVE_ORDERS=paper')")
    assert tp.locator("button.tpbuy").is_disabled() and "Orders off" in tp.locator(".tpacct").inner_text()
    # TWS logged into the paper account, in Live: Buy sends a market order of 25
    view.update(on=True, ready=True, why_not=None, account="DU…4567", paper=True)
    p.evaluate("""() => { const a = window.__intraday.chart; a.live = true;
                          const v = a.panels[0].view; if (!v.bars.length) v.bars.push({ time: 1, close: 500 }); }""")
    wait_state(p, "a.cells.some((c) => c.live && c.live.ready)", 10000)
    p.wait_for_function("!document.querySelector('.panel.tp button.tpbuy').disabled", timeout=10000)
    assert "IBKR paper DU…4567" in tp.locator(".tpacct").inner_text()
    tp.locator(".tpqty input").fill("25")
    tp.locator("button.tpbuy").click()
    p.wait_for_selector(".panel.tp .tporders tr[data-id='101']")
    assert sent[-1] == {"action": "order", "symbol": "QQQ", "order": {"side": "buy", "qty": 25, "type": "market"}}
    assert p.locator(".toast", has_text="IBKR paper DU…4567: order sent").count() == 1
    # a fill shows, with a message; × cancels the working order; Flatten
    view["position"] = {"symbol": "QQQ", "qty": 25, "avg": 499.5}
    view["fills"] = [{"symbol": "QQQ", "side": "buy", "qty": 25, "price": 499.5, "time": 1793800000, "order": 101}]
    p.wait_for_function("document.querySelector('.panel.tp .tpinfo').innerText.includes('Long 25 @ 499.50')", timeout=10000)
    p.wait_for_selector(".toast:has-text('IBKR paper: BUY 25 QQQ @ 499.50')")
    tp.locator(".tporders .tpx").first.click()
    p.wait_for_timeout(300)
    assert sent[-1] == {"action": "cancel", "symbol": "QQQ", "order_id": 101}
    tp.locator("button.tpflat").click()
    p.wait_for_timeout(300)
    assert sent[-1] == {"action": "flatten", "symbol": "QQQ"}
    p.screenshot(path="/tmp/trade-panel.png")
    # out of Live: no orders
    p.evaluate("window.__intraday.chart.live = false")
    p.wait_for_function("document.querySelector('.panel.tp button.tpbuy').disabled", timeout=10000)
    assert "turn Live on" in tp.locator(".tpnotice").inner_text()
    # kept with the window, and removed like any cell
    p.unroute("**/api/live**")
    p = tab.goto("/QQQs", 2000)
    assert app_state(p, "a.configs.some((c) => c.kind === 'trade')")
    layout_action(p, 1, "remove")
    assert p.locator(".panel.tp").count() == 0


def test_a_rule_reads_the_opening_range_high(tab, data):
    """Levels by name in the rule form: Close crosses above Session levels' OR high, with a 5-minute range."""
    p = tab.goto("/config?tab=rules", 1500)
    p.select_option("#ppRule", "\u0000new")
    p.locator("#ppRuleForm button.pp-add").first.click()
    b = p.locator("#ppRuleForm .pp-operand").nth(1)
    b.locator("select").nth(1).select_option("session_levels")
    b = p.locator("#ppRuleForm .pp-operand").nth(1)
    assert b.locator("select").nth(2).locator("option").all_inner_texts()[:4] == ["OR high", "OR low", "PM high", "PM low"]
    assert b.locator("select").nth(2).input_value() == "level:OR high"
    b.get_by_label("Session levels (premarket, opening range, HOD/LOD, profile) Opening range length").select_option("5")
    assert b.locator("input.pp-num").count() == 0                       # no settings that don't change the level
    p.click("#ppRuleSave")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.startsWith('Saved')")
    name = p.inner_text("#ppRuleMsg").split('"')[1]
    st = json.loads((data / "user" / "config.json").read_text())["signal_rules"][name]["conditions"][0]["b"]["study"]
    assert st["type"] == "session_levels" and st["output"] == "level:OR high" and st["params"]["or_minutes"] == "5"
    p.locator("#ppRuleDelete").click()
    p.locator("#ppRuleDelete").click()                                     # tidy up for the tests after
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.startsWith('Deleted')")


def test_a_rule_says_vzo_is_above_minus_40_and_rising(tab, data):
    """Direction in the rule form: A: VZO is above -40; B: VZO is rising (than 1 bar before); and a value some bars
    ago on either side of a comparison."""
    p = tab.goto("/config?tab=rules", 1500)
    p.select_option("#ppRule", "\u0000new")
    for _ in range(3):
        p.click("#ppRuleForm button:has-text('+ condition')")
    cond = lambda x: p.locator(f"#ppRuleForm .pp-cond[data-letter={x}]")   # noqa: E731  (drawn again after each change)
    for x in "AB":
        cond(x).locator(".pp-operand").nth(0).locator("select").first.select_option("study")
        cond(x).locator(".pp-operand").nth(0).locator("select").nth(1).select_option("vzo")
        assert cond(x).get_by_label("Volume Zone Oscillator (VZO) Length").count() == 1
        assert cond(x).get_by_label("Volume Zone Oscillator (VZO) Draw as").count() == 0     # how it's drawn: not offered
    cond("A").get_by_label("Condition A: how it compares").select_option("above")
    cond("A").locator(".pp-operand").nth(1).locator("select").first.select_option("value")
    cond("A").locator(".pp-operand").nth(1).locator("input.pp-num").fill("-40")
    cond("B").get_by_label("Condition B: how it compares").select_option("rising")
    assert cond("B").locator(".pp-operand").count() == 1 and cond("B").get_by_label("Condition B: over how many bars").input_value() == "1"
    cond("C").get_by_label("Condition C: how it compares").select_option("above")          # Close above the previous high
    cond("C").locator(".pp-operand").nth(1).locator("select").first.select_option("high")
    cond("C").locator(".pp-operand").nth(1).get_by_label("Bars ago").fill("1")
    cond("C").locator(".pp-operand").nth(1).get_by_label("Bars ago").press("Tab")
    assert p.locator("#ppRuleForm select.xed-leaf option").all_inner_texts()[:3] == [
        "A: Volume Zone Oscillator: VZO is above -40", "B: Volume Zone Oscillator: VZO is rising", "C: Close is above High 1 bar ago"]
    p.click("#ppRuleSave")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.startsWith('Saved')")
    name = p.inner_text("#ppRuleMsg").split('"')[1]
    c = json.loads((data / "user" / "config.json").read_text())["signal_rules"][name]["conditions"]
    assert c[0]["op"] == "above" and c[0]["b"] == {"value": -40.0} and c[0]["a"]["study"]["type"] == "vzo"
    assert c[1] == {"a": c[0]["a"], "op": "rising", "bars": 1}
    assert c[2]["b"] == {"price": "high", "ago": 1}
    p.click("#ppRuleDelete")
    p.click("#ppRuleDelete")                                                 # tidy up for the tests after
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.startsWith('Deleted')")


def test_recommended_rules_are_added_and_a_strategy_trails_by_atr(tab, data):
    """Config: tick a recommended rule (it brings the rules it's made of), add the rest, then a strategy buying on
    them with a 2 x ATR(14) trailing stop."""
    p = tab.goto("/config?tab=rules", 1500)
    p.click("#ppPresets summary")
    assert p.locator("#ppPresetList input[value='Price above ORH']").count() == 1
    p.check("#ppPresetList input[value='Bull trend']")
    p.click("#ppPresetAdd")
    p.wait_for_function("document.querySelector('#ppPresetMsg').textContent.startsWith('Added 3')")
    assert p.locator("#ppPresetList input[value='Price above VWAP']").is_disabled()           # added with Bull trend
    p.click("#ppPresetAll")
    p.wait_for_function("document.querySelector('#ppPresets summary').dataset.left === 'all added'")
    saved = json.loads((data / "user" / "config.json").read_text())["signal_rules"]
    assert {"Price above ORH", "Price below ORL", "VZO above -40 and rising", "Bull trend"} <= set(saved)
    assert saved["Bull trend"]["when"] == '"Price above VWAP" AND "EMA 9 above EMA 21"'
    p.wait_for_function("[...document.querySelectorAll('#ppRule option')].some((o) => o.value === 'Price above ORH')")
    p.click(".cfg-tabs button[data-sec=strategies]")
    p.select_option("#ppStrat", "\u0000new")
    p.fill("#ppStratForm [data-part=buy] input.xed-text", '"Bull trend" AND "VZO above -40 and rising"')
    p.wait_for_selector("#ppStratForm [data-part=buy] select.xed-leaf")
    p.fill("#ppStratForm .pp-row:has(> .pp-label:text-is('Stop')) input", "")
    p.fill("#ppStratForm input[aria-label='ATR trailing stop: multiple']", "2")
    p.click("#ppStratSave")
    p.wait_for_function("document.querySelector('#ppStratMsg').textContent.startsWith('Saved')")
    name = p.inner_text("#ppStratMsg").split('"')[1]
    st = json.loads((data / "user" / "config.json").read_text())["signal_strategies"][name]
    assert st["exits"]["trail_atr"] == 2.0 and st["exits"]["atr_length"] == 14 and "stop" not in st["exits"]
    p.select_option("#ppStrat", name)
    p.click("#ppStratDelete")
    p.click("#ppStratDelete")                                              # tidy up for the tests after
    p.wait_for_function("document.querySelector('#ppStratMsg').textContent.startsWith('Deleted')")


def test_a_rule_is_a_nested_true_false_expression_typed_or_built(tab, data):
    """(A OR B) AND NOT (C OR (A AND B)), typed; the groups show it; changing the groups changes the text; removing a
    condition takes it out and moves the letters after it up. Then a rule that uses rules, and a loop refused."""
    p = tab.goto("/config?tab=rules", 1500)
    p.select_option("#ppRule", "\u0000new")
    for _ in range(3):
        p.click("#ppRuleForm button:has-text('+ condition')")
    assert p.input_value("#ppRuleForm input.xed-text") == "A AND B AND C"
    p.fill("#ppRuleForm input.xed-text", "(A or B) and !(C OR (A AND B))")
    p.wait_for_function("document.querySelectorAll('#ppRuleForm .xed-group').length === 4")        # the top, and three inside
    p.locator("#ppRuleForm input.xed-text").blur()
    assert p.input_value("#ppRuleForm input.xed-text") == "(A OR B) AND NOT (C OR (A AND B))"     # tidied
    p.fill("#ppRuleForm input.xed-text", "(A OR B) AND (C")
    p.wait_for_function("document.querySelector('#ppRuleForm .xed-msg').textContent.includes(\"Expected ')'\")")
    p.fill("#ppRuleForm input.xed-text", "(A OR B) AND NOT (C OR (A AND B))")
    p.wait_for_function("!document.querySelector('#ppRuleForm .xed-msg').textContent")
    p.locator("#ppRuleForm .xed-group.or .xed-head .xed-not input").first.check()                    # NOT on the first group
    assert p.input_value("#ppRuleForm input.xed-text") == "NOT (A OR B) AND NOT (C OR (A AND B))"
    p.locator("#ppRuleForm .pp-cond[data-letter=B] button.pp-x").click()                              # B goes, C becomes B
    assert p.input_value("#ppRuleForm input.xed-text") == "NOT A AND NOT (B OR A)"
    p.click("#ppRuleSave")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.startsWith('Saved')")
    first = p.inner_text("#ppRuleMsg").split('"')[1]
    assert json.loads((data / "user" / "config.json").read_text())["signal_rules"][first]["when"] == "NOT A AND NOT (B OR A)"
    # a rule of rules, built with the groups
    p.select_option("#ppRule", "\u0000new")
    p.click("#ppRuleForm .xed-groups button:has-text('+ condition or rule')")
    p.locator("#ppRuleForm select.xed-leaf").select_option(label=f"Rule: {first}")
    p.click("#ppRuleSave")
    p.wait_for_function(f"(t => t.startsWith('Saved') && !t.includes('{first}'))(document.querySelector('#ppRuleMsg').textContent)")
    second = p.inner_text("#ppRuleMsg").split('"')[1]
    assert json.loads((data / "user" / "config.json").read_text())["signal_rules"][second]["when"] == f'"{first}"'
    p.select_option("#ppRule", first)                                     # the first can't use the second: a loop
    p.fill("#ppRuleForm input.xed-text", f'NOT A AND "{second}"')
    p.wait_for_function("!document.querySelector('#ppRuleForm .xed-msg').textContent")
    p.click("#ppRuleSave")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.includes(\"can't use itself\")")
    p.click("#ppRuleDelete")
    p.click("#ppRuleDelete")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.includes('is used by')")   # the second uses it
    for n in (second, first):                                              # tidy up for the tests after
        p.select_option("#ppRule", n)
        p.click("#ppRuleDelete")
        p.click("#ppRuleDelete")
        p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.startsWith('Deleted')")


def test_config_writes_a_rule_the_backtesting_page_backtests_it_and_a_chart_shows_its_signals(tab, data):
    p = tab.goto("/backtesting", 1500)
    p.evaluate("() => fetch('/api/backtest-accounts', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
               "body: JSON.stringify({name: 'Tests', start_cash: 100000})})")
    days = [d for s in p.evaluate("fetch('/api/meta').then((r) => r.json())")["symbols"] if s["symbol"] == "QQQ" for d in s["days"]]
    p = tab.goto("/backtesting", 1500)
    assert p.locator(".dashsel").input_value() == "\u0000backtesting"
    assert p.locator(".cfg-tabs button").count() == 0 and "No backtests yet" in p.inner_text("#ppRuns")   # set-up lives in Config
    # a rule, in Config: the close crosses above VWAP; a strategy buys on it, 10 shares, $0.50 stop, $1 target
    p = tab.goto("/config?tab=rules", 1500)
    p.select_option("#ppRule", "\u0000new")
    p.click("#ppRuleSave")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent.includes('needs conditions')")   # none yet: refused
    p.click("#ppRuleForm button:has-text('+ condition')")
    assert p.input_value("#ppRuleForm input.xed-text") == "A"                  # every condition, until it's changed
    p.click("#ppRuleSave")
    p.wait_for_function("document.querySelector('#ppRuleMsg').textContent === 'Saved \"Rule 1\".'")
    r = json.loads((data / "user" / "config.json").read_text())["signal_rules"]["Rule 1"]
    assert r["when"] == "A" and r["conditions"][0]["op"] == "crosses_above" and r["conditions"][0]["b"]["study"]["type"] == "vwap"
    p.click(".cfg-tabs button[data-sec=strategies]")
    p.select_option("#ppStrat", "\u0000new")
    p.fill("#ppStratForm [data-part=buy] input.xed-text", '"Rule 1"')
    p.wait_for_selector("#ppStratForm [data-part=buy] select.xed-leaf")
    p.locator("#ppStratForm .pp-row", has_text="Shares").locator("input").fill("10")
    p.click("#ppStratSave")
    p.wait_for_function("document.querySelector('#ppStratMsg').textContent === 'Saved \"Strategy 1\".'")
    st = json.loads((data / "user" / "config.json").read_text())["signal_strategies"]["Strategy 1"]
    assert st["buy"] == '"Rule 1"' and st["short"] == "" and st["qty"] == 10 and st["exits"]["stop"] == 0.5
    # backtest defaults, in Config: the Backtesting page's Run form starts with them
    p.click(".cfg-tabs button[data-sec=backtests]")
    p.wait_for_function("document.querySelector('#cfgBtAccount').options.length === 2")
    p.fill("#cfgBtSymbol", "qqq")
    p.select_option("#cfgBtAccount", "Tests")
    p.fill("#cfgBtBase", "1")
    assert p.locator("#cfgBtMissing").input_value() == "fetch"          # the built-in default
    p.select_option("#cfgBtMissing", "skip")
    p.fill("#cfgBtWorkers", "2")
    p.click("#cfgBtSave")
    p.wait_for_function("document.querySelector('#cfgBtMsg').textContent.startsWith('Saved')")
    assert json.loads((data / "user" / "config.json").read_text())["backtesting"]["backtest"] == \
        {"symbol": "QQQ", "account": "Tests", "baseline_runs": 1, "missing": "skip", "workers": 2}
    # backtest it over the cached days
    p = tab.goto("/backtesting", 1500)
    assert [p.locator(x).input_value() for x in ("#ppRunRule", "#ppRunSymbol", "#ppRunAccount", "#ppRunBase")] == ["Strategy 1", "QQQ", "Tests", "1"]
    assert p.locator("#ppRunMissing").input_value() == "skip"
    p.fill("#ppRunFrom", min(days))
    p.fill("#ppRunTo", max(days))
    p.click("#ppRun button[type=submit]")
    p.wait_for_selector("#ppReport .pp-stats", timeout=120000)
    assert "Random entries (1 runs)" in p.inner_text("#ppReport") and p.locator("#ppReport .pp-trades tr").count() > 1
    # the run's log: what it did, day by day
    p.click("#ppReport .pp-tabs button[data-tab=log]")
    assert "long signal" in p.inner_text("#ppReport .pp-log") and "filled: BUY" in p.inner_text("#ppReport .pp-log")
    assert p.locator("#ppReport .pp-logline.day").count() == len(days)
    p.select_option("#ppReport .pp-pane select", "day")
    assert p.locator("#ppReport .pp-logline").count() == len(days)
    # a trade's day on a chart: its entries and exits as arrows, with the rule's study (VWAP); a study added there
    # stays for the next day reviewed
    p.click("#ppReport .pp-tabs button[data-tab=trades]")
    first_day = p.locator("#ppReport button.pp-daylink").first.inner_text()
    p.locator("#ppReport button.pp-daylink").first.click()
    frame = p.wait_for_selector(".pp-review iframe").content_frame()
    frame.wait_for_function(f"window.__intraday?.chart?.panels?.[0]?.view?.day === '{first_day}'", timeout=20000)
    a = "window.__intraday.chart.panels[0]"
    assert frame.evaluate(f"{a}.markers.length") >= 2 and frame.evaluate(f"{a}.markerApi.markers().length") >= 2
    assert frame.evaluate(f"{a}.markers[0].shape") == "arrowUp" and frame.evaluate(f"{a}.studies.map((s) => s.type)") == ["vwap"]
    assert "Backtest review" in frame.inner_text(".reviewbar") and frame.locator("#layoutsBtn").is_hidden()
    frame.evaluate(f"{a}.addStudy('rsi')")
    frame.wait_for_timeout(500)
    p.keyboard.press("Escape")
    assert p.locator(".pp-review").count() == 0
    p.locator("#ppReport button.pp-daylink").last.click()
    frame = p.wait_for_selector(".pp-review iframe").content_frame()
    frame.wait_for_function("window.__intraday?.chart?.panels?.[0]?.view && window.__intraday.chart.panels[0].studies.length === 2", timeout=20000)
    assert frame.evaluate(f"{a}.studies.map((s) => s.type)") == ["vwap", "rsi"]
    p.click(".pp-review-x")
    assert p.locator("#ppReport button.pp-save").count() == 0                   # saving into an account is gone (#83)
    p.screenshot(path="/tmp/backtesting-page.png", full_page=True)
    # the same strategy on any chart, by address: its arrows on that day
    p = tab.goto(f"/QQQs?symbol=QQQ&day={first_day}&signals=Strategy%201", 2500)
    wait_state(p, "a.panels[0].markers && a.panels[0].markers.length > 0")
    assert app_state(p, "a.panels[0].symbol") == "QQQ" and "Strategy 1" in p.inner_text(".panel .sigbar")
    assert "?" not in p.url                                                     # the address is tidied


def test_backtest_queue_delete_acknowledgement_and_interrupted_report(tab, data):
    """New states remain pollable and render without assuming a completed report exists."""
    import json
    p = tab.page
    run = {"id": "queuedjob", "strategy_name": "Queued strategy", "symbol": "QQQ", "start": "2026-10-19",
           "end": "2026-10-23", "status": "queued", "done": 0, "total": 5, "log": []}
    state = {"exists": True}

    def handle(route):
        if route.request.method == "DELETE":
            run["status"] = "deleting"
            route.fulfill(status=202, content_type="application/json", body=json.dumps({"deleting": True, "runs": [run]}))
        elif route.request.url.endswith("/queuedjob"):
            route.fulfill(content_type="application/json", body=json.dumps(run))
        else:
            route.fulfill(content_type="application/json", body=json.dumps({"runs": [run] if state["exists"] else []}))
    p.route("**/api/backtests", handle)
    p.route("**/api/backtests/queuedjob", handle)
    tab.goto("/backtesting", 100)
    p.locator("#ppRuns .pp-report-btn").click()
    p.wait_for_function("document.querySelector('#ppReport').textContent.includes('Queued: waiting')")
    p.locator("#ppRuns button.danger").click()
    assert "Stop and delete? Yes" in p.inner_text("#ppRuns")
    p.locator("#ppRuns button.danger").click()
    p.wait_for_function("document.querySelector('#ppRuns').textContent.includes('stopping and deleting')")
    state["exists"] = False
    p.wait_for_function("document.querySelector('#ppRuns').textContent.includes('No backtests yet')")
    run.update(status="interrupted", error="Worker stopped; submit a new run.")
    state["exists"] = True
    tab.goto("/backtesting", 100)
    p.locator("#ppRuns .pp-report-btn").click()
    p.wait_for_function("document.querySelector('#ppReport').textContent.includes('Worker stopped')")
