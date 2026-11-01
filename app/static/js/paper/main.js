/* The Paper page (/paper): Trades, Rules, Backtests and Accounts, each in its own module; this one switches the
   sections and keeps them in step (a rule saved shows in the Backtests menu; an account changed, everywhere). */
import { initPaper, loadPaper } from "../config/paper.js";
import { $, api, load, store } from "../util.js";
import { fillRunForm, initBacktests, loadRuns } from "./backtests.js";
import { initRules, loadRules, ruleNames } from "./rules.js";
import { loadTrades } from "./trades.js";

const TAB_KEY = "intraday-charts:paper-tab";
const SECTIONS = ["trades", "rules", "backtests", "accounts"];
const say = (text, bad) => { $("cfgStatus").textContent = text || ""; $("cfgStatus").classList.toggle("bad", !!bad); };
const sayIn = (id) => (text, bad) => { $(id).textContent = text || ""; $(id).classList.toggle("bad", !!bad); };
const sayAt = (id, text, bad) => sayIn(id)(text, bad);          // the Accounts section names its message box (config/paper.js)

let accounts = {};

async function refreshAccounts() {
  accounts = (await api("/api/paper/accounts")).accounts;
  await loadTrades(accounts, say);
  fillRunForm(ruleNames(), accounts);
}

function showSection(sec) {
  for (const b of document.querySelectorAll(".cfg-tabs button")) {
    const on = b.dataset.sec === sec;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false");
    $("sec-" + b.dataset.sec).hidden = !on;
  }
  store(TAB_KEY, sec);
  if (sec === "trades") refreshAccounts().catch((e) => say(e.message, true));
  if (sec === "backtests") loadRuns(sayIn("ppRunMsg"));
}

for (const b of document.querySelectorAll(".cfg-tabs button")) b.onclick = () => showSection(b.dataset.sec);
document.addEventListener("paper:rules", () => fillRunForm(ruleNames(), accounts));
document.addEventListener("paper:accounts", () => refreshAccounts().catch((e) => say(e.message, true)));

initPaper(sayAt);
initRules(sayIn("ppRuleMsg"));
initBacktests(sayIn("ppRunMsg"));
(async () => {
  try {
    await Promise.all([loadPaper(sayAt), loadRules(sayIn("ppRuleMsg"))]);
    await refreshAccounts();
  } catch (e) { say("Error: " + e.message, true); }
  showSection(SECTIONS.includes(load(TAB_KEY)) ? load(TAB_KEY) : "trades");
})();
