/* The Paper page's Trades section: an account's trades (Replay practice and saved backtests) since its last reset,
   filtered by symbol and day, with totals, the equity after each session, a note per trade, and a link that opens
   the trade on a chart at its day and time. Data: /api/paper/accounts/<name>/trades. */
import { dollars, fmtMin } from "../format.js";
import { $, api, el, load, store } from "../util.js";
import { equityChart } from "./equity.js";

const KEY = "intraday-charts:paper-account";
const enc = encodeURIComponent;
let data = null;

export async function loadTrades(accounts, say) {
  const sel = $("ppAccount");
  const names = Object.keys(accounts).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  sel.innerHTML = "";
  for (const n of names) { const o = el("option", null, n); o.value = n; sel.appendChild(o); }
  if (!names.length) { $("ppTrades").innerHTML = ""; $("ppEquity").hidden = true; $("ppTotals").textContent = "No paper accounts yet: make one under Accounts."; return; }
  sel.value = names.includes(load(KEY)) ? load(KEY) : names[0];
  sel.onchange = () => { store(KEY, sel.value); show(say); };
  await show(say);
}

async function show(say) {
  try { data = await api(`/api/paper/accounts/${enc($("ppAccount").value)}/trades`); }
  catch (e) { say(e.message, true); return; }
  const fill = (id, values, all) => {
    const s = $(id), cur = s.value;
    s.innerHTML = "";
    for (const [v, t] of [["", all], ...values.map((x) => [x, x])]) { const o = el("option", null, t); o.value = v; s.appendChild(o); }
    s.value = values.includes(cur) ? cur : "";
    s.onchange = () => render(say);
  };
  fill("ppSymbol", [...new Set(data.trades.map((t) => t.symbol))].sort(), "All symbols");
  fill("ppDay", [...new Set(data.trades.map((t) => t.day))].sort().reverse(), "All days");
  render(say);
}

// the symbol, and where the trade came from when it's a saved backtest
function symbolCell(x) {
  const td = el("td", null, x.symbol);
  if (x.backtest) td.appendChild(el("span", "muted small", " backtest"));
  return td;
}

function render(say) {
  const sym = $("ppSymbol").value, day = $("ppDay").value;
  const rows = data.trades.filter((t) => (!sym || t.symbol === sym) && (!day || t.day === day));
  const total = rows.reduce((a, t) => a + t.pnl, 0), wins = rows.filter((t) => t.pnl > 0).length;
  $("ppTotals").textContent = `${rows.length} trade${rows.length === 1 ? "" : "s"} · ${dollars(total, { d: 2 })}` +
    (rows.length ? ` · ${Math.round((100 * wins) / rows.length)}% winners` : "") +
    ` · balance ${dollars(data.balance - data.start_cash, { d: 2 })} on $${Math.round(data.start_cash).toLocaleString("en-US")}`;
  equityChart($("ppEquity"), data.equity.map((e, i) => ({ i, value: e.equity, label: `${e.day} ${e.symbol}` })), data.start_cash);
  const t = $("ppTrades");
  t.innerHTML = "";
  const head = el("tr");
  for (const h of ["Day", "Symbol", "Side", "Shares", "In", "Out", "P/L", "Exit", "Note", ""]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  if (!rows.length) {
    const td = el("td", "muted", "No trades yet: practise on a chart in Replay (≡ menu, Paper trading), or save a backtest."); td.colSpan = 10;
    t.appendChild(el("tr")).appendChild(td);
  }
  for (const x of rows) {
    const tr = el("tr");
    tr.dataset.key = x.key;
    const note = el("input", "pp-note");
    Object.assign(note, { value: x.note, maxLength: 2000, placeholder: "Why, and what I learned" });
    note.setAttribute("aria-label", `Note for the ${x.side} trade at ${fmtMin(x.entry_minute)}`);
    note.onchange = async () => {
      try { await api(`/api/paper/accounts/${enc(data.account)}/notes`, { key: x.key, text: note.value }, "PUT"); x.note = note.value; say("Note saved."); }
      catch (e) { say(e.message, true); }
    };
    const open = el("a", "pp-open", "Open on the chart");
    open.href = `/?symbol=${enc(x.symbol)}&day=${x.day}&at=${x.entry_minute + 1}&paper=${enc(data.id)}`;   // just after the entry fills
    open.title = "The default dashboard's first chart, at this trade's day and time, practising in this account";
    tr.append(el("td", null, x.day), symbolCell(x), el("td", x.side === "long" ? "up" : "down", x.side),
              el("td", null, String(x.qty)), el("td", null, `${fmtMin(x.entry_minute)} @ ${x.entry.toFixed(2)}`),
              el("td", null, `${fmtMin(x.exit_minute)} @ ${x.exit.toFixed(2)}`), el("td", x.pnl >= 0 ? "up" : "down", dollars(x.pnl, { d: 2 })),
              el("td", "muted small", x.why || ""));
    tr.appendChild(el("td")).appendChild(note);
    tr.appendChild(el("td")).appendChild(open);
    t.appendChild(tr);
  }
}
