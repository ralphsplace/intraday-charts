/* Starts the earnings page (/earnings?symbol=NVDA): asks the server for the view, and when the daily prices or
   earnings dates aren't cached yet, asks the TWS collector for them and waits. */
import { EARNINGS_DAYS_KEY, EARNINGS_MODE_KEY, EARNINGS_SYMBOL_KEY } from "../keys.js";
import { $, api, btn, cleanSymbol as cleanStock, load, orElse, setValue, store, submitted, trackEdits } from "../util.js";
import { EarningsChart } from "./chart.js";
import { fmtDate, renderLegend } from "./legend.js";
import { DEFAULT_MODE, MODES } from "./modes.js";

// a stock symbol, or a synthetic one ending in -DEMO (tests/synthetic.py), which is only ever read from the cache
const cleanSymbol = (s) => cleanStock(s) || (/^[A-Z]{1,6}-DEMO$/.test((s || "").trim().toUpperCase()) ? s.trim().toUpperCase() : null);
const isDemo = (s) => s.endsWith("-DEMO");

const chart = new EarningsChart($("chart"), $("ends"));
let current = null, view = null, poll = null, asking = 0;   // asking: the latest request; older replies are dropped
let mode = MODES[load(EARNINGS_MODE_KEY)] ? load(EARNINGS_MODE_KEY) : DEFAULT_MODE;
const asked = new Set();
// trading days around day 0: what this browser chose, or the server's default (filled in from the first view)
let days = load(EARNINGS_DAYS_KEY) || {};
if (![days.before, days.after].every((n) => Number.isInteger(n) && n >= 1)) days = {};

// the Relative % / Price $ switch, built from MODES
const modeBtns = Object.entries(MODES).map(([key, m]) => {
  const b = btn(m.button, () => setMode(key)); b.title = m.tip; b.dataset.mode = key;
  $("modes").appendChild(b);
  return b;
});
function setMode(key) {
  mode = key;
  store(EARNINGS_MODE_KEY, key);
  modeBtns.forEach((b) => b.classList.toggle("active", b.dataset.mode === key));
  $("explain").textContent = MODES[key].explain + " Day 0 is the first session that trades on the report: the report " +
    "day when it came before the open or during the session, the next session when it came after the close.";
  draw();
}

// the Days before / after boxes: a valid change redraws the view and is remembered in this browser
function setDays() {
  const ins = [$("daysBefore"), $("daysAfter")];
  ins.forEach((i) => i.classList.toggle("bad", !i.checkValidity()));
  if (!ins.every((i) => i.checkValidity())) return;
  days = { before: +ins[0].value, after: +ins[1].value };
  store(EARNINGS_DAYS_KEY, days);
  if (current) show(current);
}
for (const box of [$("daysBefore"), $("daysAfter")]) {
  box.onchange = setDays;                                                  // arrows, or leaving the box
  box.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); setDays(); } };
}
$("daysForm").onsubmit = (e) => e.preventDefault();
// the boxes are what you typed; they're only filled in from a reply when still empty (the server's defaults)
function showDays(v) {
  if ($("daysBefore").value === "") $("daysBefore").value = v.before;
  if ($("daysAfter").value === "") $("daysAfter").value = v.after;
  $("daysBefore").max = $("daysAfter").max = v.max_days;
}
if (days.before) { $("daysBefore").value = days.before; $("daysAfter").value = days.after; }

function message(text) { $("msg").hidden = !text; $("msg").textContent = text || ""; }

function draw() {
  const qs = view?.quarters || [];
  // each line's end label: the report's month and year, e.g. "Jul '26"
  qs.forEach((q) => { const d = new Date(q.report_date + "T12:00:00");
                      q.label = d.toLocaleDateString("en-US", { month: "short" }) + " '" + String(d.getFullYear()).slice(2); });
  chart.show(qs, mode);
  const legend = (x) => renderLegend($("legend"), qs, mode, x, (i) => chart.highlight(i));
  chart.onHover = legend;
  legend(null);
}

async function waitingText(v) {
  const st = await orElse(api("/api/collector"), null, "Collector status");
  const what = v.missing.join(" and ");
  if (!st || !st.running) return `No ${what} for ${v.symbol} yet. The request is saved and runs when the TWS collector starts (user guide: Connecting to TWS).`;
  if (!st.connected) return `Waiting for TWS. ${st.message || ""}`;
  if ((st.bad_symbols || {})[v.symbol]) return `IBKR doesn't know ${v.symbol}. Check the symbol.`;
  return `Fetching ${v.symbol}'s ${what}…`;
}

async function show(sym) {
  clearTimeout(poll);
  current = sym;
  const mine = ++asking;
  setValue($("sym"), sym);
  $("title").textContent = `${sym} around its last earnings reports`;
  document.title = `${sym} · Earnings`;
  $("demoBanner").hidden = !isDemo(sym);
  history.replaceState(null, "", "/earnings?symbol=" + encodeURIComponent(sym));
  store(EARNINGS_SYMBOL_KEY, sym);
  let v;
  const around = days.before ? `&before=${days.before}&after=${days.after}` : "";
  try { v = await api("/api/earnings?symbol=" + encodeURIComponent(sym) + around); }
  catch (e) { if (mine === asking) message("Error: " + e.message); return; }
  if (mine !== asking) return;
  view = v;
  showDays(v);
  $("source").textContent = v.source ? `Earnings dates: ${v.source}` + (v.fetched ? `, looked up ${fmtDate(new Date(v.fetched * 1000).toISOString().slice(0, 10))}.` : ".") : "";
  if (v.status === "ok") {
    message(null);
    $("status").textContent = `${v.quarters.length} report${v.quarters.length > 1 ? "s" : ""}, ${v.before} trading days before day 0 and ${v.after} after`;
    draw();
    return;
  }
  view = { quarters: [] }; draw();
  $("status").textContent = "";
  if (v.status === "missing") {
    if (isDemo(sym)) { message(`No synthetic data for ${sym} in this data folder.`); return; }
    if (!asked.has(sym)) { asked.add(sym); await orElse(api("/api/earnings/request", { symbol: sym }), null, `Asking for ${sym}'s earnings`); }
    message(await waitingText(v));
    poll = setTimeout(() => show(sym), 3000);
    return;
  }
  message(v.message || "Nothing to show.");
}

trackEdits($("sym"), () => current || "");
$("symForm").onsubmit = (e) => {
  e.preventDefault();
  submitted($("sym"));
  const sym = cleanSymbol($("sym").value);
  if (!sym) { $("sym").classList.add("bad"); message(`"${$("sym").value}" isn't a stock symbol.`); return; }
  $("sym").classList.remove("bad");
  show(sym);
};

setMode(mode);
const start = cleanSymbol(new URLSearchParams(location.search).get("symbol") || "") || load(EARNINGS_SYMBOL_KEY);
if (start) show(start); else message("Type a stock symbol and press Enter.");

window.__earnings = { chart, get view() { return view; }, get mode() { return mode; } };   // for the browser tests
