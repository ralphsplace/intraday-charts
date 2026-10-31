/* A settings form built from a parameter list (params.js): sections, and colour / line type / thickness rows
   with captions. Used by the settings dialog (studies, price types, drawings) and the Config page. Pure DOM. */
import { el } from "./util.js";

export function fillForm(form, params, values) {
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

// the form's values, typed by each setting's type
export function readForm(form) {
  const vals = {};
  for (const e of form.querySelectorAll("[data-key]")) {
    const t = e.dataset.type;
    vals[e.dataset.key] = t === "bool" ? e.checked : t === "int" ? parseInt(e.value, 10) : t === "float" ? parseFloat(e.value) : e.value;
  }
  return vals;
}
