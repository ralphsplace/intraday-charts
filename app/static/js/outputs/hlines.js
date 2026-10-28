/* Reference lines in a study's own pane (RSI 70/30, VZO +-40/60); the pane's scale always includes them. */
import { lineStyle } from "../styles.js";

export default {
  key: "hlines",
  build(layer, hs) {
    const host = layer.host();
    if (!host) return;
    layer.refPrices.push(...hs.map((h) => h.price));
    layer.hlines = hs.map((h) => host.createPriceLine({ price: h.price, color: h.color, lineWidth: h.width || 1,
      lineStyle: lineStyle(h.style, "dashed"), axisLabelVisible: false, title: h.title || "" }));
  },
  clear(layer) { (layer.hlines || []).forEach((pl) => layer.host()?.removePriceLine(pl)); },
};
