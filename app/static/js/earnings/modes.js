/* How the earnings chart can show the quarters. Each mode says which value of a point it draws and how to
   format and explain it; the chart, legend and toolbar are built from this list. Both modes use the
   split-adjusted closes from the server (app/earnings.py). */
export const pct = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1) + "%";
export const usd = (v) => "$" + v.toFixed(2);

export const MODES = {
  relative: {
    button: "Relative %", tip: "% change from the close the day before day 0: every quarter starts at 0%",
    value: (p) => p.pct, format: pct, zeroLine: true,
    explain: "Each line is one earnings report: the close each trading day, as % change from the close the day " +
             "before day 0, so quarters at different share prices line up.",
  },
  price: {
    button: "Price $", tip: "The close each day, adjusted for splits: each quarter at its real price level",
    value: (p) => p.price, format: usd, zeroLine: false,
    explain: "Each line is one earnings report: the close each trading day, adjusted for stock splits, so each " +
             "quarter sits at its real price level.",
  },
};
export const DEFAULT_MODE = "relative";
