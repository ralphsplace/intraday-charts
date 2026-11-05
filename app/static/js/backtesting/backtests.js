/* The Backtesting page's Backtests section: run a saved strategy over a symbol's cached days in the background, follow its
   progress, read the report (the strategy against random entries with the same exits), compare runs side by side, and
   save a run's trades into an account to open them on a chart. Data: /api/backtests. */
import { dollars } from "../format.js";
import { $, api, btn, el, load, store } from "../util.js";
import { missingSelect } from "./missing.js";
import { renderReport } from "./report.js";

const KEY = "intraday-charts:backtest-form";
const enc = encodeURIComponent;
let runs = [], shown = null, poll = null, filled = false;

const active = (r) => ["queued", "running", "fetching", "deleting"].includes(r.status);      // still going: asked again every second
const pct = (x) => (x == null ? "–" : `${x}%`);
const money = (x) => (x == null ? "–" : dollars(x, { d: 2 }));
const ROWS = [["Trades", (s) => s.trades], ["Total P/L", (s) => money(s.total)], ["P/L a day", (s) => money(s.per_day)],
              ["Trades a day", (s) => s.trades_per_day ?? "–"], ["Winners", (s) => pct(s.win_rate)], ["Average win", (s) => money(s.avg_win)],
              ["Average loss", (s) => money(s.avg_loss)], ["Profit factor", (s) => s.profit_factor ?? "–"],
              ["Largest drawdown", (s) => money(s.max_drawdown)], ["Longs", (s) => `${s.long.trades} · ${money(s.long.total)}`],
              ["Shorts", (s) => `${s.short.trades} · ${money(s.short.total)}`], ["Commissions", (s) => money(s.commissions)]];

// the run form: the strategies and accounts as they are now; symbol, account, random runs and missing days from Config's
// backtest defaults the first time; the dates this browser last ran
export function fillRunForm(names, accounts, defaults) {
  const rs = $("ppRunRule"), cur = rs.value;
  rs.innerHTML = "";
  for (const n of names) { const o = el("option", null, n); o.value = n; rs.appendChild(o); }
  if (!names.length) { const o = el("option", null, "Make a strategy first (Config, Signal strategies)"); o.value = ""; rs.appendChild(o); }
  rs.value = names.includes(cur) ? cur : names[0] || "";
  const as = $("ppRunAccount"), acur = as.value;
  as.innerHTML = "";
  for (const [v, t] of [["", "New accounts (the defaults)"], ...Object.keys(accounts).sort().map((n) => [n, n])]) { const o = el("option", null, t); o.value = v; as.appendChild(o); }
  if (!filled && defaults) {                          // the first fill: Config's defaults
    filled = true;
    const saved = load(KEY) || {};
    $("ppRunSymbol").value = defaults.symbol;
    $("ppRunFrom").value = saved.from || ""; $("ppRunTo").value = saved.to || "";
    $("ppRunBase").value = defaults.baseline_runs;
    missingSelect($("ppRunMissing")).value = defaults.missing;
    as.value = defaults.account in accounts ? defaults.account : "";
  } else as.value = acur in accounts ? acur : "";
}

export async function loadRuns(say) {
  try { runs = (await api("/api/backtests")).runs; } catch (e) { say(e.message, true); return; }
  const t = $("ppRuns");
  t.innerHTML = "";
  const head = el("tr");
  for (const h of ["", "Strategy", "Symbol", "Days", "Trades", "P/L", "Winners", "Random entries", ""]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  if (!runs.length) { const td = el("td", "muted", "No backtests yet."); td.colSpan = 9; t.appendChild(el("tr")).appendChild(td); }
  for (const r of runs) {
    const tr = el("tr");
    tr.dataset.id = r.id;
    const tick = el("input"); tick.type = "checkbox"; tick.className = "pp-tick"; tick.value = r.id; tick.setAttribute("aria-label", `Compare ${r.strategy_name}`);
    const s = r.stats, b = r.baseline;
    const status = r.status === "running" ? `running ${Math.round((100 * r.done) / (r.total || 1))}%` + (r.days?.running?.length ? ` · ${r.days.running.length} day${r.days.running.length === 1 ? "" : "s"} going` : "")
      : r.status === "queued" ? "queued" : r.status === "deleting" ? "stopping and deleting…" : r.status === "interrupted" ? "interrupted"
      : r.status === "fetching" ? `fetching ${r.fetch?.got ?? 0} of ${r.fetch?.wanted ?? "?"} days` : r.status === "failed" ? "failed" : "";
    tr.appendChild(el("td")).appendChild(tick);
    tr.append(el("td", "cfg-name", r.strategy_name), el("td", null, r.symbol), el("td", "muted small", `${r.start} to ${r.end}`),
              el("td", null, s ? String(s.trades) : status), el("td", s && s.total >= 0 ? "up" : "down", s ? money(s.total) : ""),
              el("td", null, s ? pct(s.win_rate) : ""), el("td", "muted small", b ? `${money(b.per_day)} a day, ${pct(b.win_rate)} winners` : ""));
    const acts = el("td", "cfg-acts");
    acts.append(btn("Report", () => { showReport(r.id, say); loadRuns(say); }, `Show the report of ${r.strategy_name}`, "pp-report-btn"),
                btn("Delete", async (e) => {
                  const me = e.currentTarget;
                  if (me.dataset.sure !== "1") { me.dataset.sure = "1"; me.textContent = active(r) ? "Stop and delete? Yes" : "Delete? Yes"; return; }
                  try {
                    const result = await api(`/api/backtests/${r.id}`, null, "DELETE");
                    if (result.deleting) say("Stopping the job; its report will disappear when it stops.");
                  } catch (err) { say(err.message, true); return; }
                  if (shown === r.id) { $("ppReport").innerHTML = ""; shown = null; }
                  loadRuns(say);
                }, `Stop this job and delete its report`, "danger"));
    tr.appendChild(acts);
    t.appendChild(tr);
  }
  for (const tr of t.querySelectorAll("tr[data-id]")) tr.classList.toggle("on", tr.dataset.id === shown);
  if (runs.some(active)) { clearTimeout(poll); poll = setTimeout(() => loadRuns(say), 1000); }
  if (shown && runs.some((r) => r.id === shown)) showReport(shown, say, true);       // live while it runs, then done
}

async function showReport(id, say, quiet = false) {
  shown = id;
  let run;
  try { run = await api(`/api/backtests/${id}`); } catch (e) { say(e.message, true); return; }
  if (shown !== id) return;
  renderReport($("ppReport"), run, { say, statsTable, money, quiet });
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
  box.appendChild(statsTable(done.map((r) => [`${r.strategy_name} · ${r.symbol} · ${r.start} to ${r.end}`, r.stats])));
  shown = null;
}

export function initBacktests(say) {
  $("ppRun").onsubmit = async (e) => {
    e.preventDefault();
    const body = { strategy_name: $("ppRunRule").value, symbol: $("ppRunSymbol").value.trim().toUpperCase(), start: $("ppRunFrom").value,
                   end: $("ppRunTo").value, account: $("ppRunAccount").value || null, missing: $("ppRunMissing").value,
                   baseline_runs: parseInt($("ppRunBase").value, 10) || 0 };
    if (!body.strategy_name) { say("Make a strategy first: Config, Signal strategies.", true); return; }
    store(KEY, { symbol: body.symbol, from: body.start, to: body.end });
    try { const r = await api("/api/backtests", body); say(`Queued "${r.strategy_name}" on ${r.symbol}.`); shown = r.id; }
    catch (err) { say(err.message, true); return; }
    loadRuns(say);
  };
  $("ppCompare").onclick = () => compare(say);
}
