/* Trend line between two points (time and price), optionally extended to the right edge. Kept by time, so it
   stays put across timeframes and days. While placing it, a dotted preview follows the mouse. */
import { param, lineParams } from "../params.js";
import { ChartPrimitives as PR } from "../primitives.js";

export default {
  type: "trend", button: "Trend", tip: "Click two points to draw a trend line",
  hints: ["Click the first point", "Click the second point"],
  needsTime: true,
  create: (panel, [p1, p2]) => ({ p1, p2, color: "#e3e6ea", style: "solid", width: 1, extend: false }),
  label: (d) => "Trend line" + (d.extend ? " (extended)" : ""),
  settings: () => ({
    title: "Trend line", desc: "",
    params: [param("extend", "Extend to the right", "bool", false), ...lineParams("Line", "#e3e6ea", "solid", 1)],
  }),
  attach(panel) {
    panel.toolState.trendLines = new PR.TrendLines((t) => panel.xAtExt(t));
    panel.candles.attachPrimitive(panel.toolState.trendLines);
  },
  render(panel, list, pending) {
    const preview = pending && { p1: pending.points[0], p2: pending.hover || pending.points[0] };
    panel.toolState.trendLines.set(list, preview);
  },
};
