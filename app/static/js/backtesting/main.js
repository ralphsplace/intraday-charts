/* The Backtesting page (/backtesting): run a signal strategy over past days, follow its runs, read and compare their
   reports (backtests.js). Accounts, rules, strategies and backtest defaults are set up on the Config page, so
   they're read again whenever this page comes back into view (after editing a strategy in another tab, say). */
import { $, api } from "../util.js";
import { fillRunForm, initBacktests, loadRuns } from "./backtests.js";

const say = (text, bad) => { $("cfgStatus").textContent = text || ""; $("cfgStatus").classList.toggle("bad", !!bad); };
const sayRun = (text, bad) => { $("ppRunMsg").textContent = text || ""; $("ppRunMsg").classList.toggle("bad", !!bad); };

let defaults = null;

async function refresh() {
  const [a, r, d] = await Promise.all([api("/api/backtest-accounts"), api("/api/signal-strategies"), defaults || api("/api/backtest-defaults")]);
  defaults = d;
  const names = Object.keys(r.strategies).sort((x, y) => x.localeCompare(y, undefined, { numeric: true }));
  fillRunForm(names, a.accounts, defaults);
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh().catch((e) => say(e.message, true)); });
initBacktests(sayRun);
(async () => {
  try { await refresh(); } catch (e) { say("Error: " + e.message, true); }
  loadRuns(sayRun);
})();
