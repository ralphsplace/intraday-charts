/* The Paper page (/paper): Trades and Backtests, each in its own module; this one switches the sections and keeps
   them in step. Accounts, rules and backtest defaults are set up on the Config page, so they're read again whenever
   this page comes back into view (after editing a rule in another tab, say). */
import { $, api, load, store } from "../util.js";
import { fillRunForm, initBacktests, loadRuns } from "./backtests.js";
import { loadTrades } from "./trades.js";

const TAB_KEY = "intraday-charts:paper-tab";
const SECTIONS = ["trades", "backtests"];
const say = (text, bad) => { $("cfgStatus").textContent = text || ""; $("cfgStatus").classList.toggle("bad", !!bad); };
const sayIn = (id) => (text, bad) => { $(id).textContent = text || ""; $(id).classList.toggle("bad", !!bad); };

let accounts = {}, ruleNames = [], defaults = null, section = "trades";

async function refresh() {
  const [a, r, d] = await Promise.all([api("/api/paper/accounts"), api("/api/paper/rules"), defaults || api("/api/paper/backtest-defaults")]);
  accounts = a.accounts; defaults = d;
  ruleNames = Object.keys(r.rules).sort((x, y) => x.localeCompare(y, undefined, { numeric: true }));
  fillRunForm(ruleNames, accounts, defaults);
}

function showSection(sec) {
  section = sec;
  for (const b of document.querySelectorAll(".cfg-tabs button")) {
    const on = b.dataset.sec === sec;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false");
    $("sec-" + b.dataset.sec).hidden = !on;
  }
  store(TAB_KEY, sec);
  if (sec === "trades") loadTrades(accounts, say).catch((e) => say(e.message, true));
  if (sec === "backtests") loadRuns(sayIn("ppRunMsg"));
}

for (const b of document.querySelectorAll(".cfg-tabs button")) b.onclick = () => showSection(b.dataset.sec);
const again = () => refresh().then(() => section === "trades" && loadTrades(accounts, say)).catch((e) => say(e.message, true));
document.addEventListener("paper:accounts", again);                 // a backtest saved into an account
document.addEventListener("visibilitychange", () => { if (!document.hidden) again(); });

initBacktests(sayIn("ppRunMsg"));
(async () => {
  try { await refresh(); } catch (e) { say("Error: " + e.message, true); }
  const asked = new URLSearchParams(location.search).get("tab");
  showSection(SECTIONS.includes(asked) ? asked : SECTIONS.includes(load(TAB_KEY)) ? load(TAB_KEY) : "trades");
})();
