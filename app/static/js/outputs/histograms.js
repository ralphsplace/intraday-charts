/* Histogram series (volume bars, MACD histogram, TICK bars), in the study's pane. */
import { LWC } from "../util.js";

export default {
  key: "histograms",
  shape: (hs) => hs.map((h) => h.id).join(","),
  build(layer, hs) {
    layer.histograms = {};
    for (const h of hs) {
      const s = layer.chart.addSeries(LWC.HistogramSeries, { priceLineVisible: false, lastValueVisible: false,
        priceFormat: layer.scale ? { type: "volume" } : { type: "price", precision: 2, minMove: 0.01 },
        ...(layer.scale ? { priceScaleId: layer.scale } : {}) }, layer.pane);
      layer.series.push(s); layer.histograms[h.id] = s;
    }
  },
  update(layer, hs) { for (const h of hs || []) layer.histograms?.[h.id]?.setData(h.data); },
};
