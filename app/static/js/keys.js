/* Where this browser keeps things (localStorage keys). Shared by the chart page and the dashboards page. */

// each dashboard's window (charts, studies, sizes); the original dashboard (id "main") keeps the plain key
export const LAYOUT_KEY = "intraday-charts.layout.v5";     // v5: the single-chart default; earlier windows aren't carried over
export const layoutKey = (dashboardId) => (dashboardId === "main" ? LAYOUT_KEY : LAYOUT_KEY + "@" + dashboardId);

// drawings, per symbol, shared by every dashboard
export const DRAWINGS_KEY = "intraday-charts.drawings.v1";

// the earnings page's last symbol
export const EARNINGS_SYMBOL_KEY = "intraday-charts.earnings.symbol";

// the earnings page's view: "relative" or "price"
export const EARNINGS_MODE_KEY = "intraday-charts.earnings.mode";

// the earnings page's trading days around day 0: { before, after }
export const EARNINGS_DAYS_KEY = "intraday-charts.earnings.days";

// the expected-move page's last symbols and date: { symbols, date }
export const EXPECTED_MOVE_KEY = "intraday-charts.expected-move";

// Live or Replay, kept for this tab only (sessionStorage): moving between dashboards and pages stays in Live; a new
// tab or a restarted browser starts in Replay
export const MODE_KEY = "intraday-charts.mode";

// the option-chain page's symbol, expiries, structure and evaluation settings
export const OPTIONS_KEY = "intraday-charts.options";
