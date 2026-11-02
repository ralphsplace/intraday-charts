/* A backtest's day on a chart, over the Paper page: the chart page's review mode (/review, review.js) in a pane,
   with the day's entries and exits as arrows and the studies its rules read; studies can be added there to refine
   the rules. Esc or × closes it; "Open in a new tab" keeps it. */
import { btn, el } from "../util.js";

let pane = null;

export function closeReview() { if (pane) { pane.remove(); pane = null; } }

export function openReview(run, day) {
  closeReview();
  const url = `/review?run=${encodeURIComponent(run.id)}&day=${day}`;
  pane = el("div", "pp-review");
  pane.setAttribute("role", "dialog");
  pane.setAttribute("aria-label", `${run.strategy_name} on ${day}`);
  const head = el("div", "pp-review-head");
  const open = el("a", null, "Open in a new tab"); open.href = url; open.target = "_blank";
  head.append(el("b", null, `${run.strategy_name} · ${run.symbol} · ${day}`), el("span", "wlgrow"), open,
              btn("×", closeReview, "Close the chart", "pp-review-x"));
  const frame = el("iframe", "pp-review-frame");
  frame.src = url; frame.title = `Chart of ${run.symbol} on ${day}`;
  pane.append(head, frame);
  document.body.appendChild(pane);
  pane.querySelector(".pp-review-x").focus();
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && pane) closeReview(); });
