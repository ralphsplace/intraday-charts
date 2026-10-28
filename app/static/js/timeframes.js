/* The candle durations a chart offers (1m ... 15m, 1d, 1w, 1M) and the ranges each shows: days for intraday
   candles, months or years for daily, weekly and monthly ones. The list comes from the server (/api/meta,
   app/timeframes.py), so the page and the server always agree. */
import { app } from "./state.js";

const all = () => app.meta?.timeframes || { list: [], days: [], spans: [] };

export const timeframeList = () => all().list;
export const findTf = (tf) => all().list.find((t) => String(t.id) === String(tf));
export const isPeriod = (tf) => !!findTf(tf)?.period;
export const tfLabel = (tf) => findTf(tf)?.label || `${tf}m`;
// a menu value back to an id: minutes are numbers, periods keep their name ("1d")
export const parseTf = (v) => (/^\d+$/.test(String(v)) ? +v : v);
export const defaultSpan = (tf) => findTf(tf)?.span || 6;
// the range menu for a duration: [value, label] pairs
export const rangesFor = (tf) => (isPeriod(tf) ? all().spans : all().days);
export const rangeLabel = (tf, v) => (rangesFor(tf).find(([n]) => n === v) || [v, String(v)])[1];
