/* Event lines: a vertical line with a label at a time (scheduled events, headlines, significant moves). */
import { svgDash, COLORS } from "../styles.js";
import { svgEl } from "../util.js";

export default {
  key: "verticals",
  overlay(panel, events, add) {
    const h = panel.chart.panes()[0].getHeight();
    for (const e of events) {
      const d = add("evt " + (e.kind || "scheduled"), panel.xAt(e.time), null, e.label, 0, h);
      if (!d) continue;
      const w = e.width || 1, col = e.color || COLORS.purple;
      d.style.borderLeft = "none";
      const svg = svgEl("svg", { width: w + 2, height: h, style: "position:absolute;left:" + (-w / 2 - 1) + "px;top:0;overflow:visible" });
      svg.appendChild(svgEl("line", { x1: w / 2 + 1, x2: w / 2 + 1, y1: 0, y2: h, stroke: col, "stroke-width": w,
                                      "stroke-dasharray": svgDash(e.style, w) }));
      d.prepend(svg);
      const label = d.querySelector("span");
      if (label) label.style.borderLeft = `3px solid ${col}`;
    }
  },
};
