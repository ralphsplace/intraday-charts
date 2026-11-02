/* A true / false expression, edited two ways that stay in step (app/paper/expr.py has the language):
     typed:   (A OR B) AND NOT (X OR (S AND H)), ("Rule 1" AND !"Rule 3") OR Rule5
     groups:  nested boxes, each "All of" (AND) or "Any of" (OR), each part with Not and "within N bars"
   Typing is checked on the server as you type (/api/paper/expr), and a mistake says where; the groups show the last
   expression that was right. Used by Config's Paper rules (conditions and rules) and Paper strategies (rules). */
import { btn, el } from "../util.js";

const KEYWORDS = new Set(["and", "or", "not", "within"]);

// the tree as text, as the server writes it (expr.text): a group inside another always in brackets
export function exprText(t) {
  const name = (n) => (/^[A-Za-z_][A-Za-z0-9_.-]*$/.test(n) && !KEYWORDS.has(n.toLowerCase()) && !/^[A-Z]$/.test(n)
    ? n : `"${n.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`);
  const go = (x, top) => {
    if (!x) return "";
    if (x.cond) return x.cond;
    if (x.rule != null) return name(x.rule);
    if (x.not) return "NOT " + go(x.not, false);
    if (x.within) return `WITHIN ${x.within} ` + go(x.of, false);
    const op = x.and ? "and" : "or", parts = x[op].map((y) => go(y, false)).filter(Boolean);
    if (parts.length === 1) return parts[0];
    const s = parts.join(` ${op.toUpperCase()} `);
    return top ? s : `(${s})`;
  };
  return go(t, true);
}

// every leaf passed through fn (a new leaf, or null to drop it); groups left empty go too
export function mapLeaves(t, fn) {
  if (!t) return null;
  if (t.cond || t.rule != null) return fn(t);
  if (t.not) { const x = mapLeaves(t.not, fn); return x && { not: x }; }
  if (t.within) { const x = mapLeaves(t.of, fn); return x && { within: t.within, of: x }; }
  const op = t.and ? "and" : "or", kids = t[op].map((y) => mapLeaves(y, fn)).filter(Boolean);
  return kids.length ? { [op]: kids } : null;
}

async function check(body) {
  const r = await fetch("/api/paper/expr", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.detail?.message || j.detail || r.statusText), { pos: j.detail?.pos });
  return j;
}

/* opts: tree (or null: none), leaves() -> [{leaf: {cond: "A"} | {rule: "name"}, label}], empty (what none means,
   e.g. "never"; without it an expression is required), label (for screen readers). Returns { root, tree() }:
   tree() is the expression now (null for none). */
export function exprEditor(opts) {
  let tree = opts.tree || null, seq = 0, pending = Promise.resolve();
  const root = el("div", "xed");
  const typed = el("input", "xed-text");
  Object.assign(typed, { spellcheck: false, placeholder: opts.empty ? `blank: ${opts.empty}` : "e.g. (A OR B) AND NOT C" });
  typed.setAttribute("aria-label", `${opts.label}: as text`);
  const msg = el("div", "xed-msg small");
  const groups = el("div", "xed-groups");
  root.append(typed, msg, groups);

  const setTree = (t, fromText) => {
    tree = t;
    if (!fromText) typed.value = exprText(tree);
    msg.textContent = ""; msg.classList.remove("bad");
    draw();
  };
  typed.oninput = () => {
    const text = typed.value.trim(), my = ++seq;
    if (!text) { if (opts.empty) setTree(null, true); else { msg.textContent = "An expression is needed."; msg.classList.add("bad"); } return; }
    pending = new Promise((done) => setTimeout(async () => {
      if (my !== seq) return done();                          // still typing
      try { const r = await check({ text }); if (my === seq) setTree(r.tree, true); }
      catch (e) { if (my === seq) { msg.textContent = e.message; msg.classList.add("bad"); } }
      done();
    }, 250));
  };
  typed.onchange = () => { if (!msg.classList.contains("bad")) typed.value = exprText(tree); };   // tidy once done

  // ---------------------------------------------------------------- the groups
  const leafPick = (leaf, set) => {
    const s = el("select", "xed-leaf");
    s.setAttribute("aria-label", `${opts.label}: which condition or rule`);
    const all = opts.leaves();
    for (const [i, x] of all.entries()) { const o = el("option", null, x.label); o.value = String(i); s.appendChild(o); }
    const at = all.findIndex((x) => JSON.stringify(x.leaf) === JSON.stringify(leaf));
    if (at < 0) { const o = el("option", null, `${exprText(leaf)} (missing)`); o.value = "-1"; s.appendChild(o); }
    s.value = String(at);
    s.onchange = () => { if (+s.value >= 0) set(all[+s.value].leaf); };
    return s;
  };
  const firstLeaf = () => opts.leaves()[0]?.leaf;

  // one part of a group: a leaf or a sub-group, with Not and Within around it
  const part = (x, set, remove) => {
    let not = false, within = null, core = x;
    if (core.not) { not = true; core = core.not; }
    if (core.within) { within = core.within; core = core.of; }
    const wrap = (c, n = not, w = within) => { let y = c; if (w) y = { within: w, of: y }; if (n) y = { not: y }; return y; };
    const row = el("div", "xed-part");
    const nb = el("label", "xed-not"); const ncb = el("input"); ncb.type = "checkbox"; ncb.checked = not;
    ncb.onchange = () => set(wrap(core, ncb.checked)); nb.append(ncb, "NOT");
    nb.title = "True when this part is false";
    const wi = el("input", "xed-within"); Object.assign(wi, { type: "number", min: 1, max: 50, placeholder: "now", value: within ?? "" });
    wi.title = "Within N bars: true if it was true on any of the last N bars (blank: on this bar)";
    wi.setAttribute("aria-label", "Within this many bars");
    wi.onchange = () => { const n = parseInt(wi.value, 10); set(wrap(core, not, n > 1 ? Math.min(50, n) : null)); };
    const tail = [el("span", "muted small", "within"), wi, el("span", "muted small", "bars"), btn("×", remove, "Remove this part", "pp-x")];
    if (core.and || core.or) row.appendChild(group(core, (g) => set(g ? wrap(g) : null), [nb, ...tail]));   // its controls in its head
    else row.append(nb, leafPick(core, (l) => set(wrap(l))), ...tail);
    return row;
  };

  const group = (g, set, controls = []) => {
    const op = g.and ? "and" : "or";
    const box = el("div", "xed-group " + op);
    const head = el("div", "xed-head");
    const opSel = el("select", "xed-op");
    opSel.setAttribute("aria-label", "All or any");
    for (const [v, t] of [["and", "All of these (AND)"], ["or", "Any of these (OR)"]]) { const o = el("option", null, t); o.value = v; opSel.appendChild(o); }
    opSel.value = op;
    opSel.onchange = () => set({ [opSel.value]: g[op] });
    head.append(opSel, ...controls);
    box.appendChild(head);
    const kids = g[op];
    kids.forEach((k, i) => box.appendChild(part(k, (y) => { const next = [...kids]; if (y) next[i] = y; else next.splice(i, 1); set(next.length ? { [op]: next } : null); },
                                                () => { const next = kids.filter((_, j) => j !== i); set(next.length ? { [op]: next } : null); })));
    const adds = el("div", "xed-adds");
    adds.append(btn(opts.addLabel || "+ condition or rule", () => { const l = firstLeaf(); if (l) set({ [op]: [...kids, l] }); }, "Add a condition or rule to this group", "pp-add"),
                btn("+ group", () => { const l = firstLeaf(); if (l) set({ [op]: [...kids, { [op === "and" ? "or" : "and"]: [l] }] }); }, "Add a group inside this one", "pp-add"));
    box.appendChild(adds);
    return box;
  };

  function draw() {
    groups.innerHTML = "";
    if (!tree && opts.empty) {                                // none: just a way to start one
      const add = btn(opts.addLabel || "+ condition or rule", () => { const l = firstLeaf(); if (l) setTree(l); }, `Add to ${opts.label}`, "pp-add");
      add.disabled = !opts.leaves().length;
      groups.appendChild(add);
      return;
    }
    // the top is always shown as a group, so there's somewhere to add to
    const top = !tree ? { and: [] } : tree.and || tree.or ? tree : { and: [tree] };
    groups.appendChild(group(top, (g) => { setTree(g && (g.and || g.or).length === 1 && !opts.keepGroup ? (g.and || g.or)[0] : g); }));
    if (!opts.leaves().length) groups.appendChild(el("div", "muted small", opts.noLeaves || "Nothing to choose from yet."));
  }

  typed.value = exprText(tree);
  draw();
  // settled(): once what's typed has been checked (Save waits for it)
  return { root, tree: () => tree, set: (t) => setTree(t), redraw: draw, settled: () => pending,
           error: () => msg.classList.contains("bad") && msg.textContent };
}
