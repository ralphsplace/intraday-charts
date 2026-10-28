/* The earnings chart: one line per report on a trading-day axis (e.g. -10 ... +5 around day 0), drawn in the chosen
   mode (modes.js: relative % or split-adjusted price). Lines are labelled at their right end so they aren't told
   apart by colour alone. */
import { COLORS, SERIES_COLORS, withAlpha } from "../styles.js";
import { LWC, el } from "../util.js";
import { MODES, pct } from "./modes.js";

export const day = (x) => (x === 0 ? "Day 0" : (x > 0 ? "+" : "−") + Math.abs(x));

/* a vertical line at day 0, above the grid (a grid line sits at the same place) */
class DayZero {
  constructor() {
    this._views = [{ zOrder: () => "normal", renderer: () => ({ draw: (t) => t.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const x = this.chart?.timeScale().timeToCoordinate(0);
      if (x == null) return;
      context.save(); context.strokeStyle = "rgba(227,230,234,0.6)"; context.setLineDash([4, 4]);
      context.beginPath(); context.moveTo(Math.round(x) + 0.5, 0); context.lineTo(Math.round(x) + 0.5, mediaSize.height); context.stroke();
      context.restore();
    }) }) }];
  }
  attached({ chart }) { this.chart = chart; }
  detached() { this.chart = null; }
  paneViews() { return this._views; }
  updateAllViews() {}
}

export class EarningsChart {
  constructor(host, endsEl) {
    this.endsEl = endsEl;
    this.chart = LWC.createOptionsChart(host, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: COLORS.text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: "#262c35", scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: "#262c35", rightOffset: 1.5, tickMarkFormatter: (x) => day(x) },
      localization: { priceFormatter: pct, timeFormatter: (x) => day(x) },
      crosshair: { mode: LWC.CrosshairMode.Normal },
      handleScroll: false, handleScale: false,
    });
    this.series = [];
    this.zero = null;
    this.onHover = () => {};
    this.chart.subscribeCrosshairMove((p) => this.onHover(p.time ?? null));
    new ResizeObserver(() => requestAnimationFrame(() => this.placeLabels())).observe(host);
  }

  // quarters: newest first, as from /api/earnings; mode: a key of MODES
  show(quarters, mode) {
    const m = MODES[mode];
    this.series.forEach((s) => this.chart.removeSeries(s));
    this.chart.applyOptions({ localization: { priceFormatter: m.format, timeFormatter: (x) => day(x) } });
    this.series = quarters.map((q, i) => {
      const s = this.chart.addSeries(LWC.LineSeries, { color: SERIES_COLORS[i], lineWidth: 2, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerRadius: 4, priceFormat: { type: "custom", formatter: m.format } });
      s.setData(q.points.map((p) => ({ time: p.x, value: m.value(p) })));
      return s;
    });
    if (this.series[0]) {
      if (m.zeroLine) {
        this.series[0].createPriceLine({ price: 0, color: "rgba(227,230,234,0.35)", lineWidth: 1, lineStyle: LWC.LineStyle.Dashed,
                                         axisLabelVisible: false, title: "" });
      }
      this.series[0].attachPrimitive(new DayZero());
    }
    this.quarters = quarters; this.mode = m;
    this.chart.timeScale().fitContent();
    requestAnimationFrame(() => this.placeLabels());
  }

  // emphasise one quarter (legend hover); null for none
  highlight(i) {
    this.series.forEach((s, n) => s.applyOptions({ color: i == null || n === i ? SERIES_COLORS[n] : withAlpha(SERIES_COLORS[n], 0.18),
                                                   lineWidth: n === i ? 3 : 2 }));
  }

  // a label at the right end of each line, nudged apart so they don't overlap
  placeLabels() {
    this.endsEl.innerHTML = "";
    if (!this.quarters) return;
    const ts = this.chart.timeScale();
    const labels = this.quarters.map((q, i) => {
      const last = q.points[q.points.length - 1];
      return { i, text: q.label, x: ts.timeToCoordinate(last.x), y: this.series[i].priceToCoordinate(this.mode.value(last)) };
    }).filter((l) => l.x != null && l.y != null).sort((a, b) => a.y - b.y);
    for (let k = 1; k < labels.length; k++) labels[k].y = Math.max(labels[k].y, labels[k - 1].y + 16);
    for (const l of labels) {
      const e = el("span", null, l.text);
      Object.assign(e.style, { left: (l.x + 6) + "px", top: l.y + "px", borderLeftColor: SERIES_COLORS[l.i] });
      this.endsEl.appendChild(e);
    }
  }
}
