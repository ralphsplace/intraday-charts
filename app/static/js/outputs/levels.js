/* Price levels on the price pane (prior day, session levels, ATR levels, POC/VAH/VAL), with axis labels.
   Small charts drop the level names from the lines; "Fit levels" widens the price scale to show them all. */
import { lineStyle } from "../styles.js";

export default {
  key: "levels",
  update(layer, lvs) {
    const p = layer.panel, compact = p.compact();
    (layer.levels || []).forEach((pl) => p.candles.removePriceLine(pl));
    p.levelPrices.push(...(lvs || []).map((lv) => lv.price));
    layer.levels = (lvs || []).map((lv) => p.candles.createPriceLine({ price: lv.price, color: lv.color, lineWidth: lv.width || 1,
      lineStyle: lineStyle(lv.style), axisLabelVisible: true, title: compact ? "" : lv.label }));
  },
  clear(layer) { (layer.levels || []).forEach((pl) => layer.panel.candles.removePriceLine(pl)); },
  color: (lvs) => lvs[0]?.color,
};
