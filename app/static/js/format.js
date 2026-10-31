/* Numbers and times as text, the same way on every page. One job: no DOM, no state.
   A missing value (null or undefined) is shown as a dash wherever a value is expected. */
export const DASH = "–";
const missing = (x) => x == null || Number.isNaN(x);

// "+", "−" (a real minus sign) or "" for zero
export const sign = (x) => (x > 0 ? "+" : x < 0 ? "−" : "");

// minutes after midnight as 09:30
export const fmtMin = (m) => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");

// large values (e.g. NYSE up - down volume) as 25.04M / 1.20B; anything else with 2 decimals
export function fmtValue(v) {
  const a = Math.abs(v);
  return a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v.toFixed(2);
}

// a price: 691.23, or 25.04M for the big internals
export const price = (x) => (missing(x) ? DASH : Math.abs(x) >= 1e6 ? fmtValue(x) : x.toFixed(2));

// a number with d decimals: 0.45
export const fixed = (x, d = 2) => (missing(x) ? DASH : x.toFixed(d));

// a number with d decimals and its sign: +1.25, −0.40, 0.00
export const signed = (x, d = 2) => (missing(x) ? DASH : sign(x) + Math.abs(x).toFixed(d));

// a percentage already in percent: 1.5%; signedPct puts + or − in front
export const pct = (x, d = 1) => (missing(x) ? DASH : x.toFixed(d) + "%");
export const signedPct = (x, d = 1) => (missing(x) ? DASH : sign(x) + Math.abs(x).toFixed(d) + "%");

// the size of an amount with thousands separators and d decimals, without its sign: 12,345.60
export const amount = (x, d = 2) => Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// dollars with their sign, whole by default: +$1,250, −$80; compact: +$1.2M
export function dollars(x, { d = 0, compact = false } = {}) {
  if (missing(x)) return DASH;
  const size = compact ? fmtValue(Math.abs(x)).replace(/\.00$/, "") : amount(x, d);
  return sign(compact ? x : Number(x.toFixed(d))) + "$" + size;          // never "−$0"
}

// an expiry or other date given as YYYYMMDD: Fri, Oct 30
export const expiryDate = (e) => (!e ? "" : new Date(`${e.slice(0, 4)}-${e.slice(4, 6)}-${e.slice(6)}T12:00:00`)
  .toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }));

// how long ago, from seconds: 45 s ago, 12 min ago, 3 h ago
export function ago(secs) {
  if (missing(secs)) return "never";
  if (secs < 90) return Math.round(secs) + " s ago";
  if (secs < 5400) return Math.round(secs / 60) + " min ago";
  return Math.round(secs / 3600) + " h ago";
}
