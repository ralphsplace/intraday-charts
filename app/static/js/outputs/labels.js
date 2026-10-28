/* Coloured information boxes at the top of the price pane (ATR levels: day range, call and put triggers). */
import { textOn } from "../styles.js";
import { el } from "../util.js";

export default {
  key: "labels",
  gather: (ls) => ls,
  legend(panel, items) {
    if (!items.length) return null;
    const row = el("div", "labels");
    for (const l of items) { const c = el("span", "lbl", l.text); c.style.background = l.bg; c.style.color = textOn(l.bg); row.appendChild(c); }
    return row;
  },
};
