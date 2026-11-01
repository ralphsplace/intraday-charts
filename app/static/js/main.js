/* Starts the chart page: loads the catalogue and data, restores this dashboard's window, wires the modules. */
import { setColumns } from "./columns.js";
import { fillDays, fillSymbolList, refreshAll } from "./data.js";
import { expose } from "./debug.js";
import { openData } from "./dialogs/load-data.js";
import { buildGrid, showLayout } from "./grid.js";
import { isLayout } from "./layouts.js";
import { showCursor } from "./replay.js";
import { layoutKey } from "./keys.js";
import { DASH, KEY, app, defaultConfigs, normStudies, save } from "./state.js";
import { $, api, load, orElse } from "./util.js";
import { PriceTypes as PT } from "./pricetypes.js";
import * as grid from "./grid.js";
import * as modal from "./dialogs/modal.js";
import * as studiesDlg from "./dialogs/studies.js";
import * as settingsDlg from "./dialogs/settings.js";
import * as replay from "./replay.js";
import * as loadData from "./dialogs/load-data.js";
import * as saved from "./saved.js";
import * as drawTools from "./drawtools.js";

for (const m of [grid, modal, studiesDlg, settingsDlg, replay, loadData, saved, drawTools]) m.init();

expose("chart", app);        // for the browser tests and the browser console (debug.js)
expose("priceTypes", PT);

(async () => {
  const [cat, meta, st, wl, cols] = await Promise.all([api("/api/studies"), api("/api/meta"), orElse(api("/api/collector"), null, "Collector status"),
                                                       orElse(api("/api/watchlists"), null, "Watch lists"), api("/api/watch/columns")]);
  setColumns(cols);
  app.catalog = cat.studies; app.defaults = cat.default_layout; app.meta = meta;
  app.collector = st; app.saved.watchlists = wl || {}; app.listsUnknown = !wl;   // unknown: change no list
  fillSymbolList();
  const firstRun = !meta.symbols.length;
  // first visit to this dashboard in this browser: the dashboard it was copied from, or its starting layout
  const start = DASH.settings && DASH.settings.start;
  let saved = load(KEY);
  if (!saved && DASH.copied_from) saved = load(layoutKey(DASH.copied_from));
  if (!saved && start && isLayout(start.layout)) {
    saved = { layout: start.layout, configs: (start.configs || []).map((c) => ({ ...c, studies: normStudies(c.studies) })),
              prefs: { ...(start.prefs || {}) } };
    if (start.sizes) saved.prefs.sizes = { [start.layout]: start.sizes };
  }
  if (saved && Array.isArray(saved.configs)) {
    app.layout = isLayout(saved.layout) ? saved.layout : "1x1";
    app.configs = saved.configs;
    Object.assign(app.prefs, saved.prefs || {});
  } else {
    app.configs = defaultConfigs();
  }
  showLayout();
  $("fitLevels").checked = app.prefs.fitLevels; $("extShade").checked = app.prefs.extShade; $("syncCrosshair").checked = app.prefs.sync;
  buildGrid();
  save();
  openAt(new URLSearchParams(location.search));
  if (firstRun) {
    app.day = meta.calendar.last_session; app.extraDays.add(app.day); fillDays();
    openData("No market data is cached yet. Pick the symbols and the day to load from TWS. " +
             "The charts on screen are already being requested.");
  }
  await refreshAll();
  showCursor();
  await replay.restoreMode();              // Live, if this tab was in Live on the dashboard or page before
})();

// an address that opens the first chart at a symbol, day and replay time, practising in a paper account (the Paper
// page's "open on the chart"): ?symbol=QQQ&day=2026-10-16&at=630&paper=<account id>. The address is then tidied.
function openAt(q) {
  if (!q.has("symbol") && !q.has("day")) return;
  const chart = app.panels[0];
  if (!chart) return;
  const sym = (q.get("symbol") || "").toUpperCase();
  if (/^[A-Z][A-Z0-9.-]{0,11}$/.test(sym)) { chart.symbol = sym; chart.symIn.value = sym; chart.fitSymbolBox(); }
  const day = q.get("day") || "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) { app.day = day; app.extraDays.add(day); fillDays(); }
  const at = parseInt(q.get("at"), 10);
  if (at >= 0 && at <= 24 * 60) app.cursor = at;
  if (q.get("paper")) chart.paper = q.get("paper");
  save();
  history.replaceState(null, "", location.pathname);
}

