/* The evaluation: key numbers, the risk graph (profit/loss against the stock's price, now and at the chosen time,
   over the expected move) and the profit/loss grid by price and time. Data: /api/options/evaluate. */
import { dollars, signed } from "../format.js";
import { el, svgEl } from "../util.js";

export const money = (x) => dollars(x);

export function renderStats(box, ev) {
  box.innerHTML = "";
  const mp = ev.max_profit, ml = ev.max_loss;
  const tiles = [
    ["Max profit", mp.unlimited ? "Unlimited (calls)" : mp.value <= 0 ? `none (best ${money(mp.value)})` : `${money(mp.value)} at ${mp.price.toFixed(2)}`],
    ["Max loss", ml.unlimited ? "Unlimited (calls)" : ml.value >= 0 ? `none (worst ${money(ml.value)})` : money(ml.value)],
    ["Breakevens", ev.breakevens.length ? ev.breakevens.map((x) => x.toFixed(2)).join(" / ") : "none"],
    ["Chance of profit", ev.chance == null ? "–" : `≈ ${Math.round(ev.chance)}%`],
    ["Delta (shares)", signed(ev.greeks.delta, 1)],
    ["Gamma", signed(ev.greeks.gamma, 2)],
    ["Theta / day", money(ev.greeks.theta)],
    ["Vega / IV pt", money(ev.greeks.vega)],
  ];
  for (const [label, value] of tiles) {
    const d = el("div", "oc-stat");
    d.append(el("div", "muted", label), el("div", "oc-statv", value));
    box.appendChild(d);
  }
}

// the risk graph, drawn as SVG: x = stock price, y = profit/loss in $ for 1 structure
export function renderGraph(box, ev, price, move) {
  box.innerHTML = "";
  // as wide as its panel (text keeps its size), a fixed height
  const W = Math.max(480, Math.round(box.clientWidth || 660)), H = 300, L = 60, R = 10, T = 18, B = 26;
  const xs = ev.graph.prices, a = ev.graph.at, n = ev.graph.now;
  const lo = Math.min(...a, ...n, 0), hi = Math.max(...a, ...n, 0), pad = (hi - lo) * 0.08 || 1;
  const y0 = lo - pad, y1 = hi + pad;
  const X = (p) => L + (p - xs[0]) / (xs[xs.length - 1] - xs[0]) * (W - L - R);
  const Y = (v) => T + (y1 - v) / (y1 - y0) * (H - T - B);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "oc-svg", role: "img",
    "aria-label": `Profit and loss against the stock's price, now and at ${ev.at_label}` });
  if (move != null) {
    const x0 = Math.max(X(price - move), L), x1 = Math.min(X(price + move), W - R);
    svg.appendChild(svgEl("rect", { x: x0, y: T, width: Math.max(0, x1 - x0), height: H - T - B, class: "oc-emband" }));
  }
  const step = niceStep((y1 - y0) / 5);
  for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) {
    svg.appendChild(svgEl("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: v === 0 ? "oc-zero" : "oc-gridline" }));
    const t = svgEl("text", { x: L - 6, y: Y(v) + 4, class: "oc-axis", "text-anchor": "end" });
    t.textContent = money(v); svg.appendChild(t);
  }
  const xstep = niceStep((xs[xs.length - 1] - xs[0]) / 6);
  for (let p = Math.ceil(xs[0] / xstep) * xstep; p <= xs[xs.length - 1]; p += xstep) {
    const t = svgEl("text", { x: X(p), y: H - 8, class: "oc-axis", "text-anchor": "middle" });
    t.textContent = +p.toFixed(2); svg.appendChild(t);
  }
  svg.appendChild(svgEl("line", { x1: X(price), x2: X(price), y1: T, y2: H - B, class: "oc-pricel" }));
  const label = svgEl("text", { x: X(price), y: T - 5, class: "oc-pricet", "text-anchor": "middle" });
  label.textContent = price.toFixed(2); svg.appendChild(label);
  const line = (vals, cls) => svgEl("polyline", { points: xs.map((p, i) => `${X(p).toFixed(1)},${Y(vals[i]).toFixed(1)}`).join(" "), class: cls });
  svg.appendChild(line(n, "oc-now"));
  svg.appendChild(line(a, "oc-at"));
  for (const b of ev.breakevens) {
    if (b < xs[0] || b > xs[xs.length - 1]) continue;
    svg.appendChild(svgEl("circle", { cx: X(b), cy: Y(0), r: 4, class: "oc-be" }));
    const t = svgEl("text", { x: X(b), y: Y(0) + 17, class: "oc-axis oc-bet", "text-anchor": "middle" });
    t.textContent = b.toFixed(2); svg.appendChild(t);
  }
  // hover: price and both values
  const cross = svgEl("line", { y1: T, y2: H - B, class: "oc-cross", visibility: "hidden" });
  const read = svgEl("text", { y: T + 12, class: "oc-read", visibility: "hidden" });
  svg.append(cross, read);
  svg.onmousemove = (e) => {
    const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
    if (x < L || x > W - R) { cross.setAttribute("visibility", "hidden"); read.setAttribute("visibility", "hidden"); return; }
    const i = Math.round((x - L) / (W - L - R) * (xs.length - 1));
    cross.setAttribute("x1", X(xs[i])); cross.setAttribute("x2", X(xs[i]));
    read.textContent = `${xs[i].toFixed(2)}: ${money(a[i])} at ${ev.at_label.split(" (")[0]}, ${money(n[i])} now`;
    read.setAttribute("x", Math.min(X(xs[i]) + 6, W - 300));
    cross.setAttribute("visibility", "visible"); read.setAttribute("visibility", "visible");
  };
  svg.onmouseleave = () => { cross.setAttribute("visibility", "hidden"); read.setAttribute("visibility", "hidden"); };
  box.appendChild(svg);
}

function niceStep(x) {
  const p = 10 ** Math.floor(Math.log10(Math.max(x, 1e-9)));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).reduce((b, v) => (Math.abs(v - x) < Math.abs(b - x) ? v : b));
}

export function renderGrid(table, ev, price, legs) {
  table.innerHTML = "";
  const g = ev.grid;
  const h = el("tr");
  h.appendChild(el("th", null, "Stock"));
  for (const t of g.times) h.appendChild(el("th", null, t.split(" (")[0]));
  table.appendChild(h);
  const top = Math.max(1, ...g.values.flat().map(Math.abs));
  const shorts = legs.filter((l) => l.qty < 0).map((l) => l.strike);
  g.prices.forEach((p, i) => {
    const tr = el("tr");
    const th = el("th", null, p.toFixed(2));
    if (Math.abs(p - price) < 1e-6) { tr.classList.add("oc-nowrow"); th.appendChild(el("span", "oc-gtag", "now")); }
    else if (shorts.some((k) => Math.abs(k - p) < (g.prices[0] - g.prices[1]) / 2)) th.appendChild(el("span", "oc-gtag", "near a short strike"));
    tr.appendChild(th);
    for (const v of g.values[i]) {
      const td = el("td", "oc-n", money(v));
      const s = (0.10 + 0.45 * Math.min(Math.abs(v) / top, 1)).toFixed(2);
      td.style.background = v >= 0 ? `rgba(43,179,154,${s})` : `rgba(239,83,80,${s})`;
      tr.appendChild(td);
    }
    table.appendChild(tr);
  });
}

export function stopText(ev) {
  const s = ev.stop;
  if (!s) return "Set a loss limit to see where it's reached in stock prices (the levels to watch on the chart).";
  const at = ev.at_label.split(" (")[0];
  const parts = [s.below != null ? s.below.toFixed(2) : null, s.above != null ? s.above.toFixed(2) : null].filter(Boolean);
  return parts.length ? `A ${money(s.loss)} loss at ${at} is reached at ${parts.join(" or ")}.`
                      : `The structure doesn't lose ${money(s.loss).replace("−", "")} at ${at} within the range shown.`;
}
