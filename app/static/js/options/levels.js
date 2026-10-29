/* "Show levels on the chart": the structure's short strikes, breakevens and loss-limit prices as horizontal-line
   drawings of the stock, so every chart of it shows them (drawings are kept per symbol in this browser). Showing
   them again replaces the earlier ones; they can be edited or removed on the chart like any line. */
import { DRAWINGS_KEY } from "../keys.js";
import { load, store, uid } from "../util.js";

const SOURCE = "option-structure";

export function levelsFor(legs, ev) {
  const out = [];
  for (const l of legs.filter((x) => x.qty < 0)) {
    out.push({ price: l.strike, label: `Short ${l.strike} ${l.right === "C" ? "call" : "put"}`, color: "#e6b450", style: "solid" });
  }
  for (const b of ev.breakevens) out.push({ price: b, label: "Breakeven", color: "#8a8f98", style: "dashed" });
  for (const p of [ev.stop?.below, ev.stop?.above]) {
    if (p != null) out.push({ price: p, label: `Loss limit ${Math.round(ev.stop.loss)}`, color: "#ef5350", style: "dashed" });
  }
  return out;
}

export function showOnChart(symbol, levels) {
  const all = load(DRAWINGS_KEY) || {};
  const kept = (all[symbol] || []).filter((d) => d.source !== SOURCE);
  all[symbol] = kept.concat(levels.map((l) => ({ id: uid(), type: "hline", width: 1, source: SOURCE, ...l })));
  store(DRAWINGS_KEY, all);
  return levels.length;
}
