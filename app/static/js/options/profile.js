/* The strike profile: gamma exposure by strike for the expiry on view, calls up (green) and puts down (red),
   with the stock's price marked. "Near" shows the strikes closest to the price, "All" every strike in the snapshot.
   Data: the chain view's "profile" (app/option_chain.py strike_profile). */
import { fmtValue, svgEl } from "../util.js";

export const NEAR = 5;                 // strikes either side of the price in "Near"

const money = (x) => (x < 0 ? "−" : x > 0 ? "+" : "") + "$" + fmtValue(Math.abs(x)).replace(/\.00$/, "");

function niceStep(x) {
  const p = 10 ** Math.floor(Math.log10(Math.max(x, 1e-9)));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).reduce((b, v) => (Math.abs(v - x) < Math.abs(b - x) ? v : b));
}

export function renderProfile(box, note, view, mode) {
  box.innerHTML = "";
  const prof = view.profile;
  if (!prof || !prof.strikes.length) {
    note.textContent = "No open interest in this snapshot yet: it arrives with the quotes (Refresh quotes).";
    return;
  }
  const price = view.price;
  let list = prof.strikes;
  if (mode !== "all") {
    const below = list.filter((x) => x.strike <= price).slice(-NEAR), above = list.filter((x) => x.strike > price).slice(0, NEAR);
    list = below.concat(above);
  }
  const W = Math.max(480, Math.round(box.clientWidth || 900)), H = 260, L = 70, R = 12, T = 22, B = 30;
  const top = Math.max(1, ...list.map((x) => x.call)), bot = Math.min(-1, ...list.map((x) => x.put));
  const span = Math.max(top, -bot), y0 = -span * 1.08, y1 = span * 1.08;
  const lo = list[0].strike, hi = list[list.length - 1].strike, gap = list.length > 1 ? (hi - lo) / (list.length - 1) : 1;
  const X = (k) => L + (k - lo + gap / 2) / (hi - lo + gap) * (W - L - R);
  const Y = (v) => T + (y1 - v) / (y1 - y0) * (H - T - B);
  const bw = Math.max(2, Math.min(24, (W - L - R) / list.length * 0.6));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "oc-svg", role: "img",
    "aria-label": `Gamma exposure by strike for ${view.expiry_label}: calls above zero, puts below` });
  const step = niceStep(span / 2.5);
  for (let v = -Math.floor(span / step) * step; v <= span; v += step) {
    svg.appendChild(svgEl("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: v === 0 ? "oc-zero" : "oc-gridline" }));
    const t = svgEl("text", { x: L - 6, y: Y(v) + 4, class: "oc-axis", "text-anchor": "end" });
    t.textContent = money(v); svg.appendChild(t);
  }
  const every = Math.max(1, Math.ceil(list.length / 14));
  list.forEach((x, i) => {
    for (const [v, cls, side, oi] of [[x.call, "oc-gcall", "call", x.call_oi], [x.put, "oc-gput", "put", x.put_oi]]) {
      if (!v) continue;
      const r = svgEl("rect", { x: X(x.strike) - bw / 2, width: bw, y: Math.min(Y(v), Y(0)), height: Math.max(1, Math.abs(Y(v) - Y(0))), class: cls });
      const tip = svgEl("title", {});
      tip.textContent = `${x.strike} ${side}s: ${money(v)} per 1% move · open interest ${oi == null ? "–" : oi.toLocaleString("en-US")}`;
      r.appendChild(tip); svg.appendChild(r);
    }
    if (i % every === 0) {
      const t = svgEl("text", { x: X(x.strike), y: H - 10, class: "oc-axis", "text-anchor": "middle" });
      t.textContent = String(x.strike); svg.appendChild(t);
    }
  });
  if (price >= lo - gap && price <= hi + gap) {
    svg.appendChild(svgEl("line", { x1: X(price), x2: X(price), y1: T, y2: H - B, class: "oc-pricel" }));
    const t = svgEl("text", { x: X(price), y: T - 6, class: "oc-pricet", "text-anchor": "middle" });
    t.textContent = `${view.symbol} ${price.toFixed(2)}`; svg.appendChild(t);
  }
  box.appendChild(svg);
  const parts = [`Net ${money(prof.net)} per 1% move`];
  if (prof.call_wall != null) parts.push(`most call gamma at ${prof.call_wall}`);
  if (prof.put_wall != null) parts.push(`most put gamma at ${prof.put_wall}`);
  if (prof.missing) parts.push(`${prof.missing} strike${prof.missing === 1 ? "" : "s"} without open interest`);
  note.textContent = parts.join(" · ") + ".";
}
