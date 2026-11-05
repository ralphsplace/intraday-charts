/* A condition in a signal rule, as form fields: an operand (a price, a number, or a study's line or level
   with the settings that change it), how it compares (crosses above, is below...), and another operand. Used by
   Config's Signal rules (each lettered condition) and Signal strategies (an entry at a study level). The lists come
   from /api/signal-rules (prices, ops) and the study catalog (/api/studies: each study's "lines", which for a level
   study are its levels by name, and its "rule_settings"). */
import { btn, el } from "../util.js";

export const OP_LABEL = { crosses_above: "crosses above", crosses_below: "crosses below", above: "is above", below: "is below",
                          rising: "is rising", falling: "is falling" };
const TRENDS = ["rising", "falling"];                    // against itself some bars before: no second operand

// meta: { prices, ops, catalog }
export const lined = (meta) => meta.catalog.filter((s) => s.lines.length);       // studies with a line or level to read

export function firstLine(meta) {
  const s = meta.catalog.find((x) => x.type === "vwap") || lined(meta)[0];
  return { type: s.type, params: {}, output: s.lines[0].id };
}

// in words, for menus: "Close crosses above VWAP", "Close is above Session levels: OR high"
export function describe(c, meta) {
  const side = (x) => {
    if ("value" in x) return String(x.value);
    if ("price" in x) return x.price[0].toUpperCase() + x.price.slice(1);
    const spec = meta.catalog.find((s) => s.type === x.study.type);
    const line = spec?.lines.find((l) => l.id === x.study.output);
    const short = (spec?.name || x.study.type).replace(/ \(.*\)$/, "");
    return line && spec.lines.length > 1 && line.label !== short ? `${short}: ${line.label}` : short;
  };
  const at = (x) => side(x) + (x.ago ? ` ${x.ago} bar${x.ago > 1 ? "s" : ""} ago` : "");
  if (TRENDS.includes(c.op)) return `${at(c.a)} ${OP_LABEL[c.op]}` + ((c.bars || 1) > 1 ? ` over ${c.bars} bars` : "");
  return `${at(c.a)} ${OP_LABEL[c.op] || c.op} ${at(c.b)}`;
}

// an operand; set(x) replaces it, redraw() draws the form again after a change of kind
export function operand(x, set, redraw, meta, studyOnly = false) {
  const box = el("span", "pp-operand");
  const kind = el("select");
  const kinds = studyOnly ? [["study", "Study line or level"]]
    : [...meta.prices.map((p) => [p, p[0].toUpperCase() + p.slice(1)]), ["value", "Number"], ["study", "Study line or level"]];
  for (const [k, t] of kinds) { const o = el("option", null, t); o.value = k; kind.appendChild(o); }
  kind.value = "study" in x ? "study" : "value" in x ? "value" : x.price;
  kind.onchange = () => { set(kind.value === "study" ? { study: firstLine(meta) } : kind.value === "value" ? { value: 0 } : { price: kind.value }); redraw(); };
  if (!studyOnly) box.appendChild(kind);
  if ("value" in x) {
    const i = el("input", "pp-num"); Object.assign(i, { type: "number", value: x.value, step: "any" });
    i.oninput = () => set({ value: +i.value });
    box.appendChild(i);
  }
  // a price's or study's value some bars before (blank: this bar), e.g. VZO 1 bar ago
  const agoBox = () => {
    const i = el("input", "pp-ago"); Object.assign(i, { type: "number", min: 0, max: 50, step: 1, value: x.ago || "", placeholder: "now" });
    i.title = "Its value this many bars before (blank: this bar)"; i.setAttribute("aria-label", "Bars ago");
    i.oninput = () => { const n = parseInt(i.value, 10); if (n > 0) x.ago = Math.min(50, n); else delete x.ago; };
    i.onchange = redraw;                                  // its description in the expression's menus
    return [i, el("span", "muted small", "bars ago")];
  };
  if ("price" in x && !studyOnly) box.append(...agoBox());
  if ("study" in x) {
    const s = x.study, spec = meta.catalog.find((c) => c.type === s.type) || lined(meta)[0];
    const st = el("select");
    for (const c of lined(meta)) { const o = el("option", null, c.name); o.value = c.type; st.appendChild(o); }
    st.value = spec.type;
    st.onchange = () => { const c = meta.catalog.find((q) => q.type === st.value); set({ study: { type: c.type, params: {}, output: c.lines[0].id } }); redraw(); };
    box.appendChild(st);
    if (!spec.lines.some((l) => l.id === s.output)) s.output = spec.lines[0].id;   // e.g. saved before levels were named
    if (spec.lines.length > 1) {
      const ln = el("select");
      ln.setAttribute("aria-label", `${spec.name}: which line or level`);
      for (const l of spec.lines) { const o = el("option", null, l.label); o.value = l.id; ln.appendChild(o); }
      ln.value = s.output; ln.onchange = () => { s.output = ln.value; redraw(); };
      box.appendChild(ln);
    }
    // the settings that change it: a level study names them (the opening range's length...); a line study, its first
    // few numbers and choices (an SMA's length...)
    const shown = spec.rule_settings ? spec.params.filter((q) => spec.rule_settings.includes(q.key))
      : spec.params.filter((q) => ["int", "float", "choice"].includes(q.type) && !["Style", "Fill"].includes(q.section)).slice(0, 3);
    for (const p of shown) {
      const cur = s.params?.[p.key] ?? p.default;
      let i;
      if (p.type === "choice") {
        i = el("select");
        for (const v of p.options) { const o = el("option", null, String(v)); o.value = v; i.appendChild(o); }
        i.value = cur;
        i.onchange = () => { s.params = { ...(s.params || {}), [p.key]: i.value }; };
      } else {
        i = el("input", "pp-num"); Object.assign(i, { type: "number", value: cur, step: p.type === "int" ? 1 : p.step || 0.1 });
        i.oninput = () => { s.params = { ...(s.params || {}), [p.key]: p.type === "int" ? parseInt(i.value, 10) : parseFloat(i.value) }; };
      }
      i.title = p.label; i.setAttribute("aria-label", `${spec.name} ${p.label}`);
      box.append(el("span", "muted small", p.label.toLowerCase()), i);
    }
    if (!studyOnly) box.append(...agoBox());
  }
  return box;
}

// one condition: operand, comparison, operand, and × to remove it
export function conditionRow(c, letter, remove, redraw, meta) {
  const r = el("div", "pp-cond");
  r.dataset.letter = letter;
  const op = el("select");
  op.setAttribute("aria-label", `Condition ${letter}: how it compares`);
  for (const k of meta.ops) { const o = el("option", null, OP_LABEL[k]); o.value = k; op.appendChild(o); }
  op.value = c.op;
  op.onchange = () => {
    c.op = op.value;
    if (TRENDS.includes(c.op)) { delete c.b; c.bars ||= 1; if ("value" in c.a) c.a = { price: "close" }; }     // its direction
    else { delete c.bars; c.b ||= { value: 0 }; }
    redraw();
  };
  r.append(el("b", "pp-letter", letter), operand(c.a, (x) => { c.a = x; }, redraw, meta), op);
  if (TRENDS.includes(c.op)) {                           // than it was N bars before
    const n = el("input", "pp-num"); Object.assign(n, { type: "number", min: 1, max: 50, step: 1, value: c.bars || 1 });
    n.title = "Compared with its value this many bars before (1: the previous bar)"; n.setAttribute("aria-label", `Condition ${letter}: over how many bars`);
    n.oninput = () => { c.bars = Math.max(1, Math.min(50, parseInt(n.value, 10) || 1)); };
    r.append(el("span", "muted small", "than"), n, el("span", "muted small", "bar(s) before"));
  } else r.appendChild(operand(c.b, (x) => { c.b = x; }, redraw, meta));
  r.appendChild(btn("×", remove, `Remove condition ${letter}`, "pp-x"));
  return r;
}
