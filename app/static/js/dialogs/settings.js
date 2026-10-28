/* The settings dialog, built from a parameter list: used by studies, price types and drawings. */
import { closeModal, openModal } from "../dialogs/modal.js";
import { saveDrawings } from "../drawings.js";
import { app, defaultsFor, spec } from "../state.js";
import { $, el } from "../util.js";
import { defaultsOf } from "../params.js";
import { toolFor } from "../tools/index.js";
import { PriceTypes as PT } from "../pricetypes.js";

export function openSettings({ title, desc, params, values, defaults, onApply }) {
  app.editing = { params, defaults, onApply };
  $("settingsTitle").textContent = title;
  $("settingsDesc").textContent = desc || "";
  fillSettings(params, values);
  openModal("settingsDlg");
}

export function openPriceSettings(panel) {
  const t = PT.get(panel.price.type);
  openSettings({ title: "Price: " + t.name, desc: t.description, params: t.params, values: panel.price.params,
                 defaults: PT.defaults(t.id), onApply: (vals) => panel.setPrice(PT.normalize({ type: t.id, params: vals })) });
}

export function openStudySettings(panel, id) {
  const s = panel.studies.find((x) => x.uid === id);
  const sp = s && spec(s.type);
  if (!sp) return;
  openSettings({ title: sp.name, desc: sp.description, params: sp.params, values: s.params, defaults: defaultsFor(s.type),
                 onApply: (vals) => { Object.assign(s.params, vals); panel.changed(); } });
}

// a drawing's settings, from its tool (tools/)
export function openDrawingSettings(sym, d) {
  const tool = toolFor(d.type), { title, desc, params } = tool.settings(d);
  openSettings({ title, desc, params, values: d, defaults: defaultsOf(params),
                 onApply: (vals) => { Object.assign(d, vals); tool.applied?.(d); saveDrawings(sym); } });
}

export function fillSettings(params, values) {
  const form = $("settingsForm");
  form.innerHTML = "";
  let section = null, rowEl = null, rowName = null;
  for (const p of params) {
    if (p.section !== section) { section = p.section; rowName = null; form.appendChild(el("h4", "sec", section)); }
    const input = makeInput(p, values[p.key] ?? p.default);
    if (p.row && rowName === null && p.section === "Style") {
      // captions over the colour / line type / thickness / transparency columns
      const caps = params.filter((q) => q.row === p.row).map((q) => q.label);
      const head = el("div", "ctl-row ctl-head");
      caps.forEach((c) => head.appendChild(el("span", null, c.replace(" %", ""))));
      form.append(el("span"), head);
    }
    if (p.row) {
      if (p.row !== rowName) {
        rowName = p.row;
        const label = el("label", null, p.row); label.htmlFor = input.id;
        rowEl = el("div", "ctl-row");
        form.append(label, rowEl);
      }
      input.title = p.label;
      input.setAttribute("aria-label", p.row + " " + p.label.toLowerCase());
      rowEl.appendChild(input);
    } else {
      rowName = null;
      const label = el("label", null, p.label); label.htmlFor = input.id;
      form.append(label, input);
    }
  }
}

export function makeInput(p, value) {
  let input;
  if (p.type === "choice") {
    input = el("select");
    for (const o of p.options) { const op = el("option", null, (p.labels && p.labels[o]) || o); op.value = o; input.appendChild(op); }
    input.value = value;
  } else {
    input = el("input");
    input.type = { int: "number", float: "number", bool: "checkbox", color: "color" }[p.type] || "text";
    if (p.type === "bool") input.checked = !!value; else input.value = value;
    if (p.min != null) input.min = p.min;
    if (p.max != null) input.max = p.max;
    if (p.type === "int") input.step = 1;
    if (p.type === "float") input.step = p.step ?? 0.1;
  }
  input.id = "p_" + p.key; input.dataset.key = p.key; input.dataset.type = p.type;
  return input;
}

export function init() {
  $("settingsDefaults").onclick = () => app.editing && fillSettings(app.editing.params, app.editing.defaults);
  $("settingsApply").onclick = () => {
    if (!app.editing) return;
    const vals = {};
    for (const e of $("settingsForm").querySelectorAll("[data-key]")) {
      const t = e.dataset.type;
      vals[e.dataset.key] = t === "bool" ? e.checked : t === "int" ? parseInt(e.value, 10) : t === "float" ? parseFloat(e.value) : e.value;
    }
    closeModal("settingsDlg");
    app.editing.onApply(vals);
  };
  $("settingsForm").onsubmit = (e) => { e.preventDefault(); $("settingsApply").click(); };

}
