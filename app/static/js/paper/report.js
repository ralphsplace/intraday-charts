/* A backtest's report on the Paper page, live while it runs: its progress, the strategy against random entries,
   the equity by day, saving its trades into an account, and below, two tabs: Trades (click a day to see it on a
   chart, review-pane.js) and Log (what the run did, day by day: signals acted on, refused or not taken, fills).
   The run: GET /api/paper/backtests/<id> (backtests.js asks again every second while it runs). */
import { fmtMin } from "../format.js";
import { api, btn, el } from "../util.js";
import { equityChart } from "./equity.js";
import { openReview } from "./review-pane.js";

let tab = "trades", logLevel = "", lastId = null, lastStatus = null;
const LEVELS = [["", "Everything"], ["day", "A line a day"], ["warn", "Refused and skipped"]];

// o: { say, accounts, statsTable, money, quiet }
export function renderReport(box, run, o) {
  const fresh = run.id !== lastId;
  if (!fresh && lastStatus !== "done" && run.status === "done") tab = "trades";    // it just finished: its trades
  lastId = run.id; lastStatus = run.status;
  const logBox = box.querySelector(".pp-log");
  const atEnd = !logBox || logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 4;   // following the log
  const wasAt = logBox?.scrollTop || 0;
  box.innerHTML = "";
  box.dataset.id = run.id;
  box.appendChild(el("h3", null, `${run.strategy_name} · ${run.symbol} · ${run.start} to ${run.end}` + (run.report?.demo ? " (synthetic data)" : "")));
  const rep = run.report;
  if (run.status === "fetching") {
    const f = run.fetch || { got: 0, wanted: 0 };
    const bar = el("div", "pp-progress"); const fill = el("div"); fill.style.width = `${Math.round((100 * f.got) / (f.wanted || 1))}%`; bar.appendChild(fill);
    box.append(el("p", "muted", `Fetching from TWS: ${f.got} of ${f.wanted} day(s) without cached bars. The run starts when they're in…`), bar);
  } else if (run.status === "running") {
    const bar = el("div", "pp-progress"); const fill = el("div"); fill.style.width = `${Math.round((100 * run.done) / (run.total || 1))}%`; bar.appendChild(fill);
    box.append(el("p", "muted", `Running: ${run.done} of ${run.total} steps (the strategy's days, then the random entries)…`), bar);
  } else if (run.status === "failed") {
    box.appendChild(el("p", "bad", run.error));
  } else {
    if (rep.skipped?.count) box.appendChild(el("p", "bad", `${rep.skipped.count} entry signal${rep.skipped.count === 1 ? " was" : "s were"} refused: ${rep.skipped.first}` +
                                              ". Use fewer shares, or an account with more cash (see Log)."));
    if (run.skipped?.length) box.appendChild(el("p", "muted small", `Skipped ${run.skipped.length} day(s) without bars: ${run.skipped.join(", ")}`));
    box.appendChild(o.statsTable([["This strategy", rep.stats], [`Random entries (${rep.baseline_runs} runs)`, rep.baseline]].filter(([, s]) => s)));
    const eq = el("div", "pp-equity"); box.appendChild(eq);
    equityChart(eq, rep.equity.map((e) => ({ value: e.equity, label: e.day })), rep.start_cash);
    box.appendChild(saveRow(run, o));
  }
  // the tabs
  const nTrades = rep?.trades?.length ?? 0, nLog = (run.log || []).length;
  const tabs = el("nav", "cfg-kinds pp-tabs"); tabs.setAttribute("role", "tablist");
  const pane = el("div", "pp-pane");
  const show = (t) => {
    tab = t;
    for (const b of tabs.children) { const on = b.dataset.tab === t; b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false"); }
    pane.innerHTML = "";
    pane.appendChild(t === "trades" ? tradesTable(run, o) : logView(run));
    if (t === "log") { const lb = pane.querySelector(".pp-log"); lb.scrollTop = atEnd || fresh ? lb.scrollHeight : wasAt; }
  };
  for (const [t, label] of [["trades", `Trades (${nTrades})`], ["log", `Log (${nLog})`]]) {
    const b = btn(label, () => show(t), null, ""); b.dataset.tab = t; b.setAttribute("role", "tab"); tabs.appendChild(b);
  }
  box.append(tabs, pane);
  show(run.status !== "done" && run.status !== "failed" && fresh ? "log" : tab);
  if (!o.quiet) box.scrollIntoView({ block: "start" });
}

function saveRow(run, o) {
  const save = el("div", "cfg-row");
  const sel = el("select"); sel.setAttribute("aria-label", "Account to save the trades into");
  for (const n of Object.keys(o.accounts).sort()) { const x = el("option", null, n); x.value = n; sel.appendChild(x); }
  save.append(el("span", null, "Save the trades into"), sel,
              btn("Save", async () => {
                try { const r = await api(`/api/paper/backtests/${run.id}/save`, { account: sel.value }); o.say(`Saved ${r.saved_days} day(s) into "${sel.value}": see Trades.`); document.dispatchEvent(new Event("paper:accounts")); }
                catch (e) { o.say(e.message, true); }
              }, "Save these trades into the account, as sessions that open on a chart", "pp-save"),
              el("span", "muted small", "each day then opens on a chart (Trades, Open on the chart)"));
  if (!sel.options.length) save.replaceChildren(el("span", "muted small", "Make an account (Config, Paper accounts) to save these trades into."));
  return save;
}

// a day, as a button that shows it on a chart (once the run is done)
function dayLink(run, day) {
  if (run.status !== "done" || !day) return el("span", null, day || "");
  const b = btn(day, () => openReview(run, day), `Show ${day} on a chart, with its entries and exits`, "pp-daylink");
  return b;
}

function tradesTable(run, o) {
  const wrap = el("div");
  const rep = run.report;
  if (!rep) { wrap.appendChild(el("p", "muted small", run.status !== "done" ? "The trades show when the run is done; the Log shows them as they happen." : "No trades.")); return wrap; }
  wrap.appendChild(el("p", "muted small", "Click a day to see it on a chart: the entries and exits as arrows, with the studies the rules read."));
  const t = el("table", "cfg-table pp-trades");
  const head = el("tr");
  for (const h of ["Day", "Side", "Shares", "In", "Out", "P/L", "Exit"]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  if (!rep.trades.length) { const td = el("td", "muted", "No trades: see the Log for the signals and why they weren't taken."); td.colSpan = 7; t.appendChild(el("tr")).appendChild(td); }
  for (const x of rep.trades.slice(0, 500)) {
    const tr = el("tr");
    tr.appendChild(el("td")).appendChild(dayLink(run, x.day));
    tr.append(el("td", x.side === "long" ? "up" : "down", x.side), el("td", null, String(x.qty)),
      el("td", null, `${fmtMin(x.entry_minute)} @ ${x.entry.toFixed(2)}`), el("td", null, `${fmtMin(x.exit_minute)} @ ${x.exit.toFixed(2)}`),
      el("td", x.pnl >= 0 ? "up" : "down", o.money(x.pnl)), el("td", "muted small", x.why || ""));
    t.appendChild(tr);
  }
  wrap.appendChild(t);
  if (rep.trades.length > 500) wrap.appendChild(el("p", "muted small", `The first 500 of ${rep.trades.length} trades.`));
  return wrap;
}

function logView(run) {
  const wrap = el("div");
  const row = el("div", "cfg-row");
  const sel = el("select"); sel.setAttribute("aria-label", "Which log lines");
  for (const [v, t] of LEVELS) { const x = el("option", null, t); x.value = v; sel.appendChild(x); }
  sel.value = logLevel;
  const lines = (run.log || []).filter((l) => !logLevel || l.level === logLevel || l.level === "error" || (logLevel === "warn" && l.level === "warn"));
  row.append(el("span", "muted small", "Show"), sel, el("span", "muted small", `${lines.length} line${lines.length === 1 ? "" : "s"}` + (run.status === "running" || run.status === "fetching" ? ` · ${run.status}` : "")));
  const box = el("div", "pp-log");
  box.setAttribute("role", "log");
  if (!run.log) box.appendChild(el("div", "muted", "This run was made before backtests kept a log."));
  let lastDay = null;
  for (const l of lines) {
    const line = el("div", "pp-logline " + l.level);
    if (l.day && l.day !== lastDay && logLevel !== "day") line.classList.add("first");
    lastDay = l.day;
    line.appendChild(el("span", "pp-logday")).appendChild(line.classList.contains("first") || logLevel === "day" ? dayLink(run, l.day) : el("span"));
    line.appendChild(el("span", "pp-logtext", l.text));
    box.appendChild(line);
  }
  sel.onchange = () => { logLevel = sel.value; wrap.replaceWith(logView(run)); };
  wrap.append(row, box);
  return wrap;
}
