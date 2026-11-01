/* The Paper page's Backtests section: run a saved rule over a symbol's cached days in the background, follow its
   progress, read the report (the rule against random entries with the same exits), compare runs side by side, and
   save a run's trades into an account to open them on a chart. Data: /api/paper/backtests. */
import { dollars, fmtMin } from "../format.js";
import { $, api, btn, el, load, store } from "../util.js";
import { equityChart } from "./equity.js";

const KEY = "intraday-charts:paper-backtest";
const enc = encodeURIComponent;
let runs = [], shown = null, poll = null, accountsNow = {}, filled = false;

const pct = (x) => (x == null ? "–" : `${x}%`);
const money = (x) => (x == null ? "–" : dollars(x, { d: 2 }));
const ROWS = [["Trades", (s) => s.trades], ["Total P/L", (s) => money(s.total)], ["P/L a day", (s) => money(s.per_day)],
              ["Trades a day", (s) => s.trades_per_day ?? "–"], ["Winners", (s) => pct(s.win_rate)], ["Average win", (s) => money(s.avg_win)],
              ["Average loss", (s) => money(s.avg_loss)], ["Profit factor", (s) => s.profit_factor ?? "–"],
              ["Largest drawdown", (s) => money(s.max_drawdown)], ["Longs", (s) => `${s.long.trades} · ${money(s.long.total)}`],
              ["Shorts", (s) => `${s.short.trades} · ${money(s.short.total)}`], ["Commissions", (s) => money(s.commissions)]];

// the run form: the rules and accounts as they are now; symbol, account, random runs and "skip" from Config's
// backtest defaults the first time; the dates this browser last ran
export function fillRunForm(ruleNames, accounts, defaults) {
  accountsNow = accounts;
  const rs = $("ppRunRule"), cur = rs.value;
  rs.innerHTML = "";
  for (const n of ruleNames) { const o = el("option", null, n); o.value = n; rs.appendChild(o); }
  if (!ruleNames.length) { const o = el("option", null, "Make a rule first (Config, Paper rules)"); o.value = ""; rs.appendChild(o); }
  rs.value = ruleNames.includes(cur) ? cur : ruleNames[0] || "";
  const as = $("ppRunAccount"), acur = as.value;
  as.innerHTML = "";
  for (const [v, t] of [["", "New accounts (the defaults)"], ...Object.keys(accounts).sort().map((n) => [n, n])]) { const o = el("option", null, t); o.value = v; as.appendChild(o); }
  if (!filled && defaults) {                          // the first fill: Config's defaults
    filled = true;
    const saved = load(KEY) || {};
    $("ppRunSymbol").value = defaults.symbol;
    $("ppRunFrom").value = saved.from || ""; $("ppRunTo").value = saved.to || "";
    $("ppRunBase").value = defaults.baseline_runs;
    $("ppRunSkip").checked = defaults.missing === "skip";
    as.value = defaults.account in accounts ? defaults.account : "";
  } else as.value = acur in accounts ? acur : "";
}

export async function loadRuns(say) {
  try { runs = (await api("/api/paper/backtests")).runs; } catch (e) { say(e.message, true); return; }
  const t = $("ppRuns");
  t.innerHTML = "";
  const head = el("tr");
  for (const h of ["", "Rule", "Symbol", "Days", "Trades", "P/L", "Winners", "Random entries", ""]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  if (!runs.length) { const td = el("td", "muted", "No backtests yet."); td.colSpan = 9; t.appendChild(el("tr")).appendChild(td); }
  for (const r of runs) {
    const tr = el("tr");
    tr.dataset.id = r.id;
    const tick = el("input"); tick.type = "checkbox"; tick.className = "pp-tick"; tick.value = r.id; tick.setAttribute("aria-label", `Compare ${r.rule_name}`);
    const s = r.stats, b = r.baseline;
    const status = r.status === "running" ? `running ${Math.round((100 * r.done) / (r.total || 1))}%` : r.status === "failed" ? "failed" : "";
    tr.appendChild(el("td")).appendChild(tick);
    tr.append(el("td", "cfg-name", r.rule_name), el("td", null, r.symbol), el("td", "muted small", `${r.start} to ${r.end}`),
              el("td", null, s ? String(s.trades) : status), el("td", s && s.total >= 0 ? "up" : "down", s ? money(s.total) : ""),
              el("td", null, s ? pct(s.win_rate) : ""), el("td", "muted small", b ? `${money(b.per_day)} a day, ${pct(b.win_rate)} winners` : ""));
    const acts = el("td", "cfg-acts");
    acts.append(btn("Report", () => showReport(r.id, say), `Show the report of ${r.rule_name}`, "pp-report-btn"),
                btn("Delete", async (e) => {
                  const me = e.currentTarget;
                  if (me.dataset.sure !== "1") { me.dataset.sure = "1"; me.textContent = "Delete? Yes"; return; }
                  await api(`/api/paper/backtests/${r.id}`, null, "DELETE").catch((err) => say(err.message, true));
                  if (shown === r.id) { $("ppReport").innerHTML = ""; shown = null; }
                  loadRuns(say);
                }, `Delete this backtest`, "danger"));
    tr.appendChild(acts);
    t.appendChild(tr);
  }
  if (runs.some((r) => r.status === "running")) { clearTimeout(poll); poll = setTimeout(() => loadRuns(say), 1000); }
  else if (shown && runs.some((r) => r.id === shown)) showReport(shown, say, true);
}

async function showReport(id, say, quiet = false) {
  shown = id;
  let run;
  try { run = await api(`/api/paper/backtests/${id}`); } catch (e) { say(e.message, true); return; }
  const box = $("ppReport");
  box.innerHTML = "";
  box.appendChild(el("h3", null, `${run.rule_name} · ${run.symbol} · ${run.start} to ${run.end}` + (run.report?.demo ? " (synthetic data)" : "")));
  if (run.status === "running") { box.appendChild(el("p", "muted", `Running: ${run.done} of ${run.total} days…`)); return; }
  if (run.status === "failed") { box.appendChild(el("p", "bad", run.error)); return; }
  const rep = run.report;
  if (rep.skipped?.count) box.appendChild(el("p", "bad", `${rep.skipped.count} entry signal${rep.skipped.count === 1 ? " was" : "s were"} skipped: ${rep.skipped.first}` +
                                            ". Use fewer shares, or an account with more cash."));
  if (run.skipped?.length) box.appendChild(el("p", "muted small", `Skipped ${run.skipped.length} day(s) without cached bars: ${run.skipped.join(", ")}`));
  box.appendChild(statsTable([["This rule", rep.stats], [`Random entries (${rep.baseline_runs} runs)`, rep.baseline]].filter(([, s]) => s)));
  const eq = el("div", "pp-equity"); box.appendChild(eq);
  equityChart(eq, rep.equity.map((e) => ({ value: e.equity, label: e.day })), rep.start_cash);
  // save into an account
  const save = el("div", "cfg-row");
  const sel = el("select"); sel.setAttribute("aria-label", "Account to save the trades into");
  for (const n of Object.keys(accountsNow).sort()) { const o = el("option", null, n); o.value = n; sel.appendChild(o); }
  save.append(el("span", null, "Save the trades into"), sel,
              btn("Save", async () => {
                try { const r = await api(`/api/paper/backtests/${id}/save`, { account: sel.value }); say(`Saved ${r.saved_days} day(s) into "${sel.value}": see Trades.`); document.dispatchEvent(new Event("paper:accounts")); }
                catch (e) { say(e.message, true); }
              }, "Save these trades into the account, as sessions that open on a chart", "pp-save"),
              el("span", "muted small", "each day then opens on a chart (Trades, Open on the chart)"));
  if (!sel.options.length) save.replaceChildren(el("span", "muted small", "Make an account (Config, Paper accounts) to save these trades into."));
  box.appendChild(save);
  const t = el("table", "cfg-table pp-trades");
  const head = el("tr");
  for (const h of ["Day", "Side", "Shares", "In", "Out", "P/L", "Exit"]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  for (const x of rep.trades.slice(0, 500)) {
    t.appendChild(el("tr")).append(el("td", null, x.day), el("td", x.side === "long" ? "up" : "down", x.side), el("td", null, String(x.qty)),
      el("td", null, `${fmtMin(x.entry_minute)} @ ${x.entry.toFixed(2)}`), el("td", null, `${fmtMin(x.exit_minute)} @ ${x.exit.toFixed(2)}`),
      el("td", x.pnl >= 0 ? "up" : "down", money(x.pnl)), el("td", "muted small", x.why || ""));
  }
  if (rep.trades.length > 500) box.appendChild(el("p", "muted small", `The first 500 of ${rep.trades.length} trades.`));
  box.appendChild(t);
  if (!quiet) box.scrollIntoView({ block: "start" });
}

function statsTable(cols) {
  const t = el("table", "cfg-table pp-stats");
  const head = el("tr"); head.appendChild(el("th"));
  for (const [name] of cols) head.appendChild(el("th", null, name));
  t.appendChild(head);
  for (const [label, f] of ROWS) {
    const tr = el("tr"); tr.appendChild(el("td", "muted", label));
    for (const [, s] of cols) tr.appendChild(el("td", null, String(f(s))));
    t.appendChild(tr);
  }
  return t;
}

async function compare(say) {
  const ids = [...document.querySelectorAll(".pp-tick:checked")].map((x) => x.value);
  if (ids.length < 2) { say("Tick two or more finished runs to compare.", true); return; }
  const done = runs.filter((r) => ids.includes(r.id) && r.stats);
  const box = $("ppReport");
  box.innerHTML = "";
  box.appendChild(el("h3", null, "Compared"));
  box.appendChild(statsTable(done.map((r) => [`${r.rule_name} · ${r.symbol} · ${r.start} to ${r.end}`, r.stats])));
  shown = null;
}

export function initBacktests(say) {
  $("ppRun").onsubmit = async (e) => {
    e.preventDefault();
    const body = { rule_name: $("ppRunRule").value, symbol: $("ppRunSymbol").value.trim().toUpperCase(), start: $("ppRunFrom").value,
                   end: $("ppRunTo").value, account: $("ppRunAccount").value || null, missing: $("ppRunSkip").checked ? "skip" : "stop",
                   baseline_runs: parseInt($("ppRunBase").value, 10) || 0 };
    if (!body.rule_name) { say("Make a rule first: Config, Paper rules.", true); return; }
    store(KEY, { symbol: body.symbol, from: body.start, to: body.end });
    try { const r = await api("/api/paper/backtests", body); say(`Started "${r.rule_name}" on ${r.symbol}.`); shown = r.id; }
    catch (err) { say(err.message, true); return; }
    loadRuns(say);
  };
  $("ppCompare").onclick = () => compare(say);
}
