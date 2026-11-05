/* An equity curve: a small Lightweight Charts line over the starting cash, one point per session or day. Used for
   an account's trades and a backtest's report. points: [{i, value, label}]. */
import { COLORS } from "../styles.js";
import { LWC } from "../util.js";

const charts = new WeakMap();

export function equityChart(box, points, start) {
  // the points are numbered 1 (the start), 2, 3, … on the time axis; the formatters turn the numbers into labels
  const label = (t) => (t === 1 ? "start" : points[t - 2]?.label || "");
  charts.get(box)?.remove();
  box.innerHTML = "";
  if (!points.length) { box.hidden = true; return; }
  box.hidden = false;
  const chart = LWC.createChart(box, {
    autoSize: true, layout: { background: { color: "transparent" }, textColor: COLORS.text, fontSize: 11, attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: COLORS.grid } },
    rightPriceScale: { borderColor: "#262c35" },
    timeScale: { borderColor: "#262c35", tickMarkFormatter: (t) => label(t).split(" ")[0] },
    localization: { timeFormatter: label },
    handleScroll: false, handleScale: false,
  });
  const up = points[points.length - 1].value >= start;
  const line = chart.addSeries(LWC.AreaSeries, { lineColor: up ? COLORS.bull : COLORS.bear, lineWidth: 2,
                                               topColor: "rgba(38,166,154,0.18)", bottomColor: "rgba(38,166,154,0.0)",
                                               priceLineVisible: false });
  line.setData([{ time: 1, value: start }, ...points.map((p, k) => ({ time: k + 2, value: p.value }))]);
  line.createPriceLine({ price: start, color: "#8a8f98", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "start" });
  chart.timeScale().fitContent();
  charts.set(box, chart);
}
