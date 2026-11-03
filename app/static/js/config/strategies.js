/* The Config page's Paper strategies section: what to do on the saved rules (app/paper/strategies.py). Buy if, Sell
   short if, Close a long if, Close a short if: each an expression of rules by name, e.g. ("Rule 1" AND NOT
   "Rule 3") OR Rule5, typed or built in groups (expr-editor.js); then the bars the rules are read on, the shares,
   the entry order, the stop, target or trail, and the hours. Backtests run a strategy (Paper trading page).
   Data: /api/paper/strategies, /api/paper/rules (the conditions' menus), the study catalog (an entry at a level). */
import { fmtMin } from "../format.js";
import { $, api, el } from "../util.js";
import { firstLine, operand } from "./conditions.js";
import { exprEditor, exprText } from "./expr-editor.js";
import { NEW, namedMenu } from "./named-menu.js";

const PARTS = [["buy", "Buy if", null], ["short", "Sell short if", "never"], ["exit_long", "Close a long if", "only the stop, target or the end of the day"],
               ["exit_short", "Close a short if", "only the stop, target or the end of the day"]];
let meta = null, st = null, editors = {}, menu = null, say = () => {};

const blank = () => ({ tf: 3, qty: 100, order: { type: "market" }, exits: { stop: 0.5, target: 1.0, reverse: false },
                       hours: { from: 570, to: 950 }, trees: { buy: null, short: null, exit_long: null, exit_short: null } });

export async function loadStrategies(sayFn) {
  say = sayFn;
  const [s, r, cat] = await Promise.all([api("/api/paper/strategies"), api("/api/paper/rules"), api("/api/studies").then((c) => c.studies)]);
  meta = { ...r, strategies: s.strategies, ruleList: s.rules, catalog: cat };
  menu.fill();
  pick(menu.current());
}

function pick(name) {
  const v = name === NEW ? null : meta.strategies[name];
  st = v ? structuredClone(v) : blank();
  st.exits = { reverse: false, ...st.exits };
  editors = {};
  render();
}

const leaves = () => meta.ruleList.map((n) => ({ leaf: { rule: n }, label: n }));

function render() {
  for (const [k] of PARTS) if (editors[k]) st.trees[k] = editors[k].tree();
  const f = $("ppStratForm");
  f.innerHTML = "";
  const row = (label, ...nodes) => { const r = el("div", "pp-row"); r.append(el("span", "pp-label", label), ...nodes); f.appendChild(r); return r; };
  const num = (v, set, step = 1, min = 0) => { const i = el("input"); Object.assign(i, { type: "number", value: v ?? "", step, min }); i.oninput = () => set(i.value === "" ? null : +i.value); return i; };
  const choice = (opts, v, set) => { const s = el("select"); for (const [k, t] of opts) { const o = el("option", null, t); o.value = k; s.appendChild(o); } s.value = v; s.onchange = () => set(s.value); return s; };

  f.appendChild(el("h4", "sec", "When"));
  if (!meta.ruleList.length) f.appendChild(el("p", "muted small", "Save a rule first (Paper rules): a strategy trades on rules."));
  for (const [k, label, empty] of PARTS) {
    const r = el("div", "pp-row pp-when");
    r.dataset.part = k;
    editors[k] = exprEditor({ tree: st.trees[k], leaves, label, empty, addLabel: "+ rule", noLeaves: "No rules saved yet." });
    r.append(el("span", "pp-label", label), editors[k].root);
    f.appendChild(r);
  }
  f.appendChild(el("h4", "sec", "Trading"));
  row("Bars", choice(meta.tfs.map((t) => [String(t), `${t} minute${t > 1 ? "s" : ""}`]), String(st.tf), (v) => { st.tf = +v; }),
      el("span", "muted small", "the rules are read at each bar's close"));
  row("Shares", num(st.qty, (v) => { st.qty = v; }));
  const o = st.order;
  const orderRow = row("Order", choice([["market", "Market (next bar's open)"], ["limit", "Limit, from the close by"], ["stop", "Stop, from the close by"],
                                         ["level", "At a study line or level"]], o.type,
                                       (v) => { st.order = v === "level" ? { type: v, level: firstLine(meta), as: "limit" } : { type: v, offset: 0 }; render(); }));
  if (o.type === "limit" || o.type === "stop") orderRow.append(num(o.offset, (v) => { o.offset = v || 0; }, 0.01), el("span", "muted small", "$"));
  if (o.type === "level") {
    orderRow.append(operand({ study: o.level }, (x) => { o.level = x.study; }, render, meta, true),
                    choice([["limit", "as a limit"], ["stop", "as a stop"]], o.as, (v) => { o.as = v; }));
  }
  f.appendChild(el("h4", "sec", "Exits"));
  const x = st.exits;
  row("Stop", num(x.stop, (v) => { x.stop = v; }, 0.01), el("span", "muted small", "$ from the signal bar's close (blank: none)"));
  row("Target", num(x.target, (v) => { x.target = v; }, 0.01), el("span", "muted small", "$"));
  row("Trailing stop", num(x.trail, (v) => { x.trail = v; }, 0.01), el("span", "muted small", "$ behind the best price (instead of a stop)"));
  const atrLen = num(x.atr_length ?? 14, (v) => { x.atr_length = v; }, 1, 1);
  atrLen.setAttribute("aria-label", "ATR length");
  const atrRow = row("ATR trailing stop", num(x.trail_atr, (v) => { x.trail_atr = v; }, 0.1), el("span", "muted small", "× ATR ("), atrLen,
                     el("span", "muted small", "bars) behind the best price, the ATR on these bars when the entry goes in (instead of a stop)"));
  atrRow.querySelector("input").setAttribute("aria-label", "ATR trailing stop: multiple");
  const rev = el("input"); rev.type = "checkbox"; rev.checked = x.reverse; rev.onchange = () => { x.reverse = rev.checked; };
  row("Reverse", rev, el("span", "muted small", "an opposite entry closes the trade and turns it"));
  f.appendChild(el("h4", "sec", "Hours"));
  const time = (m, set) => { const i = el("input"); i.type = "time"; i.value = fmtMin(m); i.onchange = () => { const [h, mm] = i.value.split(":").map(Number); set(h * 60 + mm); }; return i; };
  row("New trades from", time(st.hours.from, (v) => { st.hours.from = v; }), el("span", null, "to"), time(st.hours.to, (v) => { st.hours.to = v; }),
      el("span", "muted small", "ET; every trade is closed at the end of regular hours"));
}

async function saveStrategy() {
  await Promise.all(PARTS.map(([k]) => editors[k].settled()));
  const bad = PARTS.map(([k, label]) => editors[k].error() && `${label}: ${editors[k].error()}`).find(Boolean);
  if (bad) { say(bad, true); return; }
  const body = { tf: st.tf, qty: st.qty, order: st.order, hours: st.hours, exits: { ...st.exits } };
  for (const k of ["stop", "target", "trail", "trail_atr"]) if (body.exits[k] == null || body.exits[k] === 0) delete body.exits[k];
  if (body.exits.trail_atr == null) delete body.exits.atr_length;
  for (const [k] of PARTS) { const t = editors[k].tree(); body[k] = t ? exprText(t) : ""; }
  const name = menu.current() === NEW ? null : menu.current();
  try {
    const r = await api("/api/paper/strategies", { name, strategy: body });
    meta.strategies = r.strategies;
    say(`Saved "${r.name}".`);
    menu.show(r.name);
  } catch (e) { say(e.message, true); return; }
  document.dispatchEvent(new Event("paper:strategies"));
}

export function initStrategies(sayFn) {
  say = sayFn;
  menu = namedMenu({ sel: $("ppStrat"), renameBtn: $("ppStratRename"), deleteBtn: $("ppStratDelete"), base: "/api/paper/strategies",
                     what: "strategy", say: (t, bad) => say(t, bad), items: () => meta?.strategies || {},
                     set: (r) => { meta.strategies = r.strategies; }, pick,
                     changed: () => document.dispatchEvent(new Event("paper:strategies")) });
  $("ppStratSave").onclick = saveStrategy;
  $("ppStratForm").onsubmit = (e) => { e.preventDefault(); saveStrategy(); };
  // a rule saved, renamed or deleted: the menus of rules, and any strategy that said its old name
  document.addEventListener("paper:rules", () => { if (meta) rulesChanged().catch((e) => say(e.message, true)); });
}

// rules saved, added, renamed or deleted (another section): the rule menus follow; what's being written here stays
async function rulesChanged() {
  const s = await api("/api/paper/strategies");
  await Promise.all(Object.values(editors).map((x) => x.settled()));    // what's typed, read first
  meta = { ...meta, strategies: s.strategies, ruleList: s.rules };
  menu.fill();
  if (st) render(); else pick(menu.current());
}
