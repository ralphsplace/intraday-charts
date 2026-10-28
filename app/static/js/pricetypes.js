/* Price types: how a chart draws the price. Each one stands alone and supports the same small interface,
   so the chart panel never needs to know which one it is showing.

   A price type is registered with
       define({ id, name, description, params, create })
     params   its settings, in the same shape as a study's (key, label, type, default, section, ...);
              the chart's settings dialog shows them, and "Defaults" puts them back
     create(chart, params) -> { setData(bars), destroy() }
              draws the bars (each {time, open, high, low, close, session}) on the chart, using its own series

   The chart's own candle series is not a price type: it stays on the chart, invisible, as the anchor that
   studies, levels, drawings and the time axis are attached to.

   Exported as PriceTypes = { list, get, defaults, normalize, create }.
*/
import { LWC } from "./util.js";
import { param } from "./params.js";
import { LINE_STYLES, LINE_STYLE_LABELS, dash, lineStyle as lwcStyle, rgba } from "./styles.js";
const EXT_ALPHA = 0.45;          // extended-hours bars are drawn at this opacity when dimmed
const UP = "#26a69a", DOWN = "#ef5350";

const P = (key, label, type, def, section, extra = {}) => param(key, label, type, def, { section, ...extra });
const lineStyle = (def) => P("style", "Line type", "choice", def, "Line", { options: LINE_STYLES, labels: LINE_STYLE_LABELS });
const thickness = (key, label, def, section) => P(key, label, "int", def, section, { min: 1, max: 6 });
const COLOR_BY = ["Open to close", "Previous close"];


const TYPES = [];
const define = (t) => { TYPES.push(t); return t; };

// ---------------------------------------------------------------- candle and bar drawing (one custom series)
// Draws candles or OHLC bars from rows {time, open, high, low, close, up, ext}: "up" picks the colour and
// "ext" marks an extended-hours bar. The settings decide fill, outline, wick, thickness and body width.
class BarsRenderer {
  constructor(mode, p) { this.mode = mode; this.p = p; this.data = null; }
  update(data) { this.data = data; }
  draw(target, toY) {
    target.useBitmapCoordinateSpace((s) => this.paint(s.context, s.horizontalPixelRatio, s.verticalPixelRatio, toY));
  }
  paint(ctx, hr, vr, toY) {
    const d = this.data;
    if (!d || !d.bars.length || !d.visibleRange) return;
    const p = this.p;
    for (let i = d.visibleRange.from; i < d.visibleRange.to; i++) {
      const bar = d.bars[i], r = bar.originalData;
      if (r.close === undefined) continue;
      const yo = toY(r.open), yh = toY(r.high), yl = toY(r.low), yc = toY(r.close);
      if (yo == null || yh == null || yl == null || yc == null) continue;
      const color = r.up ? p.up_color : p.down_color;
      ctx.globalAlpha = r.ext && p.ext_dim ? EXT_ALPHA : 1;
      ctx.fillStyle = color; ctx.strokeStyle = color;
      const x = Math.round(bar.x * hr);
      if (this.mode === "bars") this.ohlc(ctx, x, d.barSpacing * hr, [yo, yh, yl, yc].map((y) => Math.round(y * vr)), hr);
      else this.candle(ctx, r, x, d.barSpacing * hr, [yo, yh, yl, yc].map((y) => Math.round(y * vr)), hr);
    }
    ctx.globalAlpha = 1;
  }
  candle(ctx, r, x, spacing, [yo, yh, yl, yc], hr) {
    const p = this.p;
    const body = Math.max(1, Math.round(spacing * p.body_pct / 100));
    const left = x - Math.floor(body / 2);
    const top = Math.min(yo, yc), bottom = Math.max(Math.max(yo, yc), top + 1);
    const rising = r.close >= r.open;
    const filled = rising ? p.up_fill : p.down_fill;
    if (p.wick) {
      const ww = Math.max(1, Math.round(p.wick_width * hr));
      const wl = x - Math.floor(ww / 2);
      ctx.fillRect(wl, yh, ww, Math.max(0, top - yh));          // above the body
      ctx.fillRect(wl, bottom, ww, Math.max(0, yl - bottom));   // below it: an unfilled body stays empty
    }
    if (filled) ctx.fillRect(left, top, body, bottom - top);
    if (!filled || p.outline) {
      const bw = Math.min(Math.max(1, Math.round(p.outline_width * hr)), Math.ceil(body / 2));
      ctx.fillRect(left, top, body, bw); ctx.fillRect(left, bottom - bw, body, bw);
      ctx.fillRect(left, top, bw, bottom - top); ctx.fillRect(left + body - bw, top, bw, bottom - top);
    }
  }
  ohlc(ctx, x, spacing, [yo, yh, yl, yc], hr) {
    const p = this.p;
    const w = Math.max(1, Math.round(p.width * hr));
    const tick = Math.max(w, Math.round(spacing * 0.4));
    const l = x - Math.floor(w / 2);
    ctx.fillRect(l, yh, w, Math.max(w, yl - yh));
    if (p.open_tick) ctx.fillRect(l - tick, yo - Math.floor(w / 2), tick, w);
    ctx.fillRect(l + w, yc - Math.floor(w / 2), tick, w);
  }
}

class BarsView {
  constructor(mode, p) { this.r = new BarsRenderer(mode, p); }
  renderer() { return this.r; }
  update(data) { this.r.update(data); }
  priceValueBuilder(row) { return [row.low, row.high, row.close]; }
  isWhitespace(row) { return row.close === undefined; }
  defaultOptions() { return { ...LWC.customSeriesDefaultOptions, priceLineVisible: false, lastValueVisible: true }; }
  destroy() {}
}

// the "up" flag: rising from the bar's open, or from the previous bar's close
function rows(bars, colorBy) {
  let prev = null;
  return bars.map((b) => {
    const up = colorBy === "Previous close" && prev != null ? b.close >= prev : b.close >= b.open;
    prev = b.close;
    return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, up, ext: b.session !== "rth" };
  });
}

function heikinAshi(bars) {
  let po = null, pc = null;
  return bars.map((b) => {
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = po == null ? (b.open + b.close) / 2 : (po + pc) / 2;
    po = open; pc = close;
    return { ...b, open, close, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close) };
  });
}

// a price type drawn by the custom series above; "transform" turns the bars into the rows it draws
function barsType(mode, transform) {
  return (chart, p) => {
    const series = chart.addCustomSeries(new BarsView(mode, p), { priceLineVisible: false, lastValueVisible: true });
    const last = (rs) => rs.length && series.applyOptions({ color: rs[rs.length - 1].up ? p.up_color : p.down_color });
    return {
      setData(bars) { const rs = transform(bars); series.setData(rs); last(rs); },
      destroy() { chart.removeSeries(series); },
    };
  };
}

const candleParams = (colorBy) => [
  P("up_color", "Rising color", "color", UP, "Colors"),
  P("down_color", "Falling color", "color", DOWN, "Colors"),
  ...(colorBy ? [P("color_by", "Color each candle by", "choice", COLOR_BY[0], "Colors", { options: COLOR_BY })] : []),
  P("up_fill", "Fill rising bodies (close above open)", "bool", true, "Bodies"),
  P("down_fill", "Fill falling bodies (close below open)", "bool", true, "Bodies"),
  P("outline", "Outline filled bodies too", "bool", false, "Bodies"),
  thickness("outline_width", "Outline thickness", 1, "Bodies"),
  P("body_pct", "Body width (% of bar spacing)", "int", 70, "Bodies", { min: 10, max: 100 }),
  P("wick", "Show wicks", "bool", true, "Wicks"),
  thickness("wick_width", "Wick thickness", 1, "Wicks"),
  P("ext_dim", "Dim extended-hours bars", "bool", true, "Options"),
];

define({
  id: "candles", name: "Candles",
  description: "Candlesticks. For hollow candles (as on TradingView), turn off \"Fill rising bodies\" and color each " +
               "candle by the previous close.",
  params: candleParams(true),
  create: (chart, p) => barsType("candles", (bars) => rows(bars, p.color_by))(chart, p),
});

define({
  id: "heikin", name: "Heikin-Ashi",
  description: "Heikin-Ashi candles: each one averages the bar with the one before it, which smooths out the noise. " +
               "The prices on them are averages, not trades.",
  params: candleParams(false),
  create: (chart, p) => barsType("candles", (bars) => rows(heikinAshi(bars), COLOR_BY[0]))(chart, p),
});

define({
  id: "bars", name: "OHLC bars",
  description: "Open-high-low-close bars: a vertical line from the low to the high, a tick to the left at the open " +
               "and a tick to the right at the close.",
  params: [
    P("up_color", "Rising color", "color", UP, "Colors"),
    P("down_color", "Falling color", "color", DOWN, "Colors"),
    P("color_by", "Color each bar by", "choice", COLOR_BY[0], "Colors", { options: COLOR_BY }),
    thickness("width", "Bar thickness", 1, "Bars"),
    P("open_tick", "Show the open tick", "bool", true, "Bars"),
    P("ext_dim", "Dim extended-hours bars", "bool", true, "Options"),
  ],
  create: (chart, p) => barsType("bars", (bars) => rows(bars, p.color_by))(chart, p),
});

// ---------------------------------------------------------------- line and area (the library's own series)
define({
  id: "line", name: "Line",
  description: "A line through each bar's close.",
  params: [
    P("color", "Color", "color", "#c9d1db", "Line"),
    thickness("width", "Thickness", 2, "Line"),
    lineStyle("solid"),
    P("ext_color", "Extended-hours color", "color", "#6b7380", "Options"),
    P("ext_dim", "Use it for extended hours", "bool", true, "Options"),
  ],
  create(chart, p) {
    const series = chart.addSeries(LWC.LineSeries, { color: p.color, lineWidth: p.width, lineStyle: lwcStyle(p.style),
                                                     priceLineVisible: false, lastValueVisible: true });
    return {
      setData(bars) {
        series.setData(bars.map((b) => ({ time: b.time, value: b.close, ...(p.ext_dim && b.session !== "rth" ? { color: p.ext_color } : {}) })));
      },
      destroy() { chart.removeSeries(series); },
    };
  },
});

define({
  id: "area", name: "Area",
  description: "A line through each bar's close, filled down to the bottom of the chart.",
  params: [
    P("color", "Line color", "color", "#c9d1db", "Line"),
    thickness("width", "Thickness", 2, "Line"),
    lineStyle("solid"),
    P("fill_color", "Fill color", "color", "#c9d1db", "Fill"),
    P("fill_top", "Fill opacity at the line %", "int", 28, "Fill", { min: 0, max: 100 }),
    P("fill_bottom", "Fill opacity at the bottom %", "int", 2, "Fill", { min: 0, max: 100 }),
  ],
  create(chart, p) {
    const series = chart.addSeries(LWC.AreaSeries, { lineColor: p.color, lineWidth: p.width, lineStyle: lwcStyle(p.style),
                                                     topColor: rgba(p.fill_color, p.fill_top / 100),
                                                     bottomColor: rgba(p.fill_color, p.fill_bottom / 100),
                                                     priceLineVisible: false, lastValueVisible: true });
    return {
      setData(bars) { series.setData(bars.map((b) => ({ time: b.time, value: b.close }))); },
      destroy() { chart.removeSeries(series); },
    };
  },
});

// ---------------------------------------------------------------- current price line
// Only the latest price: a horizontal line across the chart, green while the price is rising and red while it
// is falling, with optional direction arrows at 1/3 and 2/3 of the way across. Nothing is kept from before.
// The arrows show the direction of the last change only; they are not signals.
class CurrentLine {
  constructor(p) {
    this.p = p; this.price = null; this.up = true;
    const self = this;
    this._views = [{ zOrder: () => "top", renderer: () => ({
      draw: (t) => t.useMediaCoordinateSpace(({ context, mediaSize }) => self.draw(context, mediaSize)) }) }];
  }
  attached({ series, requestUpdate }) { this.series = series; this.requestUpdate = requestUpdate; }
  detached() { this.series = this.requestUpdate = null; }
  paneViews() { return this._views; }
  updateAllViews() {}
  set(price, up) { this.price = price; this.up = up; if (this.requestUpdate) this.requestUpdate(); }
  draw(ctx, size) {
    if (this.price == null || !this.series) return;
    const y = this.series.priceToCoordinate(this.price);
    if (y == null) return;
    const p = this.p, color = this.up ? p.up_color : p.down_color;
    const yy = Math.round(y) + (p.width % 2 ? 0.5 : 0);
    ctx.save();
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = p.width;
    ctx.setLineDash(dash(p.style, p.width));
    ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(size.width, yy); ctx.stroke();
    ctx.setLineDash([]);
    if (p.arrows) for (const f of [1 / 3, 2 / 3]) this.arrow(ctx, Math.round(size.width * f), y, p.arrow_size, p.width, this.up);
    ctx.restore();
  }
  // an arrow the shape of a chart marker arrow: a triangular head on a shaft. Rising: it stands on top of the
  // line, pointing up. Falling: the same arrow turned 180 degrees, hanging below the line, pointing down.
  arrow(ctx, x, y, s, lineWidth, up) {
    const half = s / 2, shaft = Math.max(2, Math.round(s * 0.55)) / 2;
    const gap = lineWidth / 2 + 1, dir = up ? -1 : 1;
    const base = y + dir * gap, neck = base + dir * half, tip = base + dir * s;
    ctx.beginPath();
    ctx.moveTo(x - shaft, base); ctx.lineTo(x - shaft, neck); ctx.lineTo(x - half, neck);
    ctx.lineTo(x, tip); ctx.lineTo(x + half, neck); ctx.lineTo(x + shaft, neck); ctx.lineTo(x + shaft, base);
    ctx.closePath(); ctx.fill();
  }
}

define({
  id: "current", name: "Current price line",
  description: "Only the latest price, as a horizontal line across the chart: green while the price is moving up, " +
               "red while it is moving down. No bars or history are drawn, so studies and levels stand out. " +
               "The arrows show which way the price last moved; they are not buy or sell signals.",
  params: [
    P("up_color", "Moving up color", "color", "#3fbf4f", "Line"),
    P("down_color", "Moving down color", "color", "#ef5350", "Line"),
    thickness("width", "Thickness", 2, "Line"),
    lineStyle("solid"),
    P("arrows", "Show direction arrows (at 1/3 and 2/3)", "bool", true, "Arrows"),
    P("arrow_size", "Arrow size (pixels)", "int", 14, "Arrows", { min: 6, max: 40 }),
  ],
  create(chart, p) {
    // one point, never drawn as a line: it carries the drawing and the price label on the price axis
    // (a price line's label, so it shows even when the latest bar is scrolled out of view)
    const series = chart.addSeries(LWC.LineSeries, { lineVisible: false, pointMarkersVisible: false, crosshairMarkerVisible: false,
                                                     priceLineVisible: false, lastValueVisible: false, color: p.up_color });
    const line = new CurrentLine(p);
    series.attachPrimitive(line);
    const label = series.createPriceLine({ price: 0, color: p.up_color, lineVisible: false, axisLabelVisible: false });
    let last = null, up = true;
    return {
      setData(bars) {
        const b = bars[bars.length - 1];
        if (!b) { series.setData([]); line.set(null, up); label.applyOptions({ axisLabelVisible: false }); last = null; return; }
        // direction: the latest change in price; on the first update, the change from the bar before
        const before = last ?? (bars.length > 1 ? bars[bars.length - 2].close : b.open);
        if (b.close > before) up = true; else if (b.close < before) up = false;
        last = b.close;
        series.applyOptions({ color: up ? p.up_color : p.down_color });
        series.setData([{ time: b.time, value: b.close }]);
        label.applyOptions({ price: b.close, color: up ? p.up_color : p.down_color, axisLabelVisible: true });
        line.set(b.close, up);
      },
      destroy() { series.detachPrimitive(line); chart.removeSeries(series); },
    };
  },
});

// ---------------------------------------------------------------- the registry
const get = (id) => TYPES.find((t) => t.id === id);
const defaults = (id) => Object.fromEntries((get(id)?.params || []).map((q) => [q.key, q.default]));
const list = () => TYPES.map(({ id, name, description, params }) => ({ id, name, description, params }));

// a chart's saved price setting with every value filled in; older saved charts kept only a style name
const LEGACY = { candles: ["candles", {}], hollow: ["candles", { up_fill: false }], heikin: ["heikin", {}],
                 bars: ["bars", {}], line: ["line", {}], area: ["area", {}] };
function normalize(price, legacyStyle) {
  let type = price && get(price.type) ? price.type : null, params = (price && price.params) || {};
  if (!type) [type, params] = LEGACY[legacyStyle] || LEGACY.candles;
  const spec = get(type), out = defaults(type);
  for (const q of spec.params) {
    const v = params[q.key];
    if (v === undefined || v === null) continue;
    if (q.type === "bool") out[q.key] = !!v;
    else if (q.type === "int" || q.type === "float") {
      const n = Number(v);
      if (Number.isFinite(n)) out[q.key] = Math.min(q.max ?? n, Math.max(q.min ?? n, q.type === "int" ? Math.round(n) : n));
    } else if (q.type === "choice") { if (q.options.includes(v)) out[q.key] = v; }
    else if (q.type === "color") { if (/^#[0-9a-f]{6}$/i.test(v)) out[q.key] = v; }
    else out[q.key] = String(v);
  }
  return { type, params: out };
}

function create(chart, price) {
  const n = normalize(price);
  return get(n.type).create(chart, n.params);
}

export const PriceTypes = { list, get, defaults, normalize, create };
