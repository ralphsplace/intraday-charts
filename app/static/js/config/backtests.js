/* The Config page's Backtests section: what a new backtest starts with on the Paper page (symbol, whose cash and
   costs, how many random-entry runs, and whether days without cached bars are skipped). Kept in the application
   config. Data: /api/paper/backtest-defaults. */
import { $, api, el } from "../util.js";

let say = () => {};

function fill(d, accounts) {
  $("cfgBtSymbol").value = d.symbol;
  const as = $("cfgBtAccount");
  as.innerHTML = "";
  const names = Object.keys(accounts).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  for (const [v, t] of [["", "New accounts (the defaults)"], ...names.map((n) => [n, n])]) { const o = el("option", null, t); o.value = v; as.appendChild(o); }
  if (d.account && !names.includes(d.account)) {           // renamed or deleted since: shown, so it can be changed
    const o = el("option", null, `${d.account} (no longer exists)`); o.value = d.account; as.appendChild(o);
  }
  as.value = d.account;
  $("cfgBtBase").value = d.baseline_runs;
  $("cfgBtSkip").checked = d.missing === "skip";
}

export async function loadBacktestDefaults(sayFn) {
  say = sayFn;
  const [d, a] = await Promise.all([api("/api/paper/backtest-defaults"), api("/api/paper/accounts")]);
  fill(d, a.accounts);
}

async function save() {
  const body = { symbol: $("cfgBtSymbol").value.trim().toUpperCase(), account: $("cfgBtAccount").value,
                 baseline_runs: parseInt($("cfgBtBase").value, 10), missing: $("cfgBtSkip").checked ? "skip" : "stop" };
  if (Number.isNaN(body.baseline_runs)) { say("cfgBtMsg", "Random runs are 0 to 20.", true); return; }
  try { await api("/api/paper/backtest-defaults", body, "PUT"); say("cfgBtMsg", "Saved. New backtests start with these."); }
  catch (e) { say("cfgBtMsg", e.message, true); return; }
  await loadBacktestDefaults(say);
}

export function initBacktestDefaults(sayFn) {
  say = sayFn;
  $("cfgBtSave").onclick = save;
  $("cfgBt").onsubmit = (e) => { e.preventDefault(); save(); };
  $("cfgBtReset").onclick = async () => {
    try { await api("/api/paper/backtest-defaults", null, "DELETE"); say("cfgBtMsg", "Back to the built-in defaults."); }
    catch (e) { say("cfgBtMsg", e.message, true); }
    await loadBacktestDefaults(say);
  };
}
