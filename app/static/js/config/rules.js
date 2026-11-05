/* The Config page's Signal rules section: a rule is a named true / false condition, read at each bar's close
   (app/signals/rules.py). It has lettered conditions (A: Close crosses above OR high, B: ...) and says when it's true
   as an expression of them and of other saved rules: (A OR B) AND NOT (C OR "Trend down"), typed or built in
   groups (expr-editor.js). Strategies (strategies.js) trade on rules. Saved app-wide by name; the server checks
   everything and says what's wrong. Data: /api/signal-rules, the study catalog (/api/studies). */
import { $, api, btn, el } from "../util.js";
import { conditionRow, describe, firstLine } from "./conditions.js";
import { exprEditor, exprText, mapLeaves } from "./expr-editor.js";
import { NEW, namedMenu } from "./named-menu.js";

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
let meta = null, rule = null, editor = null, menu = null, say = () => {};

const allOf = (n) => (n === 0 ? null : n === 1 ? { cond: "A" } : { and: [...LETTERS.slice(0, n)].map((c) => ({ cond: c })) });

export async function loadRules(sayFn) {
  say = sayFn;
  const [m, cat] = await Promise.all([api("/api/signal-rules"), api("/api/studies").then((c) => c.studies)]);
  meta = { ...m, catalog: cat };
  menu.fill();
  pick(menu.current());
}

export const ruleNames = () => Object.keys(meta?.rules || {}).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

function pick(name) {
  const r = name === NEW ? null : meta.rules[name];
  rule = r ? { conditions: structuredClone(r.conditions), tree: r.tree } : { conditions: [], tree: null };
  editor = null;
  render();
}

// the leaves an expression can use: this rule's conditions by letter, and every other saved rule by name
function leaves() {
  const mine = rule.conditions.map((c, i) => ({ leaf: { cond: LETTERS[i] }, label: `${LETTERS[i]}: ${describe(c, meta)}` }));
  const others = ruleNames().filter((n) => n !== menu.current()).map((n) => ({ leaf: { rule: n }, label: `Rule: ${n}` }));
  return [...mine, ...others];
}

function render() {
  const f = $("ppRuleForm");
  if (editor) rule.tree = editor.tree();
  f.innerHTML = "";
  f.appendChild(el("h4", "sec", "Conditions"));
  const box = el("div", "pp-conds");
  rule.conditions.forEach((c, i) => box.appendChild(conditionRow(c, LETTERS[i], () => removeCondition(i), render, meta)));
  const add = btn("+ condition", () => addCondition(), "Add a condition", "pp-add");
  add.disabled = rule.conditions.length >= LETTERS.length;
  f.append(box, add);
  f.appendChild(el("h4", "sec", "True when"));
  f.appendChild(el("p", "muted small", "Type it, e.g. (A OR B) AND NOT (C OR \"Trend down\"), or build it below. AND, OR, NOT (or !), " +
    "brackets, other rules by name (in quotes if the name has spaces), WITHIN 3 A: A on one of the last 3 bars."));
  editor = exprEditor({ tree: rule.tree, leaves, label: "True when", noLeaves: "Add a condition first, or save other rules to use here." });
  f.appendChild(editor.root);
}

function addCondition() {
  if (editor) rule.tree = editor.tree();
  const all = JSON.stringify(rule.tree) === JSON.stringify(allOf(rule.conditions.length));
  rule.conditions.push({ a: { price: "close" }, op: "crosses_above", b: { study: firstLine(meta) } });
  if (all) rule.tree = allOf(rule.conditions.length);         // "all of them" stays all of them
  editor = null;
  render();
}

// a condition out: the expression loses it, and the letters after it move up one
function removeCondition(i) {
  rule.tree = mapLeaves(editor.tree(), (x) => {
    if (!x.cond) return x;
    const k = LETTERS.indexOf(x.cond);
    return k === i ? null : k > i ? { cond: LETTERS[k - 1] } : x;
  });
  rule.conditions.splice(i, 1);
  editor = null;
  render();
}

async function saveRule() {
  await editor.settled();
  if (editor.error()) { say("Fix the expression first: " + editor.error(), true); return; }
  const tree = editor.tree();
  const name = menu.current() === NEW ? null : menu.current();
  try {
    const r = await api("/api/signal-rules", { name, rule: { conditions: rule.conditions, when: tree ? exprText(tree) : "" } });
    meta.rules = r.rules;
    say(`Saved "${r.name}".`);
    menu.show(r.name);
  } catch (e) { say(e.message, true); return; }
  document.dispatchEvent(new Event("signals:rules"));
}

export function initRules(sayFn) {
  say = sayFn;
  menu = namedMenu({ sel: $("ppRule"), renameBtn: $("ppRuleRename"), deleteBtn: $("ppRuleDelete"), base: "/api/signal-rules",
                     what: "rule", say: (t, bad) => say(t, bad), items: () => meta?.rules || {},
                     set: (r) => { meta.rules = r.rules; },
                     pick, changed: () => document.dispatchEvent(new Event("signals:rules")) });
  $("ppRuleSave").onclick = saveRule;
  $("ppRuleForm").onsubmit = (e) => { e.preventDefault(); saveRule(); };
}
