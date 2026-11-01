/* Starts the chart page: loads the catalogue and data, restores this dashboard's window, wires the modules. */
import { setColumns } from "./columns.js";
import { fillDays, fillSymbolList, refreshAll } from "./data.js";
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

window.__chartApp = app;   // for debugging from the browser console (and the browser tests)
window.__priceTypes = PT;

(async () => {
  const [cat, meta, st, wl, cols] = await Promise.all([api("/api/studies"), api("/api/meta"), orElse(api("/api/collector"), null, "Collector status"),
                                                       orElse(api("/api/saved/watchlists"), null, "Watch lists"), api("/api/watch/columns")]);
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
  if (firstRun) {
    app.day = meta.calendar.last_session; app.extraDays.add(app.day); fillDays();
    openData("No market data is cached yet. Pick the symbols and the day to load from TWS. " +
             "The charts on screen are already being requested.");
  }
  await refreshAll();
  showCursor();
  await replay.restoreMode();              // Live, if this tab was in Live on the dashboard or page before
})();
