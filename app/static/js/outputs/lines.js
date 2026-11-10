/* Line series (moving averages, VWAP, oscillators); "draw" is "line" (the default), "dots" (a dot at each value,
   no line) or "both" (VZO, Parabolic SAR: app/studies/base.py draw_of), and format "volume" shows large values as
   1.38M (the CVD estimate). */
import { LWC } from "../util.js";
import { lineStyle } from "../styles.js";

export default {
  key: "lines",
  shape: (ls) => ls.map((l) => `${l.id}:${l.draw || "line"}`).join(","),
  build(layer, ls) {
    layer.lines = {};
    for (const l of ls) {
      const s = layer.chart.addSeries(LWC.LineSeries, {
        color: l.color, lineWidth: l.width || 1, lineStyle: lineStyle(l.style),
        lineVisible: (l.draw || "line") !== "dots", pointMarkersVisible: (l.draw || "line") !== "line",
        pointMarkersRadius: (l.width || 1) + 1,
        priceLineVisible: false, lastValueVisible: !!l.last_value, crosshairMarkerVisible: false,
        ...(layer.scale ? { priceScaleId: layer.scale, priceFormat: { type: "volume" } } : {}),
        ...(l.format === "volume" ? { priceFormat: { type: "volume" } } : {}) }, layer.pane);   // e.g. 1.38M
      layer.series.push(s); layer.lines[l.id] = s;
    }
  },
  update(layer, ls) { for (const l of ls || []) layer.lines?.[l.id]?.setData(l.data); },
  color: (ls) => ls[0]?.color,
};
