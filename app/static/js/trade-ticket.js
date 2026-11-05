/* The trade panel's order form (trade-panel.js): order type, shares, price or trailing distance (in dollars, or as
   a multiple of the ATR on the followed chart's bars), and an optional
   stop and target, then Buy or Sell. It only builds the action (app/backtesting/orders.py's "order" or "bracket"); the
   panel sends it. The stop and target are distances from the last price, so one form serves both sides. Orders at a
   study line are placed from a chart's own ticket (paper-practice.js), where the chart's studies are. */
import { btn, el } from "./util.js";

const TYPES = [["market", "Market"], ["limit", "Limit"], ["stop", "Stop"], ["trail", "Trailing stop"], ["trail_atr", "Trail × ATR"]];

// tfOf(): the minutes of the bars an ATR trailing stop's ATR is read on (the followed chart's)
export function tradeTicket(onAction, tfOf = () => 1) {
  const form = el("form", "tpform");
  form.autocomplete = "off";
  const field = (label, input, cls) => {
    const l = el("label", cls || null, label);
    l.appendChild(input);
    form.appendChild(l);
    return input;
  };
  const num = (step, min) => { const i = el("input"); i.type = "number"; i.step = step; if (min != null) i.min = min; return i; };
  const type = field("Order", el("select"), "tptype");
  for (const [v, t] of TYPES) { const o = el("option", null, t); o.value = v; type.appendChild(o); }
  const qty = field("Shares", num(1, 1), "tpqty");
  const price = field("Price", num(0.01), "tpprice");
  const trail = field("Trail by $", num(0.01, 0.01), "tptrail");
  const atrX = field("Trail by × ATR", num(0.1, 0.1), "tpatr"); atrX.value = 2;
  const atrN = field("ATR length", num(1, 1), "tpatrlen"); atrN.value = 14;
  const bracket = el("input"); bracket.type = "checkbox";
  const bl = el("label", "checkline tpbracket"); bl.append(bracket, " Stop and target"); form.appendChild(bl);
  const stop = field("Stop $ away", num(0.01, 0.01), "tpstop");
  const target = field("Target $ away", num(0.01, 0.01), "tptarget");
  const row = el("div", "tpbtns");
  const buy = btn("Buy", () => send("buy"), "Buy", "tpbuy");
  const sell = btn("Sell", () => send("sell"), "Sell", "tpsell");
  const flat = btn("Flatten", () => onAction({ kind: "flatten" }), "Cancel every order and close the position on the next bar", "tpflat");
  row.append(buy, sell, flat);
  form.appendChild(row);
  let last = null, touched = false;

  const show = () => {
    const k = type.value;
    price.parentElement.hidden = !(k === "limit" || k === "stop");
    trail.parentElement.hidden = k !== "trail";
    atrX.parentElement.hidden = atrN.parentElement.hidden = k !== "trail_atr";
    stop.parentElement.hidden = target.parentElement.hidden = !bracket.checked;
  };
  type.onchange = () => { if (last != null && !price.value) price.value = last.toFixed(2); show(); };
  bracket.onchange = show;
  form.oninput = () => { touched = true; };
  form.onsubmit = (e) => { e.preventDefault(); };      // Enter doesn't pick a side: Buy or Sell does

  function send(side) {
    const k = type.value, n = parseInt(qty.value, 10);
    const order = { side, qty: n, type: k === "trail_atr" ? "trail" : k };
    if (k === "limit" || k === "stop") order.price = parseFloat(price.value);
    if (k === "trail") order.trail = { amount: parseFloat(trail.value) };
    // N x the ATR on the chart's bars, worked out on the server when the order goes in (app/backtesting/orders.py)
    if (k === "trail_atr") order.trail = { atr: parseFloat(atrX.value), length: parseInt(atrN.value, 10), tf: tfOf() };
    if (!bracket.checked) return onAction({ kind: "order", order });
    const sign = side === "buy" ? 1 : -1, from = order.price ?? last;
    onAction({ kind: "bracket", order, stop: { price: round(from - sign * parseFloat(stop.value)) },
               target: { price: round(from + sign * parseFloat(target.value)) } });
  }

  show();
  return {
    form,
    // the session now: the last price for the defaults (until the form is changed by hand), and whether it can trade
    update(price_, equity, enabled) {
      last = price_;
      if (!touched && last) {
        qty.value = Math.max(1, Math.min(100, Math.floor((equity || 0) / last)));   // what the account can afford, up to 100
        price.value = last.toFixed(2);
        trail.value = (last * 0.002).toFixed(2);
        stop.value = (last * 0.003).toFixed(2);
        target.value = (last * 0.006).toFixed(2);
      }
      for (const b of [buy, sell, flat]) b.disabled = !enabled;
    },
    reset() { touched = false; },
  };
}

const round = (x) => Math.round(x * 100) / 100;
