/* Draws the expected-move view: a comparison table across the symbols, then one card per symbol with the moves,
   the event priced between expiries, the diagonal's legs and any warnings. Data: /api/expected-move. */
import { ago, expiryDate, fixed, pct, signed } from "../format.js";
import { el } from "../util.js";

const money = (x) => fixed(x);                                         // prices and strikes, without a $
const ivPct = (x) => pct(x == null ? x : x * 100, 0);                    // implied volatility comes as a fraction
export const expiryLabel = expiryDate;
// when the quotes were taken (the collector's clock), else when they were saved
const quotedAt = (it) => (it.quoted_at || it.fetched ? new Date(it.quoted_at || it.fetched * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" }) + " ET" : "");

function table(rows, cls) {
  const t = el("table", cls);
  for (const r of rows) {
    const tr = el("tr");
    r.forEach((c, i) => { const td = el(i === 0 ? "th" : "td", null, c); tr.appendChild(td); });
    t.appendChild(tr);
  }
  return t;
}

// what to say about a symbol that has no numbers yet
export function statusText(it, waiting) {
  if (it.status === "error") return it.message;
  if (it.status === "missing") return waiting ? waiting(it) : "no quotes yet";
  return "";
}

export function renderSummary(box, items, waiting) {
  box.innerHTML = "";
  const t = el("table", "em-table");
  const head = el("tr");
  for (const h of ["Stock", "Price", "Expiry", "Expected move", "%", "Range", "Event priced in", "ATM IV", "Quotes"]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  for (const it of items) {
    const tr = el("tr");
    tr.appendChild(el("th", null, it.symbol));
    if (it.status !== "ok") {
      const td = el("td", "muted", statusText(it, waiting)); td.colSpan = 8; tr.appendChild(td);
    } else {
      const m = it.moves[0], ev = it.event;
      const cells = [money(it.price), `${expiryLabel(it.expiry)} (${it.days.toFixed(1)} d)`, "±" + money(m.move), pct(m.pct),
                     `${money(m.low)} – ${money(m.high)}`, ev?.found ? `±${pct(ev.pct)} (IV ${ivPct(ev.prev_iv)} → ${ivPct(ev.iv)})` : ev ? "none" : "–",
                     ivPct(it.iv), `${quotedAt(it)}${it.warnings.length ? " ⚠" : ""}`];
      cells.forEach((c, i) => { const td = el("td", i === 2 ? "em-big" : null, c); if (i === 7 && it.warnings.length) td.title = it.warnings.join("\n"); tr.appendChild(td); });
    }
    t.appendChild(tr);
  }
  box.appendChild(t);
}

export function renderCards(box, items) {
  box.innerHTML = "";
  for (const it of items.filter((x) => x.status === "ok")) {
    const card = el("article", "em-card");
    card.dataset.symbol = it.symbol;
    card.appendChild(el("h3", null, `${it.symbol} by ${expiryLabel(it.expiry)}`));
    card.appendChild(el("p", "muted small", `Price ${money(it.price)} (${it.price_source === "last" ? "last trade" : it.price_source}), `
      + `${it.days.toFixed(1)} calendar days to the 16:00 close, quotes at ${quotedAt(it)} (${ago(it.age)}).`));
    const a = it.atm;
    const rows = [["ATM strike", money(a.strike)], ["Call / put (mid)", `${money(a.call)} / ${money(a.put)}`]];
    for (const m of it.moves) rows.push([m.name, `±${money(m.move)} (±${pct(m.pct)}) → ${money(m.low)} – ${money(m.high)}`]);
    rows.push(["Implied volatility (ATM)", ivPct(it.iv)]);
    if (it.event) {
      rows.push(["Event before this expiry", it.event.found
        ? `IV ${ivPct(it.event.prev_iv)} (${expiryLabel(it.event.prev_expiry)}) → ${ivPct(it.event.iv)}: about ±${money(it.event.move)} (±${pct(it.event.pct)}) priced for it, usually earnings`
        : `none priced in (IV ${ivPct(it.event.prev_iv)} on ${expiryLabel(it.event.prev_expiry)}, ${ivPct(it.event.iv)} here)`]);
    }
    const main = table(rows, "em-rows");
    main.rows[2].classList.add("em-key");
    card.appendChild(main);
    const dg = it.diagonal;
    if (dg) {
      card.appendChild(el("h4", null, `Diagonal legs: short ${expiryLabel(dg.short_expiry)}, long ${expiryLabel(dg.long_expiry)}`));
      const leg = (l, side) => [side, l.short_strike == null ? "–" : `${money(l.short_strike)} @ ${money(l.short)}`,
                                l.long_strike == null ? "–" : `${money(l.long_strike)} @ ${money(l.long)}`, signed(l.net)];
      const t = table([["", "Short (sell)", "Long (buy)", "Net (long − short)"], leg(dg.call, "Call"), leg(dg.put, "Put"),
                       ["Both sides", "", "", signed(dg.net)]], "em-legs");
      card.appendChild(t);
      if (dg.next_straddle != null) {
        card.appendChild(el("p", "muted small", `${expiryLabel(dg.long_expiry)} straddle ${money(dg.next_straddle)}, IV ${ivPct(dg.next_iv)}.`));
      }
    }
    if (it.warnings.length) {
      const w = el("ul", "em-warn");
      for (const x of it.warnings) w.appendChild(el("li", null, x));
      card.appendChild(w);
    }
    box.appendChild(card);
  }
}
