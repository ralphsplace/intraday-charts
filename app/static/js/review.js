/* The chart page's review mode (/review?run=<backtest id>&day=<day>, opened from the Backtesting page's backtest trades):
   one chart of the backtest's symbol and day at its strategy's timeframe, with the studies its rules read and its
   trades as entry and exit arrows. Studies added here (the f(x) button) stay for the next trade reviewed, so a rule
   can be refined against them; the ones the rules read are replaced by the next run's. Its window is its own in
   each browser (never a dashboard's). Data: /api/backtests/<id>/review. */
import { fillDays } from "./data.js";
import { DASH, app, normStudies } from "./state.js";
import { $, api, el } from "./util.js";

const enc = encodeURIComponent;
const key = (s) => s.type + JSON.stringify(Object.keys(s.params).sort().map((k) => [k, s.params[k]]));

export const reviewing = () => !!DASH.settings?.review;

// the review window: the run's chart, from what this browser kept (saved: { layout, configs, prefs } or null)
export async function reviewWindow(saved) {
  const q = new URLSearchParams(location.search);
  const v = await api(`/api/backtests/${enc(q.get("run") || "")}/review?day=${enc(q.get("day") || "")}`);
  const kept = saved?.configs?.[0] || {};
  const before = new Set(saved?.prefs?.reviewRule || []);
  const ruled = normStudies(v.studies);
  const mine = normStudies(kept.studies || []).filter((s) => !before.has(key(s)) && !ruled.some((r) => key(r) === key(s)));
  return {
    view: v,
    window: { layout: "1x1", configs: [{ ...kept, symbol: v.symbol, tf: v.tf, days: 1, studies: [...ruled, ...mine], link: "" }],
              prefs: { ...(saved?.prefs || {}), reviewRule: ruled.map(key) } },
  };
}

// once the chart is built: the day (the whole of it), the arrows, and a line saying what's shown
export function showReview(v) {
  app.day = v.day; app.extraDays.add(v.day); app.cursor = null;
  document.body.classList.add("review");               // one chart of one day: no layouts, no other days, no Live
  fillDays();
  const chart = app.panels[0];
  if (chart) chart.markers = v.markers;
  document.title = `Review · ${v.strategy_name} · ${v.symbol} ${v.day}`;
  const bar = el("div", "reviewbar");
  bar.append(el("b", null, `Backtest review: ${v.strategy_name}`), el("span", null, ` · ${v.symbol} · ${v.day} · ${v.tf}-minute bars · `));
  const pnl = v.trades.reduce((a, t) => a + t.pnl, 0);
  bar.appendChild(el("span", pnl >= 0 ? "up" : "down", `${v.trades.length} trade${v.trades.length === 1 ? "" : "s"}, ${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}`));
  const when = Object.entries({ "Buy if": v.when.buy, "Sell short if": v.when.short, "Close a long if": v.when.exit_long,
                                "Close a short if": v.when.exit_short }).filter(([, x]) => x);
  for (const [k, x] of when) bar.append(el("span", "muted", ` · ${k} `), el("code", null, x));
  const edit = el("a", null, "Edit rules"); edit.href = "/config?tab=rules"; edit.target = "_blank";
  bar.append(el("span", "muted", " · "), edit);
  $("grid").before(bar);
}
