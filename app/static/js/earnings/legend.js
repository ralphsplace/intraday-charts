/* The legend: one row per report with its colour, dates, timing and moves; while the mouse is over the chart,
   each row also shows that quarter's value at the hovered day, in the chart's mode (the move is always shown in %).
   Hovering a row highlights its line. */
import { SERIES_COLORS } from "../styles.js";
import { el } from "../util.js";
import { day } from "./chart.js";
import { MODES, pct } from "./modes.js";

const fmtDate = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const signed = (v) => el("span", v > 0 ? "up" : v < 0 ? "down" : "", v == null ? "–" : pct(v));

export function renderLegend(box, quarters, mode, hoverX, onHighlight) {
  const m = MODES[mode];
  box.innerHTML = "";
  quarters.forEach((q, i) => {
    const row = el("div", "eq");
    const sw = el("span", "sw"); sw.style.background = SERIES_COLORS[i];
    const val = el("span", "val");
    const p = hoverX != null ? q.points.find((pt) => pt.x === hoverX) : null;
    if (hoverX == null) val.append(el("span", "muted", "Day 0 "), signed(q.move));
    else if (!p) val.append(el("span", "muted", day(hoverX) + " "), signed(null));
    else if (m.zeroLine) val.append(el("span", "muted", day(hoverX) + " "), signed(p.pct));
    else val.append(el("span", "muted", day(hoverX) + " "), el("span", null, m.format(m.value(p)) + " "), signed(p.pct));
    const last = q.points[q.points.length - 1];
    const sub = el("span", "sub", `${q.timing} · day 0 ${fmtDate(q.day0)} · ${day(last.x)}: ${pct(last.pct)}` +
                   (q.splits.length ? ` · adjusted for a ${q.splits.map((s) => s.ratio).join(", ")} split` : ""));
    row.append(sw, el("span", "when", "Reported " + fmtDate(q.report_date)), val, sub);
    row.onmouseenter = () => onHighlight(i);
    row.onmouseleave = () => onHighlight(null);
    box.appendChild(row);
  });
}

export { fmtDate };
