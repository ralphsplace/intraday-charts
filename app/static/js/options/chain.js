/* The expiry strip and the chain table for one expiry. Clicking a bid adds a sold leg, an ask a bought one.
   Data: /api/options/chain. */
import { fixed, pct as fmtPct } from "../format.js";
import { el, morph } from "../util.js";

const num = fixed;
const pct = (x) => fmtPct(x == null ? x : x * 100);                  // implied volatility comes as a fraction

export function renderStrip(box, view, state, pick) {
  box.innerHTML = "";
  box.appendChild(el("span", "muted", "Expiry"));
  for (const s of view.strip || []) {
    const b = el("button", "oc-chip" + (s.expiry === state.expiry ? " active" : ""));
    b.type = "button";
    b.dataset.expiry = s.expiry;
    b.appendChild(el("b", null, s.label));
    b.appendChild(el("span", "muted", ` ${s.days} d`));
    b.appendChild(el("span", null, s.move == null ? "  EM –" : `  EM ±${s.move.toFixed(2)}`));
    const tags = [];
    if (s.expiry === state.back) tags.push("back");
    if (state.legs.some((l) => l.expiry === s.expiry)) tags.push("in structure");
    if (tags.length) b.appendChild(el("span", "oc-tag", tags.join(" · ")));
    b.title = s.move == null ? "No at-the-money quotes yet" : `Expected move by ${s.label} (the at-the-money straddle), at IV ${pct(s.iv)}`;
    b.onclick = () => pick(s.expiry);
    box.appendChild(b);
  }
}

// a leg in this expiry at this strike and right: its quantity (sold < 0 < bought), or 0
const legQty = (legs, e, k, r) => legs.filter((l) => l.expiry === e && l.strike === k && l.right === r).reduce((a, l) => a + l.qty, 0);

// drawn into a fresh table and moved onto the live one (morph), so a refresh keeps the rows on screen
export function renderChain(live, view, legs, click) {
  const table = el("table");
  const head = el("thead");
  const h1 = el("tr");
  for (const [text, span] of [["Calls", 4], ["", 1], ["Puts", 4]]) { const th = el("th", "oc-side-h", text); th.colSpan = span; h1.appendChild(th); }
  const h2 = el("tr", "oc-cols");
  for (const t of ["Delta", "IV", "Bid", "Ask", "Strike", "Bid", "Ask", "IV", "Delta"]) h2.appendChild(el("th", null, t));
  head.append(h1, h2);
  const body = el("tbody");
  const price = view.price, lo = view.move != null ? price - view.move : null, hi = view.move != null ? price + view.move : null;
  let priced = false;
  for (const r of view.rows) {
    if (!priced && r.strike > price) {
      const tr = el("tr", "oc-priceline"), td = el("td");
      td.colSpan = 9;
      td.appendChild(el("span", null, `${view.symbol} ${price.toFixed(2)}`));
      tr.appendChild(td); body.appendChild(tr); priced = true;
    }
    const tr = el("tr");
    tr.dataset.strike = r.strike;
    if (lo != null && r.strike >= lo && r.strike <= hi) tr.classList.add("oc-inem");
    const cell = (text, cls) => { const td = el("td", cls, text); tr.appendChild(td); return td; };
    const quote = (q, right, side, itm) => {
      const qty = legQty(legs, view.expiry, r.strike, right);
      const mine = (side === "bid" && qty < 0) || (side === "ask" && qty > 0);
      const td = cell(num(q?.[side]), "oc-q" + (mine ? (qty < 0 ? " oc-sell" : " oc-buy") : itm));
      if (q?.[side] != null) {
        td.tabIndex = 0;
        td.title = `${side === "bid" ? "Sell" : "Buy"} 1 ${view.expiry_label} ${r.strike} ${right === "C" ? "call" : "put"}`;
        td.onclick = () => click(r.strike, right, side === "bid" ? -1 : 1);
        td.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } };
      }
    };
    const itmC = r.strike < price ? " oc-itm" : "", itmP = r.strike > price ? " oc-itm" : "";
    cell(num(r.C?.delta), "oc-n" + itmC); cell(pct(r.C?.iv), "oc-n" + itmC);
    quote(r.C, "C", "bid", itmC); quote(r.C, "C", "ask", itmC);
    const k = cell(r.strike % 1 ? r.strike.toFixed(2) : String(r.strike), "oc-strike");
    if (lo != null && view.rows.length && (nearestTo(view.rows, lo) === r.strike || nearestTo(view.rows, hi) === r.strike)) k.appendChild(el("span", "oc-emtag", "EM"));
    quote(r.P, "P", "bid", itmP); quote(r.P, "P", "ask", itmP);
    cell(pct(r.P?.iv), "oc-n" + itmP); cell(num(r.P?.delta), "oc-n" + itmP);
    body.appendChild(tr);
  }
  table.append(head, body);
  morph(live, table);
}

const nearestTo = (rows, x) => rows.reduce((b, r) => (Math.abs(r.strike - x) < Math.abs(b - x) ? r.strike : b), rows[0].strike);
