/* The top bar's drawing tools (Alert, Line, Trend, VWAP): one button per tool module in tools/. A button arms its
   tool on every chart; the next click on a chart places it there. */
import { setTools } from "./drawings.js";
import { app } from "./state.js";
import { $, btn } from "./util.js";
import { TOOLS } from "./tools/index.js";

export function init() {
  const box = $("drawTools");
  for (const t of TOOLS) {
    const b = btn(t.button, () => setTools(app.tool === t.type ? null : t.type));
    b.dataset.tool = t.type;
    b.title = t.tip;
    box.appendChild(b);
  }
}
