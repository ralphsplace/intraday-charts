/* The Config page's Paper rules section: a form that writes a rule (app/paper/rules.py) as data, never as code. Entry
   conditions for long and short, the entry order, the exits, the hours, saved app-wide by name. The server checks
   every field and says what's wrong. Data: /api/paper/rules, the study catalog (/api/studies). */
import { fmtMin } from "../format.js";
import { $, api, btn, el } from "../util.js";

const NEW = "\u0000new";
const OP_LABEL = { crosses_above: "crosses above", crosses_below: "crosses below", above: "is above", below: "is below" };
const enc = encodeURIComponent;
let meta = null, catalog = [], rule = null, current = NEW;

const blank = () => ({ tf: 3, qty: 100, within: 1, long: [], short: [], order: { type: "market" },
                       exits: { stop: 0.5, target: 1.0, exit_long: [], exit_short: [], reverse: false }, hours: { from: 570, to: 950 } });
const lined = () => catalog.filter((s) => s.lines.length);          // studies with lines a rule can read

export async function loadRules(say) {
  [meta, catalog] = await Promise.all([api("/api/paper/rules"), api("/api/studies").then((c) => c.studies)]);
  fillRuleMenus();
  pick(current, say);
}

export const ruleNames = () => Object.keys(meta?.rules || {}).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

function fillRuleMenus() {
  const sel = $("ppRule");
  sel.innerHTML = "";
  for (const [v, t] of [[NEW, "New rule…"], ...ruleNames().map((n) => [n, n])]) { const o = el("option", null, t); o.value = v; sel.appendChild(o); }
  if (current !== NEW && !meta.rules[current]) current = NEW;
  sel.value = current;
}

function pick(name, say) {
  current = name;
  rule = name === NEW ? blank() : structuredClone(meta.rules[name].rule);
  $("ppRuleRename").disabled = $("ppRuleDelete").disabled = name === NEW;
  render(say);
}

// ---------------------------------------------------------------- the form
function render(say) {
  const f = $("ppRuleForm");
  f.innerHTML = "";
  const row = (label, ...nodes) => { const r = el("div", "pp-row"); r.append(el("span", "pp-label", label), ...nodes); f.appendChild(r); return r; };
  const num = (v, set, step = 1, min = 0) => { const i = el("input"); Object.assign(i, { type: "number", value: v ?? "", step, min }); i.oninput = () => set(i.value === "" ? null : +i.value); return i; };
  const choice = (opts, v, set) => { const s = el("select"); for (const [k, t] of opts) { const o = el("option", null, t); o.value = k; s.appendChild(o); } s.value = v; s.onchange = () => set(s.value); return s; };

  row("Bars", choice(meta.tfs.map((t) => [String(t), `${t} minute${t > 1 ? "s" : ""}`]), String(rule.tf), (v) => { rule.tf = +v; }),
      el("span", "muted small", "conditions read each bar at its close"));
  row("Shares", num(rule.qty, (v) => { rule.qty = v; }));
  f.appendChild(el("h4", "sec", "Entry"));
  conditions(f, "Long when", rule.long, say);
  conditions(f, "Short when", rule.short, say);
  row("Within", num(rule.within, (v) => { rule.within = v; }), el("span", "muted small", "bars of each other (1: all on the same bar)"));
  const o = rule.order;
  const orderRow = row("Order", choice([["market", "Market (next bar's open)"], ["limit", "Limit, from the close by"], ["stop", "Stop, from the close by"],
                                         ["level", "At a study line"]], o.type, (v) => { rule.order = v === "level" ? { type: v, level: firstLine(), as: "limit" } : { type: v, offset: 0 }; render(say); }));
  if (o.type === "limit" || o.type === "stop") orderRow.append(num(o.offset, (v) => { o.offset = v || 0; }, 0.01), el("span", "muted small", "$"));
  if (o.type === "level") {
    orderRow.append(studyPicker({ study: o.level }, (x) => { o.level = x.study; }, say, true),
                    choice([["limit", "as a limit"], ["stop", "as a stop"]], o.as, (v) => { o.as = v; }));
  }
  f.appendChild(el("h4", "sec", "Exits"));
  const x = rule.exits;
  row("Stop", num(x.stop, (v) => { x.stop = v; }, 0.01), el("span", "muted small", "$ from the signal bar's close (blank: none)"));
  row("Target", num(x.target, (v) => { x.target = v; }, 0.01), el("span", "muted small", "$"));
  row("Trailing stop", num(x.trail, (v) => { x.trail = v; }, 0.01), el("span", "muted small", "$ behind the best price (instead of a stop)"));
  conditions(f, "Close a long when", x.exit_long, say);
  conditions(f, "Close a short when", x.exit_short, say);
  const rev = el("input"); rev.type = "checkbox"; rev.checked = x.reverse; rev.onchange = () => { x.reverse = rev.checked; };
  row("Reverse", rev, el("span", "muted small", "an opposite entry closes the trade and turns it"));
  f.appendChild(el("h4", "sec", "Hours"));
  const time = (m, set) => { const i = el("input"); i.type = "time"; i.value = fmtMin(m); i.onchange = () => { const [h, mm] = i.value.split(":").map(Number); set(h * 60 + mm); }; return i; };
  row("New trades from", time(rule.hours.from, (v) => { rule.hours.from = v; }), el("span", null, "to"), time(rule.hours.to, (v) => { rule.hours.to = v; }),
      el("span", "muted small", "ET; every trade is closed at the end of regular hours"));
}

function conditions(f, label, list, say) {
  const box = el("div", "pp-conds");
  list.forEach((c, i) => {
    const r = el("div", "pp-cond");
    const op = el("select");
    for (const k of meta.ops) { const o = el("option", null, OP_LABEL[k]); o.value = k; op.appendChild(o); }
    op.value = c.op; op.onchange = () => { c.op = op.value; };
    r.append(studyPicker(c.a, (x) => { c.a = x; }, say), op, studyPicker(c.b, (x) => { c.b = x; }, say),
             btn("×", () => { list.splice(i, 1); render(say); }, "Remove this condition", "pp-x"));
    box.appendChild(r);
  });
  const op = label === "Short when" || label === "Close a long when" ? "crosses_below" : "crosses_above";   // the usual way round
  const add = btn("+ condition", () => { list.push({ a: { price: "close" }, op, b: { study: firstLine() } }); render(say); },
                  `Add a condition to "${label}"`, "pp-add");
  const r = el("div", "pp-row"); r.append(el("span", "pp-label", label), box, add); f.appendChild(r);
}

function firstLine() {
  const s = catalog.find((x) => x.type === "vwap") || lined()[0];
  return { type: s.type, params: {}, output: s.lines[0].id };
}

// an operand: a price, a number, or a study line with its numeric settings
function studyPicker(x, set, say, studyOnly = false) {
  const box = el("span", "pp-operand");
  const kind = el("select");
  const kinds = studyOnly ? [["study", "Study line"]] : [...meta.prices.map((p) => [p, p[0].toUpperCase() + p.slice(1)]), ["value", "Number"], ["study", "Study line"]];
  for (const [k, t] of kinds) { const o = el("option", null, t); o.value = k; kind.appendChild(o); }
  kind.value = "study" in x ? "study" : "value" in x ? "value" : x.price;
  kind.onchange = () => { set(kind.value === "study" ? { study: firstLine() } : kind.value === "value" ? { value: 0 } : { price: kind.value }); render(say); };
  if (!studyOnly) box.appendChild(kind);
  if ("value" in x) {
    const i = el("input"); Object.assign(i, { type: "number", value: x.value, step: "any" }); i.className = "pp-num";
    i.oninput = () => set({ value: +i.value });
    box.appendChild(i);
  }
  if ("study" in x) {
    const s = x.study, spec = catalog.find((c) => c.type === s.type) || lined()[0];
    const st = el("select");
    for (const c of lined()) { const o = el("option", null, c.name); o.value = c.type; st.appendChild(o); }
    st.value = spec.type;
    st.onchange = () => { const c = catalog.find((q) => q.type === st.value); set({ study: { type: c.type, params: {}, output: c.lines[0].id } }); render(say); };
    box.appendChild(st);
    if (spec.lines.length > 1) {
      const ln = el("select");
      for (const l of spec.lines) { const o = el("option", null, l.label); o.value = l.id; ln.appendChild(o); }
      ln.value = s.output || spec.lines[0].id; ln.onchange = () => { s.output = ln.value; };
      box.appendChild(ln);
    }
    for (const p of spec.params.filter((q) => (q.type === "int" || q.type === "float") && q.section !== "Style").slice(0, 3)) {
      const i = el("input"); Object.assign(i, { type: "number", value: s.params?.[p.key] ?? p.default, step: p.type === "int" ? 1 : p.step || 0.1 });
      i.className = "pp-num"; i.title = p.label; i.setAttribute("aria-label", `${spec.name} ${p.label}`);
      i.oninput = () => { s.params = { ...(s.params || {}), [p.key]: p.type === "int" ? parseInt(i.value, 10) : parseFloat(i.value) }; };
      box.append(el("span", "muted small", p.label.toLowerCase()), i);
    }
  }
  return box;
}

// ---------------------------------------------------------------- saving
async function saveRule(say) {
  const clean = { ...rule, exits: { ...rule.exits } };
  for (const k of ["stop", "target", "trail"]) if (clean.exits[k] == null || clean.exits[k] === 0) delete clean.exits[k];
  try {
    const r = await api("/api/paper/rules", { name: current === NEW ? null : current, rule: clean });
    meta.rules = r.rules; current = r.name;
    say(`Saved "${r.name}".`);
  } catch (e) { say(e.message, true); return; }
  fillRuleMenus(); pick(current, say);
  document.dispatchEvent(new Event("paper:rules"));
}

export function initRules(say) {
  $("ppRule").onchange = (e) => pick(e.target.value, say);
  $("ppRuleSave").onclick = () => saveRule(say);
  $("ppRuleForm").onsubmit = (e) => { e.preventDefault(); saveRule(say); };
  $("ppRuleRename").onclick = () => {                 // renamed in place: the menu becomes a box while typing
    const sel = $("ppRule"), input = el("input", "cfg-input");
    Object.assign(input, { value: current, maxLength: 60, spellcheck: false });
    input.setAttribute("aria-label", "New name for the rule");
    sel.replaceWith(input); input.focus(); input.select();
    let finished = false;
    const done = async (keep) => {
      if (finished) return;
      finished = true;
      input.replaceWith(sel);
      const to = input.value.trim();
      if (keep && to && to !== current) {
        try { const r = await api(`/api/paper/rules/${enc(current)}/rename`, { to }); meta.rules = r.rules; current = r.name; say(`Renamed to "${r.name}".`); }
        catch (e) { say(e.message, true); }
        fillRuleMenus(); pick(current, say);
        document.dispatchEvent(new Event("paper:rules"));
      }
    };
    input.onkeydown = (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); };
    input.onblur = () => done(true);
  };
  $("ppRuleDelete").onclick = async (e) => {
    const b = e.currentTarget;
    if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Delete? Yes"; setTimeout(() => { b.dataset.sure = ""; b.textContent = "Delete"; }, 4000); return; }
    try { meta.rules = (await api(`/api/paper/rules/${enc(current)}`, null, "DELETE")).rules; say(`Deleted "${current}".`); current = NEW; }
    catch (err) { say(err.message, true); }
    b.dataset.sure = ""; b.textContent = "Delete";
    fillRuleMenus(); pick(current, say);
    document.dispatchEvent(new Event("paper:rules"));
  };
}
