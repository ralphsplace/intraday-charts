/* MARK alert line: a price line that sounds and shows a message when the price reaches it
   (in Live mode, or while replaying forward). Grey once it has fired; Re-arm in the legend sets it again. */
import { param, lineParams } from "../params.js";
import { btn } from "../util.js";
import { renderPriceLines } from "./priceline.js";

const label = (d) => `MARK ${d.op} ${d.price.toFixed(2)}` + (d.triggered ? " (hit " + d.triggered + ")" : "");

export default {
  type: "alert", button: "Alert", tip: "Click the chart to place a MARK alert line",
  hints: ["Click to place an alert line"],
  create: (panel, [pt]) => ({ price: pt.price, op: pt.price >= panel.view.price ? ">=" : "<=", color: "#e6b450", style: "dashed", width: 1 }),
  placed() {
    if (window.Notification && Notification.permission === "default") Notification.requestPermission().catch(() => {});
  },
  label,
  settings: (d) => ({
    title: "Alert line",
    desc: "Sounds and shows a message when the price reaches the line (Live mode, or while replaying forward).",
    params: [param("price", "Price", "float", d.price, { step: 0.01 }),
             param("op", "Alert when price is", "choice", d.op, { options: [">=", "<="] }),
             ...lineParams("Line", "#e6b450", "dashed", 1)],
  }),
  applied(d) { delete d.triggered; },
  render(panel, list) { renderPriceLines(panel, "alert", list, (d) => (d.triggered ? "#6b7380" : d.color), label, "dashed"); },
  check(panel, d, v) {
    if (d.triggered) return null;
    if (!((d.op === ">=" && v.price >= d.price) || (d.op === "<=" && v.price <= d.price))) return null;
    d.triggered = v.cursor_label;
    return `${panel.symbol} ${v.price.toFixed(2)}: MARK ${d.op} ${d.price.toFixed(2)} reached at ${v.cursor_label}`;
  },
  actions: (panel, d) => (d.triggered ? [btn("Re-arm", () => { delete d.triggered; panel.saveDrawings(); })] : []),
};
