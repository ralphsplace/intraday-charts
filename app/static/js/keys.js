/* Where this browser keeps things (localStorage keys). Shared by the chart page and the dashboards page. */

// each dashboard's window (charts, studies, sizes); the original dashboard (id "main") keeps the plain key
export const LAYOUT_KEY = "intraday-chart.layout.v5";     // v5: the single-chart default; earlier windows aren't carried over
export const layoutKey = (dashboardId) => (dashboardId === "main" ? LAYOUT_KEY : LAYOUT_KEY + "@" + dashboardId);

// drawings, per symbol, shared by every dashboard
export const DRAWINGS_KEY = "intraday-chart.drawings.v1";

// the earnings page's last symbol
export const EARNINGS_SYMBOL_KEY = "intraday-chart.earnings.symbol";

// the earnings page's view: "relative" or "price"
export const EARNINGS_MODE_KEY = "intraday-chart.earnings.mode";

// the earnings page's trading days around day 0: { before, after }
export const EARNINGS_DAYS_KEY = "intraday-chart.earnings.days";
