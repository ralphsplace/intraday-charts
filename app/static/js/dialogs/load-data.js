/* The Load data dialog: symbols and day to fetch, watchlists, and the collector's status. */
import { names, normal, symbolsOf } from "../lists.js";
import { fillDays, fillSymbolList, refreshAll, refreshData, startPolling } from "../data.js";
import { ago } from "../format.js";
import { openModal } from "../dialogs/modal.js";
import { setMode, showCursor } from "../replay.js";
import { app } from "../state.js";
import { $, api, btn, el } from "../util.js";

export function openData(note) {
  const syms = [...new Set(app.panels.map((p) => p.symbol))];
  if (!$("dataSyms").value.trim()) $("dataSyms").value = syms.join(" ");
  const cal = app.meta.calendar || {};
  if (!$("dataDay").value) $("dataDay").value = cal.last_session || "";
  $("dataDay").max = cal.live_day || "";
  $("dataNote").textContent = note || "";
  $("dataNote").hidden = !note;
  fillWatchlists();
  renderCollector();
  openModal("dataDlg");
  startPolling();
}

export function fillWatchlists() {
  const sel = $("wlSel"), cur = sel.value;
  sel.innerHTML = '<option value="">Watchlists…</option>';
  // the watch lists of symbols (FinViz and Holdings lists have no symbols of their own to fetch)
  names().filter((n) => normal(app.saved.watchlists[n]).source === "symbols")
    .forEach((n) => { const o = el("option", null, n); o.value = n; sel.appendChild(o); });
  sel.value = app.saved.watchlists[cur] ? cur : "";
  $("wlDelete").disabled = !sel.value;
}

export async function parseSymbols(text) {
  const r = await api("/api/symbols/parse", { text });
  $("dataMsg").textContent = [r.skipped.length ? `Skipped (not stocks or ETFs): ${r.skipped.slice(0, 12).join(" ")}` : "", r.note || ""]
    .filter(Boolean).join(" ");
  return r.symbols;
}

export function renderCollector() {
  const st = app.collector, box = $("collectorBox");
  box.innerHTML = "";
  const line = (cls, text) => box.appendChild(el("div", cls, text));
  if (!st || !st.running) {
    line("bad", "TWS collector: not running" + (st && st.age != null ? ` (last seen ${ago(st.age)})` : "") + ".");
    line("muted", "Requests are saved and run when it starts. See the user guide: Connecting to TWS.");
    if (st && st.waiting_requests) line("muted", `${st.waiting_requests} request${st.waiting_requests > 1 ? "s" : ""} waiting.`);
    return;
  }
  if (!st.connected) { line("bad", "TWS collector: running, but can't reach TWS."); line("muted", st.message || ""); return; }
  line("good", `TWS collector: connected to ${st.host}:${st.port}` + (st.market_open ? "" : " (market closed, streaming paused)"));
  const live = el("div", "chips");
  live.appendChild(el("span", "muted", "Live symbols: "));
  if (!(st.live || []).length) live.appendChild(el("span", "muted", "none"));
  for (const sym of st.live || []) {
    const c = el("span", "chip", sym);
    const x = btn("\u00d7", async () => {
      await api("/api/live/stop", { symbols: [sym] });
      [...app.requested].filter((k) => k === `${sym}|live`).forEach((k) => app.requested.delete(k));
      setTimeout(refreshData, 1500);
    }, `Stop streaming ${sym}`);
    x.title = `Stop streaming ${sym}`;
    c.appendChild(x); live.appendChild(c);
  }
  box.appendChild(live);
  if (st.current) line("", `Fetching ${st.current.symbol} ${st.current.day || "daily history"}…`);
  if (st.queue_len) {
    const q = (st.queue || []).slice(0, 8).map((t) => `${t.symbol} ${t.day || "daily"}`).join(", ");
    line("muted", `${st.queue_len} fetch${st.queue_len > 1 ? "es" : ""} waiting: ${q}${st.queue_len > 8 ? ", …" : ""}`);
  } else if (!st.current) line("muted", "Queue empty.");
  const bad = Object.keys(st.bad_symbols || {});
  if (bad.length) line("bad", "Unknown at IBKR: " + bad.join(", "));
  const recent = (st.results || []).slice(-6).reverse();
  if (recent.length) {
    line("muted", "Recent: " + recent.map((r) => `${r.symbol} ${r.day || "daily"} ${r.bars ? "✓" : "(no bars)"}`).join(", "));
  }
  const errs = (st.errors || []).slice(-3).reverse();
  errs.forEach((e) => line("bad small", `TWS ${e.code}${e.symbol ? " " + e.symbol : ""}: ${e.message}`));
}

export function init() {
  $("openData").onclick = () => openData();
  $("wlSel").onchange = () => {
    const list = app.saved.watchlists[$("wlSel").value];
    if (list) $("dataSyms").value = symbolsOf(list).join(" ");
    $("wlDelete").disabled = !list;
  };
  $("wlSave").onclick = async () => {
    const name = ($("wlName").value || "").trim() || $("wlSel").value;
    if (!name) { $("wlName").focus(); $("dataMsg").textContent = "Type a name for the watchlist first."; return; }
    const syms = await parseSymbols($("dataSyms").value);
    if (!syms.length) { $("dataMsg").textContent = "No symbols to save."; return; }
    try {
      app.saved.watchlists = await api(`/api/saved/watchlists/${encodeURIComponent(name)}`, syms, "PUT");
      $("wlName").value = ""; fillWatchlists(); $("wlSel").value = name; $("wlDelete").disabled = false;
      fillSymbolList();
      $("dataMsg").textContent = `Saved watchlist "${name}" (${syms.length} symbols).`;
    } catch (e) { $("dataMsg").textContent = e.message; }
  };
  $("wlDelete").onclick = async () => {
    const name = $("wlSel").value;
    if (!name) return;
    app.saved.watchlists = await api(`/api/saved/watchlists/${encodeURIComponent(name)}`, null, "DELETE");
    fillWatchlists(); fillSymbolList();
    $("dataMsg").textContent = `Deleted watchlist "${name}".`;
  };
  $("wlFile").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const syms = await parseSymbols(await f.text());
    $("dataSyms").value = syms.join(" ");
    if (!$("wlName").value) $("wlName").value = f.name.replace(/\.[^.]+$/, "").slice(0, 60);
    e.target.value = "";
  };
  $("dataFetch").onclick = async () => {
    const syms = await parseSymbols($("dataSyms").value);
    const day = $("dataDay").value;
    if (!syms.length) { $("dataMsg").textContent = "Type at least one symbol."; return; }
    if (!day) { $("dataMsg").textContent = "Pick a date."; return; }
    try {
      const r = await api("/api/fetch", { symbols: syms, day, live: false });
      syms.forEach((s) => app.requested.add(`${s}|${r.day}`));
      $("dataMsg").textContent = `Requested ${syms.length} symbol${syms.length > 1 ? "s" : ""} for ${r.day}` +
        (r.day !== day ? ` (${day} wasn't a trading day)` : "") + ", plus the 5 trading days before it.";
      if (app.live) await setMode(false);
      app.extraDays.add(r.day);
      app.day = r.day; app.cursor = null;
      app.panels.forEach((p) => { p.fitted = false; p.lastCursor = null; });
      fillDays(); showCursor();
      await refreshAll();
      startPolling();
    } catch (e) { $("dataMsg").textContent = e.message; }
  };

}
