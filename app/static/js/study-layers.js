/* Draws a chart's studies. Each study is a "layer" (its pane, series and price lines); what each kind of output
   looks like is up to its module in outputs/ — this file only runs their hooks in order. */
import { OUTPUTS } from "./outputs/index.js";
import { el } from "./util.js";

// the outputs' chart-wide drawings, created once per chart
export function attachOutputs(panel) {
  panel.out = {};
  for (const o of OUTPUTS) o.attach?.(panel);
}

// the gathered items of every output with a gather hook, from the visible studies' results
export function gatherOutputs(panel, view) {
  const acc = {};
  for (const s of panel.studies.filter((x) => x.visible)) {
    const res = view.studies[s.uid];
    if (!res) continue;
    for (const o of OUTPUTS) if (o.gather && res[o.key] != null) (acc[o.key] ||= []).push(...o.gather(res[o.key]));
  }
  return acc;
}

const shapeOf = (res) => OUTPUTS.map((o) => (o.shape && res[o.key] != null ? o.key + ":" + o.shape(res[o.key]) : "")).join("|");

// study drawing for a Panel (mixed into Panel)
export class StudyLayers {
  teardown() {
    for (const layer of Object.values(this.rendered)) {
      for (const o of OUTPUTS) o.clear?.(layer);
      layer.series.forEach((s) => this.chart.removeSeries(s));
    }
    this.rendered = {};
    for (let i = this.chart.panes().length - 1; i > 0; i--) this.chart.removePane(i);
  }

  newLayer(uid, res, pane) {
    const layer = { panel: this, chart: this.chart, res, uid, pane, scale: res.pane === "volume" ? "vol-" + uid : undefined,
                    series: [], refPrices: [] };
    layer.host = () => layer.series[0];
    for (const o of OUTPUTS) if (o.build && res[o.key] != null) o.build(layer, res[o.key]);
    if (layer.scale) this.chart.priceScale(layer.scale).applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const host = layer.host(), ref = layer.refPrices;
    if (host && ref.length) {
      host.applyOptions({ autoscaleInfoProvider: (original) => {
        const o = original();
        if (!o) return o;
        return { ...o, priceRange: { minValue: Math.min(o.priceRange.minValue, ...ref), maxValue: Math.max(o.priceRange.maxValue, ...ref) } };
      } });
    }
    return layer;
  }

  renderStudies(v) {
    const visible = this.studies.filter((s) => s.visible);
    const sig = JSON.stringify([v.symbol, visible.map((s) => [s.uid, s.type, s.params, shapeOf(v.studies[s.uid] || {})])]);
    const rebuild = sig !== this.layoutSig;
    if (rebuild) { this.teardown(); this.layoutSig = sig; }
    let nextPane = 1;
    this.levelPrices = [];
    for (const s of visible) {
      const res = v.studies[s.uid];
      if (!res) continue;
      let layer = this.rendered[s.uid];
      if (rebuild || !layer) layer = this.rendered[s.uid] = this.newLayer(s.uid, res, res.pane === "own" ? nextPane++ : 0);
      layer.res = res;
      for (const o of OUTPUTS) o.update?.(layer, res[o.key]);
    }
    const gathered = gatherOutputs(this, v);
    for (const o of OUTPUTS) o.flush?.(this, gathered[o.key] || []);
    if (rebuild) this.chart.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));
  }

  // HTML drawn over the chart (opening-range box, event lines); redrawn on scroll and resize
  drawOverlay() {
    const v = this.view, ov = this.overlay;
    if (this.dead) return;
    ov.innerHTML = "";
    if (!v || !this.chart.panes().length) return;
    const h = this.chartEl.clientHeight - this.chart.timeScale().height();
    const w = this.chart.timeScale().width();
    const add = (cls, left, width, text, top = 0, height = h) => {
      if (left == null || left > w) return null;
      const d = el("div", cls);
      Object.assign(d.style, { left: Math.max(left, 0) + "px", top: top + "px", height: height + "px" });
      if (width != null) d.style.width = Math.max(Math.min(width, w - left), 0) + "px";
      if (text) d.appendChild(el("span", null, text));
      ov.appendChild(d);
      return d;
    };
    for (const s of this.studies.filter((x) => x.visible)) {
      const res = v.studies[s.uid];
      if (!res || !res.ok) continue;
      for (const o of OUTPUTS) if (o.overlay && res[o.key] != null) o.overlay(this, res[o.key], add);
    }
  }
}

// the colour of a study's legend swatch: from the first output that has one
export function studyColor(res) {
  for (const o of OUTPUTS) {
    const c = o.color && res?.[o.key]?.length ? o.color(res[o.key]) : null;
    if (c) return c;
  }
  return null;
}
