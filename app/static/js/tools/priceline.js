/* Shared by tools drawn as a horizontal price line (alert, horizontal line): one price line per drawing. */
import { lineStyle } from "../styles.js";

export function renderPriceLines(panel, type, list, colorOf, label, fallbackStyle) {
  const st = panel.toolState;
  (st[type] || []).forEach((pl) => panel.candles.removePriceLine(pl));
  st[type] = list.map((d) => panel.candles.createPriceLine({ price: d.price, color: colorOf(d), lineWidth: d.width || 1,
    lineStyle: lineStyle(d.style, fallbackStyle), axisLabelVisible: true, title: panel.compact() ? "" : label(d) }));
}
