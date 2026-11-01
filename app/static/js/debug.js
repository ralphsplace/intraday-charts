/* What the browser tests and the browser console can look at: one object, window.__intraday, holding each page's
   state under a name (chart, priceTypes, options, earnings, expectedMove). Nothing in the app reads it. */
export function expose(name, value) {
  window.__intraday = window.__intraday || {};
  window.__intraday[name] = value;
}
