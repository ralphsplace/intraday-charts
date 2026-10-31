/* The columns a watch list can show: one registry, so a new column is one entry here. Each column says what it
   shows and how: its row field, its kind (how the value is written and coloured), and which lists have it
   ("quote": every list, from the cached bars; "holding": the Holdings list, from the account's positions).
   A list shows its own choice of columns, or its kind's default set. */
import { fmtValue } from "./util.js";

export const COLUMNS = {
  symbol:         { label: "Symbol", kind: "symbol", has: "quote" },
  last:           { label: "Last", kind: "price", has: "quote" },
  change:         { label: "Chg", kind: "signed", has: "quote", tip: "Change from the prior day's close" },
  pct:            { label: "Chg %", kind: "pct", has: "quote", tip: "% change from the prior day's close" },
  volume:         { label: "Volume", kind: "count", has: "quote", tip: "Regular hours (premarket before 09:30)" },
  high:           { label: "High", kind: "price", has: "quote" },
  low:            { label: "Low", kind: "price", has: "quote" },
  qty:            { label: "Qty", kind: "qty", has: "holding", tip: "Shares held, over all accounts (negative: short)" },
  avg_cost:       { label: "Avg cost", kind: "price", has: "holding", tip: "Average cost per share, as IBKR reports it" },
  cost:           { label: "Cost basis", kind: "money", has: "holding", tip: "Quantity × average cost" },
  market_value:   { label: "Mkt value", kind: "money", has: "holding", tip: "Quantity × the price on screen" },
  unrealized:     { label: "Unrl P/L", kind: "pnl", has: "holding", tip: "Market value − cost basis" },
  unrealized_pct: { label: "Unrl P/L %", kind: "pct", has: "holding", tip: "Unrealized P/L as a % of the cost basis" },
  day_pnl:        { label: "Day P/L", kind: "pnl", has: "holding", tip: "Quantity × change from the prior close" },
};

export const DEFAULTS = {
  quote: ["symbol", "last", "change", "pct", "volume", "high", "low"],
  holding: ["symbol", "qty", "avg_cost", "last", "market_value", "unrealized", "unrealized_pct", "day_pnl", "pct"],
};

// the columns a kind of list can show, in registry order
export const available = (kind) => Object.keys(COLUMNS).filter((id) => COLUMNS[id].has === "quote" || COLUMNS[id].has === kind);

// a list's columns: its own choice (known ones it can show, Symbol always first), or the kind's default
export function columnsFor(kind, chosen) {
  const can = available(kind);
  const list = Array.isArray(chosen) ? chosen.filter((id) => can.includes(id) && id !== "symbol") : null;
  return list && list.length ? ["symbol", ...list] : DEFAULTS[kind] || DEFAULTS.quote;
}

const sign = (x) => (x > 0 ? "+" : x < 0 ? "−" : "");
const price = (x) => (Math.abs(x) >= 1e6 ? fmtValue(x) : x.toFixed(2));        // 25.04M for big internals
const money = (x) => Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// the text of a value and its colour class ("up" / "down" / "")
export function cellText(id, row) {
  const c = COLUMNS[id], x = row[id];
  if (c.kind === "symbol") return [row.symbol, ""];
  if (x == null || Number.isNaN(x)) return ["–", ""];
  const dir = x > 0 ? "up" : x < 0 ? "down" : "";
  switch (c.kind) {
    case "price": return [price(x), ""];
    case "signed": return [sign(x) + price(Math.abs(x)), dir];
    case "pct": return [sign(x) + Math.abs(x).toFixed(2) + "%", dir];
    case "count": return [fmtValue(x).replace(/\.00$/, ""), ""];
    case "qty": return [x.toLocaleString("en-US", { maximumFractionDigits: 4 }), x < 0 ? "down" : ""];
    case "money": return [(x < 0 ? "−" : "") + money(x), ""];
    case "pnl": return [sign(x) + money(x), dir];
    default: return [String(x), ""];
  }
}
