/* The structure's legs: side, quantity, expiry, strike, mid price, delta and theta, with the net debit or credit.
   Legs are {qty (+ bought, - sold), expiry (YYYYMMDD), strike, right ("C"|"P")}; prices come from the evaluation. */
import { btn, el } from "../util.js";
import { num } from "./chain.js";

export const sameContract = (a, b) => a.expiry === b.expiry && a.strike === b.strike && a.right === b.right;

// add qty of a contract to the legs (merging with a leg of the same contract; a leg at 0 goes away)
export function addLeg(legs, leg) {
  const out = legs.map((l) => ({ ...l }));
  const same = out.find((l) => sameContract(l, leg));
  if (same) same.qty += leg.qty; else out.push({ ...leg });
  return out.filter((l) => l.qty !== 0).sort((a, b) => a.expiry.localeCompare(b.expiry) || a.right.localeCompare(b.right) || a.strike - b.strike);
}

const fmtDate = (e) => new Date(`${e.slice(0, 4)}-${e.slice(4, 6)}-${e.slice(6)}T12:00:00`)
  .toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
const signed = (x, d = 2) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d));

export function renderLegs(box, legs, ev, change) {
  box.innerHTML = "";
  if (!legs.length) {
    box.appendChild(el("p", "muted oc-pad", "No legs yet: click a bid or an ask in the chain, or pick a template and press Fill from expected move."));
    return;
  }
  const priced = ev?.status === "ok" ? ev.legs : [];
  const t = el("table", "oc-legs");
  const h = el("tr");
  for (const x of ["Leg", "Qty", "Expiry", "Strike", "Mid", "Delta", "Theta/day", ""]) h.appendChild(el("th", null, x));
  t.appendChild(h);
  legs.forEach((l, i) => {
    const p = priced.find((x) => sameContract(x, l));
    const tr = el("tr");
    tr.dataset.leg = `${l.qty > 0 ? "buy" : "sell"} ${l.expiry} ${l.strike} ${l.right}`;
    const side = el("td");
    const tag = btn(l.qty > 0 ? "Buy" : "Sell", () => change(legs.map((x, j) => (j === i ? { ...x, qty: -x.qty } : x))),
                    `Switch to ${l.qty > 0 ? "sell" : "buy"}`, "oc-sidebtn " + (l.qty > 0 ? "oc-buytag" : "oc-selltag"));
    side.append(tag, document.createTextNode(l.right === "C" ? " call" : " put"));
    const qtd = el("td"), q = el("input", "oc-qty");
    q.type = "number"; q.min = "1"; q.max = "50"; q.value = Math.abs(l.qty);
    q.setAttribute("aria-label", "Contracts");
    q.onchange = () => { const n = Math.max(1, Math.min(50, Math.round(+q.value) || 1)); change(legs.map((x, j) => (j === i ? { ...x, qty: Math.sign(x.qty) * n } : x))); };
    qtd.appendChild(q);
    tr.append(side, qtd, el("td", null, fmtDate(l.expiry)), el("td", "oc-b", String(l.strike)),
              el("td", "oc-n", num(p?.price)), el("td", "oc-n", p ? signed(p.delta * l.qty) : "–"),
              el("td", "oc-n", p ? signed(p.theta * l.qty * 100) : "–"));
    const rm = el("td");
    rm.appendChild(btn("×", () => change(legs.filter((_, j) => j !== i)), "Remove leg", "oc-x"));
    tr.appendChild(rm);
    t.appendChild(tr);
  });
  if (ev?.status === "ok") {
    const tr = el("tr", "oc-total");
    const td = el("td", null, `Net ${ev.kind}, 1 structure`); td.colSpan = 4;
    tr.append(td, el("td", "oc-n", num(Math.abs(ev.net))), el("td", "oc-n", signed(ev.greeks.delta / 100)),
              el("td", "oc-n", signed(ev.greeks.theta)), el("td", "muted", `$${Math.abs(ev.cost).toFixed(0)}`));
    t.appendChild(tr);
  }
  box.appendChild(t);
}
