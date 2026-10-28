/* Drawings (alert lines, horizontal lines, trend lines): kept per symbol in this browser, like thinkorswim, so
   every chart of a symbol shows them. What each kind looks like and does is up to its module in tools/; this file
   stores them and runs the tools' hooks. */
import { toast } from "./notify.js";
import { DRAWINGS_KEY } from "./keys.js";
import { app } from "./state.js";
import { TOOLS, toolFor } from "./tools/index.js";
import { load, store, uid } from "./util.js";

let drawings = load(DRAWINGS_KEY) || {};
export const drawingsFor = (sym) => (drawings[sym] || []).filter((d) => toolFor(d.type));
export function saveDrawings(sym) {
  store(DRAWINGS_KEY, drawings);
  app.panels.filter((p) => p.symbol === sym).forEach((p) => p.renderDrawings());
}
export function addDrawing(sym, d) { (drawings[sym] = drawings[sym] || []).push({ id: uid(), ...d }); saveDrawings(sym); }
export function removeDrawing(sym, id) { drawings[sym] = (drawings[sym] || []).filter((d) => d.id !== id); saveDrawings(sym); }
export const drawingLabel = (d) => toolFor(d.type).label(d);

// a chart's drawing tools and alerts (mixed into Panel)
export class DrawingTools {
  attachTools() {
    this.toolState = {};
    for (const t of TOOLS) t.attach?.(this);
  }

  saveDrawings() { saveDrawings(this.symbol); }

  renderDrawings() {
    if (this.dead) return;
    const list = drawingsFor(this.symbol);
    for (const t of TOOLS) {
      t.render(this, list.filter((d) => d.type === t.type), this.pending?.type === t.type ? this.pending : null);
    }
    if (this.view) this.drawLegends();
  }

  // alerts fire only going forward: in Live mode, or while replaying forward
  checkAlerts(v) {
    const forward = app.live || (this.lastCursor != null && v.cursor > this.lastCursor);
    this.lastCursor = v.cursor;
    if (!forward) return;
    let changed = false;
    for (const d of drawingsFor(this.symbol)) {
      const msg = toolFor(d.type).check?.(this, d, v);
      if (msg) { toast(msg); changed = true; }
    }
    if (changed) saveDrawings(this.symbol);
  }

  setTool(type) {
    this.tool = type; this.pending = null;
    Object.entries(this.toolBtns).forEach(([k, b]) => b.classList.toggle("active", k === type));
    this.hint.textContent = type ? toolFor(type).hints[0] : "";
    this.chartEl.classList.toggle("drawing", !!type);
    this.renderDrawings();
  }

  // a click or hover on the price pane as {time, price}, or null
  clickPoint(p) {
    if (!p.point || (p.paneIndex != null && p.paneIndex !== 0)) return null;
    const price = this.candles.coordinateToPrice(p.point.y);
    const time = p.time ?? this.chart.timeScale().coordinateToTime(p.point.x);
    if (price == null) return null;
    return { time, price: Math.round(price * 100) / 100 };
  }

  onClick(p) {
    if (!this.tool || !this.view) return;
    const tool = toolFor(this.tool), pt = this.clickPoint(p);
    if (!pt || (tool.needsTime && pt.time == null)) return;
    const points = [...(this.pending?.points || []), pt];
    if (points.length < tool.hints.length) {             // more clicks to go
      this.pending = { type: tool.type, points };
      this.hint.textContent = tool.hints[points.length];
      this.renderDrawings();
      return;
    }
    if (tool.place) tool.place(this, points);            // e.g. VWAP: adds a study rather than a drawing
    else addDrawing(this.symbol, { type: tool.type, ...tool.create(this, points) });
    tool.placed?.();
    this.setTool(null);
  }

  // while placing a drawing, the mouse position is the preview's next point
  previewAt(p) {
    if (!this.pending || !p.point) return;
    const pt = this.clickPoint(p);
    if (!pt || (toolFor(this.pending.type).needsTime && pt.time == null)) return;
    this.pending.hover = pt;
    const tool = toolFor(this.pending.type);             // only that tool redraws: this runs on every mouse move
    tool.render(this, drawingsFor(this.symbol).filter((d) => d.type === tool.type), this.pending);
  }
}
