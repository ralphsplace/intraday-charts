/* Bars from TWS: the Day list, requests to the collector, what a waiting chart says, polling, symbol suggestions. */
import { renderCollector } from "./dialogs/load-data.js";
import { toast } from "./notify.js";
import { app, cachedSymbols, hasBars } from "./state.js";
import { $, api, el, inUse } from "./util.js";

// the Day list: days cached for any chart's symbol, plus days asked for that are still being fetched
export function fillDays() {
  const days = new Set(app.extraDays);
  for (const p of app.panels) (app.meta.symbols.find((s) => s.symbol === p.symbol)?.days || []).forEach((d) => days.add(d));
  const cal = app.meta.calendar || {};
  if (app.live && cal.live_day) days.add(cal.live_day);
  const list = [...days].sort().reverse();
  const sel = $("day");
  const cur = app.day;
  if (app.live) app.day = cal.live_day || list[0];
  else app.day = list.includes(cur) ? cur : (list[0] || cal.last_session);
  if (inUse(sel)) return app.day !== cur;          // open: the menu is rebuilt on the next refresh
  sel.innerHTML = "";
  list.forEach((d) => {
    const cached = app.live || app.panels.some((p) => hasBars(p.symbol, d));
    const o = el("option", null, d + (cached ? "" : " (loading)")); o.value = d; sel.appendChild(o);
  });
  if (app.day && !list.includes(app.day)) { const o = el("option", null, app.day); o.value = app.day; sel.appendChild(o); }
  sel.value = app.day;
  return app.day !== cur;
}

// ================================================================ data from TWS: requests and progress
export function requestData(symbols, day) {
  const live = app.live && !day;
  const d = live ? null : (day || app.day);
  const want = symbols.filter((s) => !app.requested.has(`${s}|${live ? "live" : d}`));
  if (!want.length) return Promise.resolve(null);
  want.forEach((s) => app.requested.add(`${s}|${live ? "live" : d}`));
  startPolling();
  return api("/api/fetch", { symbols: want, day: d, live }).catch((e) => {
    want.forEach((s) => app.requested.delete(`${s}|${live ? "live" : d}`));
    toast("Couldn't request data: " + e.message, true);
  });
}

export function ago(secs) {
  if (secs == null) return "never";
  if (secs < 90) return Math.round(secs) + " s ago";
  if (secs < 5400) return Math.round(secs / 60) + " min ago";
  return Math.round(secs / 3600) + " h ago";
}

// what a chart waiting for bars should say, from the collector's last status report
export function describeWait(sym, day) {
  const st = app.collector;
  if ((app.meta?.recorded || []).includes(sym)) {        // no history at IBKR: only what the collector has recorded
    const rec = st?.running && (st.recording || []).includes(sym);
    const why = st?.running && (st.not_recording || {})[sym];   // e.g. no market data permission for the indicator
    return `No ${sym} bars for ${day}. IBKR sends ${sym} only as live quotes, so the TWS collector records it ` +
           `during regular hours (09:30–16:00) and history starts when recording starts. ` +
           (rec ? "Recording now." : why ? `The collector can't record it: ${why}.` :
            st?.running ? "The collector isn't recording it at the moment." :
                  "The collector isn't running (user guide: Connecting to TWS).");
  }
  if (!st) return `No ${sym} bars for ${day} yet. Asking the TWS collector…`;
  if (!st.running) {
    return `No ${sym} bars for ${day} yet. The request is saved and runs when the TWS collector starts ` +
           `(user guide: Connecting to TWS). Collector last seen: ${ago(st.age)}.`;
  }
  if (!st.connected) return `Waiting for TWS. ${st.message || ""}`;
  if ((st.bad_symbols || {})[sym]) return `IBKR doesn't know ${sym}. Check the symbol.`;
  if (st.current && st.current.symbol === sym && st.current.day === day) return `Fetching ${sym} ${day} from TWS…`;
  const pos = (st.queue || []).findIndex((q) => q.symbol === sym && q.day === day);
  if (pos >= 0) return `Waiting for TWS: ${sym} ${day} is number ${pos + 1} of ${st.queue_len} in the queue.`;
  const done = (st.results || []).filter((r) => r.symbol === sym && r.day === day && r.kind === "day").pop();
  if (done && !done.bars) {
    const err = (st.errors || []).filter((e) => !e.symbol || e.symbol === sym).pop();
    return `TWS returned no ${sym} bars for ${day} (a holiday, or no market-data permission for it).` +
           (err ? ` TWS said: ${err.message}` : "");
  }
  if (app.live && day === app.meta.calendar?.live_day) {
    if (!st.market_open) return `No ${sym} bars for ${day}. The market is closed; streaming starts at 04:00 ET.`;
    return (st.streaming || []).includes(sym) ? `Waiting for the first ${sym} bars from TWS…` : `Starting the ${sym} stream…`;
  }
  if (st.waiting_requests) return `Sent to the TWS collector…`;
  return `No ${sym} bars for ${day}.`;
}

let pollTimer = null;
export function startPolling() { if (!pollTimer) pollTimer = setTimeout(poll, 1200); }
export async function poll() {
  pollTimer = null;
  await refreshData();
  const busy = app.panels.some((p) => p.waiting) || !$("dataDlg").hidden ||
               (app.collector && (app.collector.queue_len || app.collector.waiting_requests) && app.extraDays.size);
  if (busy) pollTimer = setTimeout(poll, 3000);
}

// re-read what is cached and what the collector is doing; refresh charts whose bars just arrived
export async function refreshData() {
  const [meta, st] = await Promise.all([api("/api/meta").catch(() => null), api("/api/collector").catch(() => null)]);
  if (meta) { app.meta = meta; fillSymbolList(); }
  if (st) app.collector = st;
  for (const d of [...app.extraDays]) if (app.panels.every((p) => hasBars(p.symbol, d))) app.extraDays.delete(d);
  if (meta && !app.live) fillDays();
  for (const p of app.panels) {
    if (p.waiting && hasBars(p.symbol, app.day)) p.refresh();
    else p.showWaiting();
  }
  if (!$("dataDlg").hidden) renderCollector();
}

export function fillSymbolList() {
  const list = $("symList"), have = new Set();
  list.innerHTML = "";
  const add = (sym, note) => {
    if (have.has(sym)) return;
    have.add(sym);
    const o = el("option"); o.value = sym; if (note) o.label = note; list.appendChild(o);
  };
  cachedSymbols().forEach((s) => add(s, "cached"));
  Object.entries(app.saved.watchlists || {}).forEach(([n, syms]) => (syms || []).forEach((s) => add(s, n)));
}

export function refreshAll() { return Promise.all(app.cells.map((p) => p.refresh())); }
