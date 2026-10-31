/* Starts the expected-move page (/expected-move?symbols=AMZN,LLY&date=2026-10-30): shows what's cached, asks the
   TWS collector for fresh option quotes when they're missing or stale (or on Refresh), and waits for them. */
import { EXPECTED_MOVE_KEY } from "../keys.js";
import { $, api, keepScroll, load, orElse, setValue, store, submitted, trackEdits } from "../util.js";
import { renderCards, renderSummary } from "./render.js";

const POLL_MS = 3000, GIVE_UP_MS = 3 * 60 * 1000;
let current = null, poll = null, asking = 0, waitingSince = 0, collector = null;
const isDemo = (s) => s.endsWith("-DEMO");

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });     // YYYY-MM-DD
const parse = (raw) => [...new Set((raw || "").toUpperCase().split(/[\s,;]+/).filter(Boolean))];

function message(text) { $("emMsg").hidden = !text; $("emMsg").textContent = text || ""; }

// what a symbol without numbers is waiting for, from the collector's last status report
function waiting(it) {
  if (isDemo(it.symbol)) return "no synthetic quotes for this symbol in this data folder";
  if (it.message && it.status === "missing" && !waitingSince) return it.message;
  if (!collector || !collector.running) return "the request is saved and runs when the TWS collector starts (user guide: Connecting to TWS)";
  if (!collector.connected) return `waiting for TWS: ${collector.message || "not connected"}`;
  if ((collector.bad_symbols || {})[it.symbol]) return `IBKR doesn't know ${it.symbol}`;
  return "asking TWS for option quotes…";
}

async function fetchQuotes(symbols, date) {
  const real = symbols.filter((s) => !isDemo(s));
  if (!real.length) return;
  waitingSince = Date.now();
  await api("/api/expected-move/request", { symbols: real.join(" "), date }).catch((e) => message("Error: " + e.message));
}

async function show(symbols, date, refresh = false) {
  clearTimeout(poll);
  const mine = ++asking;
  current = { symbols, date };
  setValue($("emSyms"), symbols.join(" "));
  setValue($("emDate"), date);
  $("demoBanner").hidden = !symbols.some(isDemo);
  history.replaceState(null, "", `/expected-move?symbols=${encodeURIComponent(symbols.join(","))}&date=${date}`);
  store(EXPECTED_MOVE_KEY, current);
  document.title = `${symbols.join(" ")} · Expected move`;
  let v;
  try { v = await api(`/api/expected-move?symbols=${encodeURIComponent(symbols.join(","))}&date=${date}`); }
  catch (e) { if (mine === asking) message("Error: " + e.message); return; }
  if (mine !== asking) return;
  message(null);
  const stale = v.items.filter((it) => !isDemo(it.symbol) && (it.status === "missing" || (it.age != null && it.age > v.stale_seconds)));
  if (refresh || (stale.length && !waitingSince)) await fetchQuotes(refresh ? symbols : stale.map((it) => it.symbol), date);
  collector = await orElse(api("/api/collector"), null, "Collector status");
  if (mine !== asking) return;
  keepScroll(null, () => {                         // a refresh doesn't move the page
    renderSummary($("emSummary"), v.items, waiting);
    renderCards($("emCards"), v.items);
  });
  // still waiting for fresh quotes: ask again in a moment (they arrive as the collector works through the list)
  const pending = waitingSince && v.items.some((it) => !isDemo(it.symbol) && (it.status === "missing" || (it.fetched || 0) * 1000 < waitingSince));
  if (pending && Date.now() - waitingSince < GIVE_UP_MS) {
    $("emStatus").textContent = "Waiting for option quotes from TWS…";
    poll = setTimeout(() => show(current.symbols, current.date), POLL_MS);
  } else {
    if (pending) message("Still no fresh quotes after 3 minutes: check the collector (Load data… on a chart page shows its status).");
    waitingSince = 0;
    const ok = v.items.filter((it) => it.status === "ok").length;
    $("emStatus").textContent = `${ok} of ${v.items.length} with quotes`;
  }
}

trackEdits($("emSyms"), () => (current ? current.symbols.join(" ") : ""));
trackEdits($("emDate"), () => (current ? current.date : $("emDate").value));
$("emForm").onsubmit = (e) => {
  e.preventDefault();
  submitted($("emSyms")); submitted($("emDate"));
  const syms = parse($("emSyms").value);
  if (!syms.length || !$("emDate").value) { message("Type one or more stock symbols and pick a date."); return; }
  waitingSince = 0;
  show(syms, $("emDate").value);
};
$("emRefresh").onclick = () => { if (current) { waitingSince = 0; show(current.symbols, current.date, true); } };

const q = new URLSearchParams(location.search), saved = load(EXPECTED_MOVE_KEY) || {};
const startSyms = parse(q.get("symbols") || (saved.symbols || []).join(" "));
const startDate = q.get("date") || saved.date || today();
$("emDate").value = startDate;
if (startSyms.length) show(startSyms, startDate);
else message("Type one or more stock symbols (e.g. AMZN LLY MA), pick the date the expiry should be on or after, and press Show.");

window.__expectedMove = { get current() { return current; } };   // for the browser tests
