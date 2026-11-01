/* One chart: its settings, the chart itself, fetching its view and drawing it. Drawing studies, legends, drawings and the header are in their own modules, mixed in below. */
import { describeWait, fillDays, refreshAll, requestData } from "./data.js";
import { renderActiveList } from "./dialogs/studies.js";
import { DrawingTools } from "./drawings.js";
import { fmtValue } from "./format.js";
import { updateBanner } from "./grid.js";
import { Legends } from "./legends.js";
import { publish } from "./links.js";
import { PanelHeader } from "./panel-header.js";
import { ChartPrimitives as PR } from "./primitives.js";
import { PriceTypes as PT } from "./pricetypes.js";
import { app, defaultSymbol, defaultsFor, normStudies, save } from "./state.js";
import { StudyLayers, attachOutputs } from "./study-layers.js";
import { COLORS } from "./styles.js";
import { $, LWC, api, cleanSymbol, clone, el, mixParts, uid } from "./util.js";
import { defaultSpan, findTf, isPeriod } from "./timeframes.js";

export class Panel {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.link = cfg.link || "";                           // symbol-link group (links.js)
    this.symbol = cfg.symbol; this.tf = findTf(cfg.tf) ? cfg.tf : 3; this.days = cfg.days || 1;
    this.spans = { ...(cfg.spans || {}) };               // months shown, per daily / weekly / monthly duration
    this.price = PT.normalize(cfg.price);                // {type, params}
    this.studies = normStudies(cfg.studies);
    this.view = null; this.fitted = false; this.rendered = {}; this.layoutSig = ""; this.levelPrices = [];
    this.times = []; this.tool = null; this.pending = null;
    this.lastCursor = null; this.inflight = 0;
    this.buildDom();
    this.buildChart();
  }

  config() { return { id: this.id, link: this.link, symbol: this.symbol, tf: this.tf, days: this.days, spans: { ...this.spans }, price: clone(this.price), studies: this.studies }; }

  // daily, weekly or monthly candles (from daily prices) rather than intraday ones
  isPeriod() { return isPeriod(this.tf); }
  // what the range menu shows: days for intraday candles, months for periods
  range() { return this.isPeriod() ? (this.spans[this.tf] || defaultSpan(this.tf)) : this.days; }
  setRange(v) { if (this.isPeriod()) this.spans = { ...this.spans, [this.tf]: v }; else this.days = v; }
  // seconds per candle
  step() { return this.view?.step || (this.isPeriod() ? 86400 : this.tf * 60); }

  // small panels drop level names from the lines (the price-axis labels stay) to keep the chart readable
  compact() { return this.chartEl.clientWidth < 420 || this.chartEl.clientHeight < 360; }

  buildChart() {
    const chart = this.chart = LWC.createChart(this.chartEl, {
      autoSize: true, localization: { locale: "en-US" },
      layout: { background: { color: "transparent" }, textColor: COLORS.text, fontSize: 11, attributionLogo: false,
                panes: { separatorColor: "#2a313b", separatorHoverColor: "#3a4350", enableResize: true } },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: "#262c35", scaleMargins: { top: 0.06, bottom: 0.06 } },
      // keep the same stretch of time on screen when a chart is resized or maximized
      timeScale: { borderColor: "#262c35", timeVisible: true, secondsVisible: false, rightOffset: 2,
                   lockVisibleTimeRangeOnResize: true },
      crosshair: { mode: LWC.CrosshairMode.Normal },
    });
    // the anchor: never drawn, it carries the studies, levels and drawings and spans the time axis.
    // The price itself is drawn by the chosen price type, on its own series.
    const clear = "rgba(0,0,0,0)";
    this.candles = chart.addSeries(LWC.CandlestickSeries, {
      upColor: clear, downColor: clear, borderVisible: false, wickVisible: false, priceLineVisible: false, lastValueVisible: false,
      autoscaleInfoProvider: (original) => {
        const r = original();
        if (!r || !app.prefs.fitLevels || !this.levelPrices.length) return r;
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...this.levelPrices),
                                     maxValue: Math.max(r.priceRange.maxValue, ...this.levelPrices) } };
      },
    });
    this.bg = new PR.Background(); this.candles.attachPrimitive(this.bg);
    attachOutputs(this);       // what study outputs share on this chart (outputs/)
    this.attachTools();        // what the drawing tools draw with (tools/)
    this.watermark = LWC.createTextWatermark(chart.panes()[0], { horzAlign: "center", vertAlign: "center",
      lines: [{ text: "", color: "rgba(255,255,255,0.05)", fontSize: 44 }] });
    this.priceView = null;
    this.applyPrice();

    // drawing clicks come from the DOM: the chart library merges two quick clicks into a double-click
    this.chartEl.addEventListener("click", (e) => {
      if (!this.tool) return;
      const r = this.chartEl.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      if (x > this.chart.timeScale().width() || y > this.chart.panes()[0].getHeight()) return;   // price axis or lower panes
      this.onClick({ point: { x, y }, paneIndex: 0, time: this.chart.timeScale().coordinateToTime(x) });
    }, true);
    chart.subscribeCrosshairMove((p) => this.onCrosshair(p));
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(() => this.drawOverlay()));
    this.resizeObs = new ResizeObserver(() => requestAnimationFrame(() => { this.drawOverlay(); this.drawLegends(); }));
    this.resizeObs.observe(this.chartEl);
    this.chartEl.addEventListener("mouseup", () => requestAnimationFrame(() => { this.drawOverlay(); this.drawLegends(); }));
  }

  destroy() { this.dead = true; this.resizeObs.disconnect(); this.chart.remove(); this.root.remove(); }

  fillSymbols() {
    this.symbol = this.symbol || defaultSymbol();
    this.symIn.value = this.symbol;
    this.symIn.classList.remove("bad");
    this.fitSymbolBox();
  }

  // the symbol box grows for long names (VOLD-NYSE), measured in the font this browser uses; ordinary tickers
  // keep the standard width
  fitSymbolBox() {
    const box = this.symIn;
    box.style.width = "";
    if (box.scrollWidth > box.clientWidth) box.style.width = (box.scrollWidth + box.offsetWidth - box.clientWidth + 2) + "px";
  }

  // linked: the change came from another cell of this chart's link group (links.js), so it isn't passed on
  setSymbol(raw, linked = false) {
    const sym = cleanSymbol(raw);
    if (!sym) {
      this.symIn.classList.add("bad");
      this.symIn.title = `"${raw}" isn't a stock or ETF symbol`;
      return;
    }
    this.symIn.classList.remove("bad");
    this.symIn.value = sym;
    if (sym === this.symbol) return;
    this.symbol = sym; this.fitSymbolBox(); this.fitted = false; this.layoutSig = ""; this.view = null;
    save(); updateBanner();
    if (!linked) publish(this, sym);
    if (app.live) requestData([sym]);
    if (!app.live && fillDays()) refreshAll(); else this.refresh();
  }

  showLinked(sym) { this.setSymbol(sym, true); }

  // ---------------------------------------------------------------- data
  async refresh() {
    if (!this.symbol || !app.day) return;
    const req = ++this.inflight;
    const body = { symbol: this.symbol, day: app.day, tf: this.tf, days: this.days, span: this.isPeriod() ? this.range() : null,
                   cursor: app.live ? null : app.cursor,
                   studies: this.studies.filter((s) => s.visible).map(({ uid, type, params }) => ({ uid, type, params })) };
    let v;
    try { v = await api("/api/view", body); }
    catch (e) {
      if (req !== this.inflight || this.dead) return;
      if (e.message.startsWith("No cached bars")) {
        this.waiting = true; this.view = null; this.fitted = false;
        this.chartEl.style.visibility = "hidden"; this.title.textContent = "";
        requestData([this.symbol]);
        this.showWaiting();
      } else this.showMsg("Error: " + e.message);
      return;
    }
    if (req !== this.inflight || this.dead) return;
    this.waiting = false; this.chartEl.style.visibility = "";
    this.showMsg(null);
    this.view = v;
    this.render(v);
  }

  // the price, drawn by the chosen price type through the common interface
  applyPrice() {
    if (this.priceView) this.priceView.destroy();
    this.priceView = PT.create(this.chart, this.price);
    if (this.view) this.priceView.setData(this.view.bars);
  }
  setPrice(price) {
    this.price = price; this.priceSel.value = price.type;
    this.applyPrice(); save();
  }

  showMsg(text) { this.msg.hidden = !text; this.msg.textContent = text || ""; }
  showWaiting() { if (this.waiting) this.showMsg(describeWait(this.symbol, app.day)); }

  // ---------------------------------------------------------------- rendering
  render(v) {
    const keep = this.fitted ? this.chart.timeScale().getVisibleLogicalRange() : null;
    const blank = v.future.map((t) => ({ time: t }));
    this.candles.setData([...v.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })), ...blank]);
    this.priceView.setData(v.bars);
    this.times = [...v.bars.map((b) => b.time), ...v.future];
    this.renderStudies(v);
    // symbols the studies read besides this chart's (e.g. SPY for relative strength): fetched, or streamed in Live
    const needs = [...new Set(Object.values(v.studies).flatMap((r) => r.needs || []))].filter((s) => s !== v.symbol);
    if (needs.length) requestData(needs);
    if (v.period !== this.periodAxis) {                // dates only on daily, weekly and monthly charts
      this.periodAxis = v.period;
      this.chart.applyOptions({ timeScale: { timeVisible: !v.period } });
    }
    this.bg.set({ bars: v.bars, future: v.future, shade: app.prefs.extShade, separators: v.days > 1 && !v.period });
    this.renderDrawings();
    this.checkAlerts(v);
    const opened = this.preFit && v.bars.some((b) => b.session === "rth");   // 09:30 arrived in Live
    if (!this.fitted || opened) { this.defaultView(v); this.fitted = true; }
    else if (keep) this.chart.timeScale().setVisibleLogicalRange(keep);
    const last = v.bars[v.bars.length - 1];
    // values in the millions (VOLD) read as 25.04M on the axis and in the title; prices keep the library's format
    const big = v.bars.some((b) => Math.abs(b.close) >= 1e6);
    if (big !== this.bigValues) { this.bigValues = big; this.chart.applyOptions({ localization: { priceFormatter: big ? fmtValue : undefined } }); }
    this.title.innerHTML = "";
    this.title.append(el("b", null, `${v.symbol} ${v.range_label} ${v.tf_label}`),
                      el("span", last && last.close >= v.bars[0].open ? "up" : "down", " " + (big ? fmtValue(v.price) : v.price.toFixed(2))));
    this.watermark.applyOptions({ lines: [{ text: v.symbol.replace("-DEMO", " (synthetic)"), color: "rgba(255,255,255,0.05)", fontSize: 44 }] });
    requestAnimationFrame(() => { this.drawOverlay(); this.drawLegends(); });
  }

  defaultView(v) {
    const total = v.bars.length + v.future.length;
    if (v.period) {                                    // daily and longer: the whole range shown
      this.preFit = false;
      this.chart.timeScale().setVisibleLogicalRange({ from: -1, to: total + 1 });
      return;
    }
    const firstDay = v.shown_days[0];
    const firstRth = v.bars.findIndex((b) => b.session === "rth" && b.day === firstDay);
    if (firstRth < 0) {
      // premarket, before the first regular-session bar: show from the first bar through 10:30
      // (the open and its first hour), so today's bars start at the left edge with room to the right
      const minute = (t) => Math.floor((t % 86400) / 60);   // chart times are ET wall-clock as UTC
      const at = v.future.findIndex((t) => minute(t) >= 10 * 60 + 30);
      const to = v.bars.length + (at < 0 ? v.future.length : at);
      this.chart.timeScale().setVisibleLogicalRange({ from: -1, to: Math.max(to, v.bars.length + 5) });
      this.preFit = true;
      return;
    }
    this.preFit = false;
    const lead = Math.round(45 / v.tf);
    this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(firstRth - lead, 0), to: total + 1 });
  }

  onCrosshair(p) {
    this.previewAt(p);                                // a drawing being placed follows the mouse
    if (!p.sourceEvent || !app.prefs.sync) return;   // ignore moves we set ourselves
    for (const other of app.panels) if (other !== this) other.showCrosshairAt(p.time);
  }

  showCrosshairAt(t) {
    const bars = this.view?.bars;
    if (t == null || !bars || !bars.length) { this.chart.clearCrosshairPosition(); return; }
    let lo = 0, hi = bars.length - 1;
    if (t < bars[0].time || t >= bars[hi].time + this.step()) { this.chart.clearCrosshairPosition(); return; }
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (bars[mid].time <= t) lo = mid; else hi = mid; }
    const b = bars[hi].time <= t ? bars[hi] : bars[lo];
    this.chart.setCrosshairPosition(b.close, b.time, this.candles);
  }

  // ---------------------------------------------------------------- coordinates
  // x of any time, also between bars; null past the last bar
  xAt(t) {
    const ts = this.times;
    if (!ts.length) return null;
    const scale = this.chart.timeScale();
    let lo = 0, hi = ts.length - 1;
    if (t <= ts[0]) return scale.timeToCoordinate(ts[0]);
    if (t >= ts[hi]) return null;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (ts[mid] <= t) lo = mid; else hi = mid; }
    const x0 = scale.timeToCoordinate(ts[lo]), x1 = scale.timeToCoordinate(ts[hi]);
    if (x0 == null || x1 == null) return x0;
    return x0 + (x1 - x0) * (t - ts[lo]) / (ts[hi] - ts[lo]);
  }

  // like xAt, but extrapolates beyond the loaded bars (for trend lines drawn on other days or timeframes)
  xAtExt(t) {
    const ts = this.times;
    if (!ts.length || t == null) return null;
    const scale = this.chart.timeScale(), spacing = scale.options().barSpacing || 6, step = this.step();
    if (t < ts[0]) { const x = scale.timeToCoordinate(ts[0]); return x == null ? null : x - (ts[0] - t) / step * spacing; }
    if (t > ts[ts.length - 1]) { const x = scale.timeToCoordinate(ts[ts.length - 1]); return x == null ? null : x + (t - ts[ts.length - 1]) / step * spacing; }
    return this.xAt(t) ?? scale.timeToCoordinate(ts[ts.length - 1]);
  }

  // ---------------------------------------------------------------- studies
  addStudy(type, params = {}) { this.studies.push({ uid: uid(), type, visible: true, params: { ...defaultsFor(type), ...params } }); this.changed(); }
  removeStudy(id) { this.studies = this.studies.filter((s) => s.uid !== id); this.changed(); }
  toggleStudy(id) { const s = this.studies.find((x) => x.uid === id); if (s) { s.visible = !s.visible; this.changed(); } }
  changed() { save(); this.refresh(); if (!$("studiesDlg").hidden) renderActiveList(); }
}

// the parts of a chart kept in their own modules
mixParts(Panel, PanelHeader, StudyLayers, Legends, DrawingTools);
