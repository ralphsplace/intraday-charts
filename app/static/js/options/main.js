/* Starts the option-chain page (/options?symbol=QQQ): shows the cached chain, asks the TWS collector for fresh
   snapshots when they're missing or stale (or on Refresh), builds a structure from clicks or a template, and
   evaluates it. Read-only: nothing here places or prepares orders. */
import { expose } from "../debug.js";
import { ago } from "../format.js";
import { OPTIONS_KEY } from "../keys.js";
import { $, api, cleanSymbol, el, inUse, keepScroll, load, orElse, setValue, store, submitted, trackEdits } from "../util.js";

// the page's scrolling column (the toolbar and expiry strip stay above it)
const SCROLLER = () => document.querySelector("main.oc");
import { renderChain, renderStrip } from "./chain.js";
import { renderGraph, renderGrid, renderStats, stopText } from "./evaluation.js";
import { levelsFor, showOnChart } from "./levels.js";
import { renderProfile } from "./profile.js";
import { addLeg, renderLegs } from "./structure.js";

const POLL_MS = 2500, GIVE_UP_MS = 3 * 60 * 1000, MAX_EXPIRIES = 4;
const IV_SHIFTS = [-5, -3, -2, -1, 0, 1, 2, 3, 5];
const DEMO_RE = /^[A-Z]{1,6}-DEMO$/;
const fresh = () => ({ symbol: "", expiry: null, back: null, window: 9, legs: [], at: "front_close", ivShift: 0, stop: null,
                       template: "double_diagonal", profile: "near" });

let st = { ...fresh(), ...(load(OPTIONS_KEY) || {}) };
let view = null, ev = null, waitingSince = 0, poll = null, asking = 0, evalSeq = 0, collector = null, pendingFill = null;

const isDemo = () => DEMO_RE.test(st.symbol);
const save = () => store(OPTIONS_KEY, st);
function message(text) { $("ocMsg").hidden = !text; $("ocMsg").textContent = text || ""; }
const needed = () => [...new Set([st.expiry, st.back, ...st.legs.map((l) => l.expiry)].filter(Boolean))].slice(0, MAX_EXPIRIES);
const timeOf = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" }) + " ET";

// what the page is waiting for, from the collector's last report
function waitingText() {
  if (!collector || !collector.running) return "The request is saved and runs when the TWS collector starts (user guide: Connecting to TWS).";
  if (!collector.connected) return `Waiting for TWS: ${collector.message || "not connected"}.`;
  return "Asking TWS for option quotes…";
}

// ---------------------------------------------------------------- the chain
async function loadChain(refresh = false) {
  clearTimeout(poll);
  const mine = ++asking;
  if (!st.symbol) { message("Type a stock or ETF symbol (e.g. QQQ) and press Enter."); return; }
  let v;
  try { v = await api(`/api/options/chain?symbol=${encodeURIComponent(st.symbol)}${st.expiry ? "&expiry=" + st.expiry : ""}`); }
  catch (e) { if (mine === asking) message("Error: " + e.message); return; }
  if (mine !== asking) return;
  view = v;
  if (v.status === "ok") {
    if (!st.expiry || !v.expirations.includes(st.expiry)) st.expiry = v.expiry;
    if (!st.back || st.back <= st.expiry || !v.expirations.includes(st.back)) st.back = v.expiry === st.expiry ? v.next_weekly : st.back;
    save();
  }
  const have = v.wanted || [];
  const outdated = v.status === "missing" || (v.age != null && v.age > v.stale_seconds) || v.window !== st.window
                   || needed().some((e) => !have.includes(e));
  if (!isDemo() && (refresh || (outdated && !waitingSince))) {
    waitingSince = Date.now();
    try { await api("/api/options/request", { symbol: st.symbol, expiries: needed(), window: st.window }); }
    catch (e) { message("Error: " + e.message); waitingSince = 0; }
  }
  if (waitingSince) collector = await orElse(api("/api/collector"), null, "Collector status");
  if (mine !== asking) return;
  const pending = waitingSince && (v.fetched || 0) * 1000 < waitingSince;
  render();
  if (pending && Date.now() - waitingSince < GIVE_UP_MS) {
    $("ocStatus").textContent = waitingText();
    poll = setTimeout(() => loadChain(), POLL_MS);
    return;
  }
  if (pending) message("Still no fresh quotes after 3 minutes: check the collector (Load data… on a chart page shows its status).");
  else if (v.status === "error") message(v.message);
  else if (v.status === "missing") message(isDemo() ? "No synthetic option quotes for this symbol in this data folder." : waitingText());
  else if (v.expiry !== st.expiry) message(`No quotes for ${st.expiry} in this snapshot yet: press Refresh quotes.`);
  else message(null);
  waitingSince = 0;
  if (v.status === "ok") $("ocStatus").textContent = `Quotes ${timeOf(v.quoted_at)} (${ago(v.age)})${v.market_open ? "" : ", outside regular hours"}`;
  if (pendingFill && v.status === "ok") { const t = pendingFill; pendingFill = null; await fill(t); return; }
  await evaluate();
}

function render() { keepScroll(SCROLLER(), renderNow); }

function renderNow() {
  setValue($("ocSym"), st.symbol);
  $("demoBanner").hidden = !isDemo() && !view?.synthetic;
  document.title = `${st.symbol || "Option chain"} · Option chain`;
  history.replaceState(null, "", st.symbol ? `/options?symbol=${encodeURIComponent(st.symbol)}` : "/options");
  const ok = view?.status === "ok";
  $("ocPrice").textContent = ok ? `${view.price.toFixed(2)} (${view.price_source === "last" ? "last" : view.price_source})` : "";
  renderStrip($("ocStrip"), ok ? view : {}, st, pickExpiry);
  $("ocChainTitle").textContent = ok && view.expiry
    ? `${view.expiry_label} · expected move ${view.move == null ? "–" : `±${view.move.toFixed(2)} (${(view.price - view.move).toFixed(2)} – ${(view.price + view.move).toFixed(2)})`}`
    : "No chain yet";
  if (ok) renderChain($("ocChain"), view, st.legs, clickQuote); else $("ocChain").innerHTML = "";
  drawProfile();
  fillSelects();
  renderLegs($("ocLegs"), st.legs, ev, setLegs);
}

// the strike profile for the expiry on view: gamma exposure by strike
function drawProfile() {
  const ok = view?.status === "ok";
  $("ocProfileTitle").textContent = ok && view.expiry ? `Strike profile · ${view.expiry_label}` : "Strike profile";
  $("ocProfileAll").classList.toggle("active", st.profile === "all");
  $("ocProfileNear").classList.toggle("active", st.profile !== "all");
  if (ok) renderProfile($("ocProfile"), $("ocProfileNote"), view, st.profile);
  else { $("ocProfile").innerHTML = ""; $("ocProfileNote").textContent = ""; }
}

function fillSelects() {
  const back = $("ocBack");
  if (inUse(back)) return;                       // open: rebuilt on the next refresh
  back.innerHTML = "";
  for (const e of (view?.expirations || []).filter((x) => x > (st.expiry || "")).slice(0, 12)) {
    const o = el("option", null, fmt(e)); o.value = e; o.selected = e === st.back; back.appendChild(o);
  }
  const tpl = $("ocTemplate");
  if (!tpl.options.length && view?.templates) {
    for (const [k, label] of Object.entries(view.templates)) { const o = el("option", null, label); o.value = k; tpl.appendChild(o); }
  }
  tpl.value = st.template;
}
const fmt = (e) => new Date(`${e.slice(0, 4)}-${e.slice(4, 6)}-${e.slice(6)}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function pickExpiry(e) { st.expiry = e; if (st.back && st.back <= e) st.back = null; save(); loadChain(); }

function clickQuote(strike, right, qty) {
  if (!view?.expiry) return;
  setLegs(addLeg(st.legs, { qty, expiry: view.expiry, strike, right }));
}

function setLegs(legs) {
  st.legs = legs; save();
  const have = view?.wanted || [];
  if (needed().some((e) => !have.includes(e))) loadChain(); else { render(); evaluate(); }
}

// ---------------------------------------------------------------- templates
async function fill(template) {
  if (!view || view.status !== "ok") return;
  try {
    const r = await api("/api/options/template", { symbol: st.symbol, template, front: view.expiry, back: st.back });
    message(null);
    setLegs(r.legs);
  } catch (e) {
    if (st.back && !(view.wanted || []).includes(st.back) && !isDemo()) { pendingFill = template; loadChain(true); }
    else message(e.message);
  }
}

// ---------------------------------------------------------------- evaluation
async function evaluate() {
  const mine = ++evalSeq;
  const show = (on) => { for (const id of ["ocStats", "ocGraph", "ocGrid", "ocStopText"]) $(id).hidden = !on; };
  if (!st.legs.length || view?.status !== "ok") { ev = null; show(false); renderLegs($("ocLegs"), st.legs, ev, setLegs); return; }
  let r;
  try {
    r = await api("/api/options/evaluate", { symbol: st.symbol, legs: st.legs, at: st.at, iv_shift: st.ivShift / 100,
                                              stop: st.stop != null && st.stop < 0 ? st.stop : null });
  } catch (e) { if (mine === evalSeq) message("Error: " + e.message); return; }
  if (mine !== evalSeq) return;
  ev = r;
  keepScroll(SCROLLER(), () => renderLegs($("ocLegs"), st.legs, ev, setLegs));
  if (r.status !== "ok") { show(false); return; }
  show(true);
  const at = $("ocAt");
  if (!inUse(at)) {
    at.innerHTML = "";
    for (const t of r.times) { const o = el("option", null, t.label); o.value = t.id; o.selected = t.id === r.at; at.appendChild(o); }
  }
  $("ocAtLabel").textContent = `At ${r.at_label}`;
  keepScroll(SCROLLER(), () => {
    renderStats($("ocStats"), r);
    renderGraph($("ocGraph"), r, r.price, view.move);
    renderGrid($("ocGrid"), r, r.price, st.legs);
  });
  $("ocStopText").textContent = stopText(r);
}

// ---------------------------------------------------------------- saved structures
async function fillSaved(selected) {
  const all = await orElse(api("/api/saved/structures"), {}, "Saved structures");
  const sel = $("ocSaved");
  sel.innerHTML = "";
  sel.appendChild(el("option", null, Object.keys(all).length ? "Open a saved structure…" : "none saved yet")).value = "";
  for (const [name, d] of Object.entries(all).sort()) {
    const o = el("option", null, `${name} (${d.symbol})`); o.value = name; o.selected = name === selected; sel.appendChild(o);
  }
  sel.onchange = () => {
    const d = all[sel.value];
    if (!d) return;
    st = { ...fresh(), ...d, window: st.window };
    view = null; ev = null; save(); message(null); loadChain();
  };
}

// ---------------------------------------------------------------- controls
trackEdits($("ocSym"), () => st.symbol);
$("ocForm").onsubmit = (e) => {
  e.preventDefault();
  submitted($("ocSym"));
  const raw = $("ocSym").value.trim().toUpperCase();
  const sym = cleanSymbol(raw) || (DEMO_RE.test(raw) ? raw : null);
  if (!sym) { message(`"${raw}" isn't a stock symbol.`); return; }
  if (sym !== st.symbol) st = { ...fresh(), symbol: sym, window: st.window, template: st.template };
  view = null; ev = null; waitingSince = 0; save(); loadChain();
};
for (const w of [5, 9, 15]) { const o = el("option", null, `±${w} around the money`); o.value = w; $("ocWindow").appendChild(o); }
$("ocWindow").value = st.window;
$("ocWindow").onchange = () => { st.window = +$("ocWindow").value; save(); loadChain(); };
$("ocRefresh").onclick = () => { waitingSince = 0; loadChain(true); };
$("ocBack").onchange = () => { st.back = $("ocBack").value; save(); loadChain(); };
$("ocTemplate").onchange = () => { st.template = $("ocTemplate").value; save(); };
$("ocFill").onclick = () => fill($("ocTemplate").value);
$("ocProfileAll").onclick = () => { st.profile = "all"; save(); keepScroll(SCROLLER(), drawProfile); };
$("ocProfileNear").onclick = () => { st.profile = "near"; save(); keepScroll(SCROLLER(), drawProfile); };
$("ocReverse").onclick = () => setLegs(st.legs.map((l) => ({ ...l, qty: -l.qty })));
$("ocClear").onclick = () => setLegs([]);
for (const s of IV_SHIFTS) { const o = el("option", null, s ? `${s > 0 ? "+" : "−"}${Math.abs(s)} pts` : "0 pts"); o.value = s; $("ocIv").appendChild(o); }
$("ocIv").value = st.ivShift;
$("ocIv").onchange = () => { st.ivShift = +$("ocIv").value; save(); evaluate(); };
$("ocAt").onchange = () => { st.at = $("ocAt").value; save(); evaluate(); };
$("ocStop").value = st.stop ?? "";
$("ocStop").onchange = () => { const v = parseFloat($("ocStop").value); st.stop = Number.isFinite(v) && v < 0 ? v : null; save(); evaluate(); };
$("ocSaveForm").onsubmit = async (e) => {
  e.preventDefault();
  const name = $("ocName").value.trim();
  if (!name || !st.legs.length) { message(st.legs.length ? "Give the structure a name." : "Add legs before saving."); return; }
  const { symbol, legs, back, at, ivShift, stop, template } = st;
  try { await api(`/api/saved/structures/${encodeURIComponent(name)}`, { symbol, legs, back, at, ivShift, stop, template, saved: new Date().toISOString() }, "PUT"); }
  catch (err) { message("Error: " + err.message); return; }
  $("ocName").value = ""; message(null); fillSaved(name);
};
$("ocDelete").onclick = async () => {
  const name = $("ocSaved").value;
  if (!name) return;
  await api(`/api/saved/structures/${encodeURIComponent(name)}`, null, "DELETE").catch((e) => message("Error: " + e.message));
  fillSaved();
};
$("ocLevels").onclick = () => {
  if (ev?.status !== "ok") { $("ocLevelsMsg").textContent = "Add legs first."; return; }
  const n = showOnChart(st.symbol, levelsFor(st.legs, ev));
  $("ocLevelsMsg").textContent = `${n} line${n === 1 ? "" : "s"} drawn on every ${st.symbol} chart (showing them again replaces them).`;
};

const q = new URLSearchParams(location.search).get("symbol");
if (q) {
  const sym = cleanSymbol(q) || (DEMO_RE.test(q.toUpperCase()) ? q.toUpperCase() : null);
  if (sym && sym !== st.symbol) st = { ...fresh(), symbol: sym, window: st.window, template: st.template };
}
fillSaved();
render();
loadChain();

let resizing = null;     // the risk graph is drawn to its panel's width: redraw it when the window changes size
window.addEventListener("resize", () => {
  clearTimeout(resizing);
  resizing = setTimeout(() => keepScroll(SCROLLER(), () => {
    drawProfile();
    if (ev?.status === "ok" && view) renderGraph($("ocGraph"), ev, ev.price, view.move);
  }), 150);
});

expose("options", { get state() { return st; }, get view() { return view; }, get ev() { return ev; } });   // for the browser tests (debug.js)
