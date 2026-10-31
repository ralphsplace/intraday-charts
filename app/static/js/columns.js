/* The columns a watch list can show, and how each kind is written or drawn in a cell. The list of columns
   comes from the server (app/watch_fields.py, /api/watch/columns), so a new column is one entry there; a new
   kind is one renderer here.

   Kinds: text ones (price, signed, pct, count, ratio, qty, money, pnl, time, date, text, state) and graphical
   ones (range: the day's range; range52: the 52-week range; spark: the day's prices; pnlbar). A column marked
   heat can shade its cells by value; one with a bar scale draws a bar behind its number. */
import { fmtValue } from "./util.js";

export let COLUMNS = {};
export let DEFAULTS = { quote: ["symbol", "last", "change", "pct", "volume", "high", "low"] };

// the sections of the column chooser, by the server's groups
export const SECTIONS = [
  ["quote", "Price and volume"], ["day", "The day so far"], ["spark", "The day so far"], ["rvol", "The day so far"],
  ["daily", "Daily history"], ["events", "Earnings and options"], ["study", "Study values"],
  ["holding", "Holdings"], ["finviz", "FinViz"],
];
export const sectionOf = (c) => (SECTIONS.find(([g]) => c.group === g || c.group.startsWith(g + ":")) || [, "Other"])[1];

export function setColumns(r) {
  COLUMNS = Object.fromEntries((r?.columns || []).map((c) => [c.id, c]));
  if (r?.defaults) DEFAULTS = { ...DEFAULTS, ...r.defaults };
}

// the columns a kind of list can show ("quote", "holding" or "finviz"), in registry order
export const available = (kind) => Object.values(COLUMNS).filter((c) => c.lists === "all" || c.lists === kind).map((c) => c.id);

// a list's columns: its own choice (known ones it can show, Symbol always first), or the kind's default
export function columnsFor(kind, chosen) {
  const can = available(kind);
  const list = Array.isArray(chosen) ? chosen.filter((id) => can.includes(id) && id !== "symbol") : null;
  if (list && list.length) return ["symbol", ...list];
  return (DEFAULTS[kind] || DEFAULTS.quote).filter((id) => id === "symbol" || can.includes(id));
}

const sign = (x) => (x > 0 ? "+" : x < 0 ? "−" : "");
const price = (x) => (Math.abs(x) >= 1e6 ? fmtValue(x) : x.toFixed(2));        // 25.04M for big internals
const money = (x) => Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// a value's text and colour class ("up" / "down" / "" / others), for the text kinds
export function cellText(id, row) {
  const c = COLUMNS[id] || { kind: "text" }, x = row[id];
  if (c.kind === "symbol") return [row.symbol, ""];
  if (x == null || (typeof x === "number" && Number.isNaN(x))) return ["–", ""];
  const dir = x > 0 ? "up" : x < 0 ? "down" : "";
  switch (c.kind) {
    case "price": return [price(x), ""];
    case "signed": return [sign(x) + price(Math.abs(x)), dir];
    case "pct": return [sign(x) + Math.abs(x).toFixed(2) + "%", dir];
    case "count": return [fmtValue(x).replace(/\.00$/, ""), ""];
    case "ratio": return [x.toFixed(2) + "×", ""];
    case "qty": return [x.toLocaleString("en-US", { maximumFractionDigits: 4 }), x < 0 ? "down" : ""];
    case "money": return [(x < 0 ? "−" : "") + money(x), ""];
    case "pnl": return [sign(x) + money(x), dir];
    case "time": return [String(x), ""];
    case "date": {
      const d = new Date(x.date + "T12:00:00");
      const when = x.last ? `last ${-x.days} d ago` : x.days === 0 ? "today" : `in ${x.days} d`;
      return [`${DOW[d.getDay()]} ${x.date.slice(5)}${x.time ? " " + x.time : ""} (${when})`, !x.last && x.days <= 7 ? "soon" : ""];
    }
    case "state": return [String(x), "state " + stateClass(String(x))];
    default: return [String(x), ""];
  }
}

// neutral colours for states: these describe the day so far, never buy or sell
function stateClass(s) {
  if (/above|extended up|^\+/.test(s)) return "hi";
  if (/below|extended down|^−/.test(s)) return "lo";
  return "mid";
}

// a number to sort a cell by (graphical kinds sort by what they show)
export function sortValue(id, row) {
  const c = COLUMNS[id] || {}, x = row[id];
  if (c.kind === "symbol" || id === "symbol") return row.symbol;
  if (c.kind === "range") return row.high > row.low ? (row.last - row.low) / (row.high - row.low) : null;
  if (c.kind === "range52") return row.hi52 > row.lo52 ? (row.last - row.lo52) / (row.hi52 - row.lo52) : null;
  if (c.kind === "spark") return row.pct ?? null;
  if (c.kind === "date") return x ? x.days : null;
  if (x == null) return null;
  if (typeof x === "number") return x;
  const n = parseFloat(String(x).replace(/[,%×]/g, ""));
  return Number.isFinite(n) && /^[\s\d.,%×+−-]+$/.test(String(x)) ? n : String(x).toLowerCase();
}

// heat: a background deeper the further a value is from 0 (or from 1 for ratios)
export function heatStyle(id, row) {
  const c = COLUMNS[id], x = row[id];
  if (!c?.heat || x == null) return "";
  const v = c.kind === "ratio" ? x - 1 : x;
  const full = c.kind === "ratio" ? 2 : 4;                 // full colour at +4% / ratio 3×
  const a = Math.round(Math.min(1, Math.abs(v) / full) * 45);
  if (!a) return "";
  return `background: color-mix(in srgb, var(--${v >= 0 ? "bull" : "bear"}) ${a}%, transparent)`;
}

// ---------------------------------------------------------------- the graphical kinds (inline SVG)
const NS = "http://www.w3.org/2000/svg";
function svg(w, h, label) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("width", w); s.setAttribute("height", h); s.setAttribute("viewBox", `0 0 ${w} ${h}`);
  s.setAttribute("role", "img"); s.setAttribute("aria-label", label);
  return s;
}
function add(s, tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  s.appendChild(e);
  return e;
}

function rangeBar(lo, hi, last, marks, band, label) {
  const W = 110, H = 14, s = svg(W, H, label);
  if (!(hi > lo) || last == null) return null;
  const x = (v) => 4 + Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * (W - 8);
  add(s, "rect", { x: 4, y: 6, width: W - 8, height: 2, rx: 1, class: "rb-track" });
  if (band) add(s, "rect", { x: x(band[0]), y: 4, width: Math.max(2, x(band[1]) - x(band[0])), height: 6, rx: 2, class: "rb-band" });
  for (const [v, cls] of marks) if (v != null) add(s, "rect", { x: x(v) - 0.75, y: 2, width: 1.5, height: 10, class: cls });
  add(s, "circle", { cx: x(last), cy: 7, r: 3.4, class: "rb-last" });
  return s;
}

function spark(sp, label) {
  if (!sp?.p?.length) return null;
  const W = 100, H = 20, s = svg(W, H, label), p = sp.p;
  const vals = sp.base != null ? [...p, sp.base] : p;
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const X = (i) => 1 + (p.length > 1 ? i / (p.length - 1) : 0) * (W - 2), Y = (v) => 2 + (hi - v) / span * (H - 4);
  if (sp.base != null) add(s, "line", { x1: 0, x2: W, y1: Y(sp.base), y2: Y(sp.base), class: "sp-base" });
  const seg = (a, b, cls) => {
    if (b - a < 1) return;
    add(s, "polyline", { points: p.slice(a, b + 1).map((v, j) => `${X(a + j).toFixed(1)},${Y(v).toFixed(1)}`).join(" "), class: cls });
  };
  const up = sp.base == null || p[p.length - 1] >= sp.base;
  const rthEnd = p.length - 1 - (sp.post || 0);
  seg(0, Math.min(sp.pre || 0, p.length - 1), "sp-ext");
  seg(sp.pre || 0, rthEnd, up ? "sp-up" : "sp-down");
  seg(rthEnd, p.length - 1, "sp-ext");
  return s;
}

function dataBar(x, scale, text) {
  const W = 64, H = 14, s = svg(W, H, text);
  add(s, "rect", { x: 0, y: 1, width: Math.max(0, Math.min(1, x / scale)) * W, height: H - 2, rx: 2, class: "db-bar" });
  const t = add(s, "text", { x: W - 2, y: 11, "text-anchor": "end", class: "db-text" });
  t.textContent = text;
  return s;
}

function pnlBar(x, max, text) {
  const W = 80, H = 14, s = svg(W, H, text), mid = W / 2, w = Math.min(1, Math.abs(x) / (max || 1)) * (mid - 1);
  add(s, "line", { x1: mid, x2: mid, y1: 0, y2: H, class: "pb-mid" });
  add(s, "rect", { x: x >= 0 ? mid : mid - w, y: 3, width: w, height: H - 6, rx: 1.5, class: x >= 0 ? "pb-up" : "pb-down" });
  return s;
}

/* A cell for column id in row r: {node or text, cls, style, title}. ctx: {colMax: {id: largest |value|}} */
export function renderCell(id, r, ctx) {
  const c = COLUMNS[id] || { kind: "text" };
  if (c.kind === "range") {
    const node = rangeBar(Math.min(r.low, r.prev_close ?? r.low), Math.max(r.high, r.prev_close ?? r.high), r.last,
                          [[r.open, "rb-open"], [r.prev_close, "rb-pc"], [r.vwap, "rb-vwap"]], null,
                          `${r.symbol}: ${r.last} in today's range ${r.low}-${r.high}`);
    return { node, title: `Low ${r.low} · High ${r.high} · Open ${r.open ?? "–"} · Prior close ${r.prev_close ?? "–"} · VWAP ${r.vwap ?? "–"}` };
  }
  if (c.kind === "range52") {
    const node = rangeBar(r.lo52, r.hi52, r.last, [], [r.low, r.high], `${r.symbol}: ${r.last} in its 52-week range ${r.lo52}-${r.hi52}`);
    return { node, title: `52-week low ${r.lo52 ?? "–"} · high ${r.hi52 ?? "–"}` };
  }
  if (c.kind === "spark") return { node: spark(r.spark, `${r.symbol} today`), title: "Today; dotted: the prior close" };
  if (c.kind === "pnlbar") {
    const [txt] = cellText("unrealized", { ...r, unrealized: r[id] });
    return { node: r[id] == null ? null : pnlBar(r[id], ctx.colMax[id], txt), title: txt };
  }
  const [txt, cls] = cellText(id, r);
  if (c.bar && r[id] != null) {
    return { node: dataBar(r[id], c.kind === "pct" ? (ctx.colMax[id] || c.bar) : c.bar, txt), cls, style: ctx.heat ? heatStyle(id, r) : "" };
  }
  return { text: txt, cls, style: ctx.heat ? heatStyle(id, r) : "" };
}
