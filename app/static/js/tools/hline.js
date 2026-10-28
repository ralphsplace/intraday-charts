/* Horizontal line at a price, with an optional label. */
import { param, lineParams } from "../params.js";
import { renderPriceLines } from "./priceline.js";

const label = (d) => (d.label ? d.label + " " : "Line ") + d.price.toFixed(2);

export default {
  type: "hline", button: "Line", tip: "Click the chart to place a horizontal line",
  hints: ["Click to place a line"],
  create: (panel, [pt]) => ({ price: pt.price, label: "", color: "#4d9de0", style: "solid", width: 1 }),
  label,
  settings: (d) => ({
    title: "Horizontal line", desc: "",
    params: [param("price", "Price", "float", d.price, { step: 0.01 }), param("label", "Label", "text", ""),
             ...lineParams("Line", "#4d9de0", "solid", 1)],
  }),
  render(panel, list) { renderPriceLines(panel, "hline", list, (d) => d.color, label, "dashed"); },
};
