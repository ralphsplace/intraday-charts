/* The window's state: charts, layout, replay day and cursor, preferences; and saving it in this browser. */
import { LAYOUT_KEY, layoutKey } from "./keys.js";
import { clone, store, uid } from "./util.js";

// the dashboard this page shows; each keeps its own window in this browser (keys.js)
export const DASH = window.DASHBOARD || { id: "main", legacy: true, settings: {} };
export const KEY = DASH.legacy ? LAYOUT_KEY : layoutKey(DASH.id);
export const LIVE_REFRESH_MS = 5000;   // the collector writes today's bars every ~5 s

export const app = { meta: null, catalog: [], defaults: [], layout: "1x1", day: null, cursor: null,
                     live: false, playing: false, panels: [], configs: [], active: null, editing: null,
                     collector: null, requested: new Set(), extraDays: new Set(), saved: { views: {}, layouts: {}, watchlists: {} },
                     prefs: { fitLevels: false, extShade: true, sync: true } };

export const spec = (type) => app.catalog.find((s) => s.type === type);

export const defaultsFor = (type) => Object.fromEntries((spec(type)?.params || []).map((p) => [p.key, p.default]));

// a study list with every setting filled in; studies this version doesn't know are dropped
export function normStudies(list) {
  return (Array.isArray(list) ? list : []).filter((s) => spec(s.type)).map((s) => ({ uid: s.uid || uid(), type: s.type, visible: s.visible !== false,
                                                                                    params: { ...defaultsFor(s.type), ...(s.params || {}) } }));
}

export const cachedSymbols = () => (app.meta?.symbols || []).map((s) => s.symbol);
export const hasBars = (sym, day) => !!(app.meta?.symbols || []).find((s) => s.symbol === sym)?.days.includes(day);

// a new window: one chart of the default symbol (QQQ), 3-minute bars, today, no studies
export const defaultSymbol = () => app.meta?.default_symbol || "QQQ";     // config.json "default_symbol"

export function defaultConfigs() {
  return [{ symbol: defaultSymbol(), tf: 3, days: 1, studies: [] }];
}
// a chart added with Layout: the default symbol, like the first chart
export function newConfig() {
  return { symbol: defaultSymbol(), tf: 3, days: 1, studies: normStudies(clone(app.defaults)) };
}

export function save() {
  app.configs = app.configs.map((c, i) => app.panels[i] ? app.panels[i].config() : c);
  store(KEY, { layout: app.layout, configs: app.configs, prefs: app.prefs });
}
