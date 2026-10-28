/* Shared look: line types, dash patterns and colours, used by every part of the chart page.
   The line types match app/studies/base.py (STYLES, STYLE_LABELS); tests/test_styles.py checks they stay in step. */
import { LWC } from "./util.js";

export const COLORS = { bull: "#26a69a", bear: "#ef5350", text: "#e3e6ea", grid: "#1d222a", purple: "#9b8cff", muted: "#8a8f98" };

// one colour per series where several are compared (the earnings page's quarters), newest first, in this fixed
// order. Six overlapping lines can't be told apart by colour alone, so pages using these also label the lines.
export const SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"];

export const LINE_STYLES = ["solid", "dotted", "dashed", "large_dashed", "sparse_dotted"];
export const LINE_STYLE_LABELS = { solid: "Solid", dotted: "Dotted", dashed: "Dashed", large_dashed: "Long dashes", sparse_dotted: "Sparse dots" };

const LWC_STYLE = { solid: LWC.LineStyle.Solid, dotted: LWC.LineStyle.Dotted, dashed: LWC.LineStyle.Dashed,
                    large_dashed: LWC.LineStyle.LargeDashed, sparse_dotted: LWC.LineStyle.SparseDotted };

// the chart library's line style for one of ours (for series and price lines)
export const lineStyle = (id, fallback = "solid") => LWC_STYLE[id] ?? LWC_STYLE[fallback];

// the dash pattern for lines we draw ourselves (canvas and SVG); the same as the library draws its own
export function dash(id, width = 1) {
  const w = width;
  return { dotted: [w, w], dashed: [2 * w, 2 * w], large_dashed: [6 * w, 6 * w], sparse_dotted: [w, 4 * w] }[id] || [];
}
export const svgDash = (id, width = 1) => dash(id, width).join(" ");

// a #rgb / #rrggbb colour as rgba() with the given opacity
export function rgba(hex, alpha) {
  if (/^rgba?\(/.test(hex || "")) return withAlpha(hex, alpha);
  const h = (hex || "#888888").replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

// any CSS colour (#rgb, #rrggbb, rgba()) with its opacity multiplied by `alpha`
export function withAlpha(color, alpha) {
  const m = /^rgba?\(([^)]+)\)/.exec(color || "");
  if (m) {
    const [r, g, b, a = 1] = m[1].split(",").map((x) => parseFloat(x));
    return `rgba(${r},${g},${b},${a * alpha})`;
  }
  return rgba(color, alpha);
}

// black or white text, whichever reads better on the background colour
export function textOn(bg) {
  const h = (bg || "#000").replace("#", ""), n = parseInt(h.slice(0, 6), 16);
  const lum = 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
  return lum > 150 ? "#111" : "#fff";
}
