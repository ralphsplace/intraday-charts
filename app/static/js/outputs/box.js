/* The opening-range box: an outlined, lightly filled rectangle over the price, with its label. */
import { svgDash, withAlpha, COLORS } from "../styles.js";
import { svgEl } from "../util.js";

export default {
  key: "box",
  overlay(panel, b, add) {
    const v = panel.view, x0 = panel.xAt(b.start), x1 = panel.xAt(b.end) ?? panel.xAt(v.now_time);
    const y0 = panel.candles.priceToCoordinate(b.high), y1 = panel.candles.priceToCoordinate(b.low);
    if (![x0, x1, y0, y1].every((z) => z != null)) return;
    const d = add("orbox", x0, x1 - x0, b.label, y0, Math.max(y1 - y0, 2));
    if (!d) return;
    const w = b.width || 1, col = b.color || COLORS.purple;
    d.style.border = "none"; d.style.background = withAlpha(col, 0.1);
    const bw = parseFloat(d.style.width) || 0, bh = parseFloat(d.style.height) || 0;
    const svg = svgEl("svg", { width: bw, height: bh, style: "position:absolute;left:0;top:0;overflow:visible" });
    svg.appendChild(svgEl("rect", { x: w / 2, y: w / 2, width: Math.max(bw - w, 0), height: Math.max(bh - w, 0),
      fill: "none", stroke: col, "stroke-width": w, "stroke-dasharray": svgDash(b.style, w) }));
    d.prepend(svg);
    const label = d.querySelector("span");
    if (label) label.style.color = col;
  },
};
