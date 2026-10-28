/* Line series (moving averages, VWAP, oscillators); "markers_only" draws dots instead of a line (VZO), and
   format "volume" shows large values as 1.38M (the CVD estimate). */
import { LWC } from "../util.js";
import { lineStyle } from "../styles.js";

export default {
  key: "lines",
  shape: (ls) => ls.map((l) => l.id + (l.markers_only ? "*" : "")).join(","),
  build(layer, ls) {
    layer.lines = {};
    for (const l of ls) {
      const s = layer.chart.addSeries(LWC.LineSeries, {
        color: l.color, lineWidth: l.width || 1, lineStyle: lineStyle(l.style),
        lineVisible: !l.markers_only, pointMarkersVisible: !!l.markers_only, pointMarkersRadius: (l.width || 1) + 1,
        priceLineVisible: false, lastValueVisible: !!l.last_value, crosshairMarkerVisible: false,
        ...(layer.scale ? { priceScaleId: layer.scale, priceFormat: { type: "volume" } } : {}),
        ...(l.format === "volume" ? { priceFormat: { type: "volume" } } : {}) }, layer.pane);   // e.g. 1.38M
      layer.series.push(s); layer.lines[l.id] = s;
    }
  },
  update(layer, ls) { for (const l of ls || []) layer.lines?.[l.id]?.setData(l.data); },
  color: (ls) => ls[0]?.color,
};
