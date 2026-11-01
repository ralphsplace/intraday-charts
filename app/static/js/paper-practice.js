/* Replay practice on a chart (mixed into Panel): trading a paper account by hand while stepping through a past
   day (app/paper/practice.py, /api/paper/practice). Simulated on the NAS from the cached bars: nothing here talks to
   TWS or IBKR, and nothing places a real order.

   When the chart has an account (its ≡ menu), a strip under the header shows the position, P/L and equity, the
   working orders (× cancels one), and Buy / Sell / Flatten. Orders and the average price are drawn as labelled
   price lines (never arrows). Fills show as a message with a sound. Stepping the replay back past trades asks
   before removing them. */
import { amount, dollars } from "./format.js";
import { toast, toastAction } from "./notify.js";
import { app, save } from "./state.js";
import { renderPriceLines } from "./tools/priceline.js";
import { api, btn, el } from "./util.js";

const TYPES = [["market", "Market"], ["limit", "Limit"], ["stop", "Stop"], ["trail", "Trailing stop"], ["level", "At a study line"]];
const SHORT = { market: "MKT", limit: "LMT", stop: "STP", trail: "TRAIL", level: "LVL" };
const COLOR = { buy: "#26a69a", sell: "#ef5350", avg: "#c9d1d9" };

export class PaperPractice {
  // ---------------------------------------------------------------- the strip
  buildPaper() {
    this.paperBar = el("div", "paperbar"); this.paperBar.hidden = true;
    this.paperInfo = el("span", "paperinfo");
    this.paperOrders = el("span", "paperorders");
    const buy = btn("Buy", (e) => this.openTicket(e.currentTarget, "buy"), "Buy: market, limit, stop, trailing or at a study line", "paperbuy");
    const sell = btn("Sell", (e) => this.openTicket(e.currentTarget, "sell"), "Sell: market, limit, stop, trailing or at a study line", "papersell");
    const flat = btn("Flatten", () => this.paperAct({ kind: "flatten" }), "Cancel every order and close the position on the next bar", "paperflat");
    this.paperBtns = [buy, sell, flat];
    this.paperBar.append(el("b", "papertag", "Paper"), this.paperInfo, this.paperOrders, el("span", "wlgrow"), buy, sell, flat);
    return this.paperBar;
  }

  setPaperAccount(id) {
    this.paper = id || "";
    this.paperView = null; this.asked = null;
    this.closeTicket();
    save();
    if (this.view) this.paperRefresh(this.view); else this.paperBar.hidden = !this.paper;
  }

  where() { return { account: this.paper, symbol: this.symbol, day: app.day, cursor: this.view?.cursor ?? 0 }; }

  // after every render: the session at this chart's cursor
  async paperRefresh(v) {
    this.paperBar.hidden = !this.paper;
    if (!this.paper) { renderPriceLines(this, "paper", [], () => "", () => ""); return; }
    if (app.live || v.period) {
      this.paperInfo.textContent = "Practice works in Replay, on minute charts.";
      this.paperOrders.innerHTML = ""; this.paperBtns.forEach((b) => { b.disabled = true; });
      renderPriceLines(this, "paper", [], () => "", () => "");
      return;
    }
    const seq = (this.paperSeq = (this.paperSeq || 0) + 1);
    let r;
    try { r = await api("/api/paper/practice", this.where()); }
    catch (e) { if (seq === this.paperSeq) this.paperInfo.textContent = "Paper: " + e.message; return; }
    if (seq !== this.paperSeq || this.dead) return;
    this.showPaper(r);
  }

  showPaper(r) {
    this.paperView = r;
    const q = r.equity, ahead = r.later_actions > 0;
    const pos = q.position ? `${q.position > 0 ? "Long" : "Short"} ${Math.abs(q.position)} @ ${q.avg.toFixed(2)}` : "Flat";
    this.paperInfo.innerHTML = "";
    this.paperInfo.append(el("span", "paperacct", r.account + (r.demo ? " (synthetic data)" : "")), el("span", null, pos));
    if (q.position) this.paperInfo.appendChild(el("span", q.unrealized >= 0 ? "up" : "down", `Unrl ${dollars(q.unrealized, { d: 2 })}`));
    this.paperInfo.append(el("span", q.realized >= 0 ? "up" : "down", `Real ${dollars(q.realized, { d: 2 })}`),
                          el("span", "muted", `Equity $${amount(q.equity, 0)}`));
    if (r.closed) this.paperInfo.appendChild(el("span", "muted", "· the session has ended"));
    this.paperOrders.innerHTML = "";
    for (const o of r.orders) {
      const chip = el("span", "paperorder " + o.side, `${o.side.toUpperCase()} ${SHORT[o.type]} ${o.qty}` +
                      (o.price != null ? ` ${o.price.toFixed(2)}` : "") + (o.active ? "" : " (waits)"));
      chip.appendChild(btn("×", () => this.paperAct({ kind: "cancel", id: o.id }), `Cancel order ${o.id}`, "paperx"));
      this.paperOrders.appendChild(chip);
    }
    this.paperBtns.forEach((b) => { b.disabled = ahead || r.closed; });
    // orders and the average price, as lines on the chart
    const lines = r.orders.filter((o) => o.price != null && o.active).map((o) => ({ price: o.price, side: o.side, label: `${o.side.toUpperCase()} ${SHORT[o.type]} ${o.qty}`, style: "dashed" }));
    if (q.position) lines.push({ price: q.avg, side: "avg", label: `AVG ${q.position}`, style: "dotted" });
    renderPriceLines(this, "paper", lines, (d) => COLOR[d.side], (d) => d.label, "dashed");
    for (const f of r.new_fills) toast(`Paper ${r.account}: ${f.side.toUpperCase()} ${f.qty} ${r.symbol} @ ${f.price.toFixed(2)}${f.note ? " (" + f.note + ")" : ""}`);
    for (const why of r.refused) toast("Paper: " + why, true);
    if (ahead && this.asked !== r.cursor) {
      this.asked = r.cursor;
      toastAction(`The replay is before ${r.later_actions} of ${r.account}'s trades. Remove them to trade from here?`, "Remove",
                  () => this.paperRewind(), 12000);
    }
  }

  async paperAct(action) {
    this.closeTicket();
    try { this.showPaper(await api("/api/paper/practice/act", { ...this.where(), ...action })); }
    catch (e) { toast("Paper: " + e.message, true); return; }
    paperChanged(this, this.paper, this.symbol);
  }

  async paperRewind() {
    try { this.showPaper(await api("/api/paper/practice/rewind", this.where())); toast("Removed the later trades."); }
    catch (e) { toast("Paper: " + e.message, true); return; }
    paperChanged(this, this.paper, this.symbol);
  }

  // ---------------------------------------------------------------- the order ticket
  closeTicket() { if (this.ticket) { this.ticket.remove(); this.ticket = null; } }

  // the chart's study lines an order can follow (VWAP, SMA 50, ...), as study_values specs
  studyLines() {
    const out = [];
    for (const s of this.studies.filter((x) => x.visible)) {
      const res = this.view?.studies?.[s.uid];
      for (const ln of res?.lines || []) {
        if (!ln.data?.length) continue;
        out.push({ label: `${res.label || s.type}: ${ln.title || ln.id}`, spec: { type: s.type, params: s.params, output: ln.id, tf: this.tf } });
      }
    }
    return out;
  }

  openTicket(anchor, side) {
    if (this.ticket?.dataset.side === side) return this.closeTicket();
    this.closeTicket();
    const last = this.view?.price ?? 0;
    const t = this.ticket = el("form", "paperticket");
    t.dataset.side = side;
    const field = (label, input) => { const l = el("label", null, label); l.appendChild(input); t.appendChild(l); return input; };
    const num = (v, step) => { const i = el("input"); i.type = "number"; i.step = step; i.value = v; return i; };
    t.appendChild(el("b", side, `${side === "buy" ? "Buy" : "Sell"} ${this.symbol}`));
    const type = field("Order", el("select"));
    for (const [v, txt] of TYPES) { const o = el("option", null, txt); o.value = v; type.appendChild(o); }
    const cash = this.paperView?.equity.equity ?? 0;                       // a size the account can afford, up to 100
    const qty = field("Shares", num(Math.max(1, Math.min(100, Math.floor(cash / (last || 1)))), 1)); qty.min = 1;
    const price = field("Price", num(last.toFixed(2), 0.01));
    const trail = field("Trail by ($)", num((last * 0.002).toFixed(2), 0.01));
    const lines = this.studyLines();
    const line = field("Study line", el("select"));
    for (const [i, x] of lines.entries()) { const o = el("option", null, x.label); o.value = String(i); line.appendChild(o); }
    const br = el("label", "papercheck"); const brOn = el("input"); brOn.type = "checkbox"; br.append(brOn, " Attach a stop and target"); t.appendChild(br);
    const away = side === "buy" ? -1 : 1;
    const stop = field("Stop", num((last + away * last * 0.003).toFixed(2), 0.01));
    const target = field("Target", num((last - away * last * 0.006).toFixed(2), 0.01));
    const msg = el("span", "muted small");
    const ok = el("button", "primary", "Place"); ok.type = "submit";
    const row = el("div", "wlrow"); row.append(ok, btn("Cancel", () => this.closeTicket()), msg); t.appendChild(row);
    const show = () => {
      const k = type.value;
      price.parentElement.hidden = !(k === "limit" || k === "stop");
      trail.parentElement.hidden = k !== "trail";
      line.parentElement.hidden = k !== "level";
      stop.parentElement.hidden = target.parentElement.hidden = !brOn.checked;
      msg.textContent = k === "level" && !lines.length ? "Add a study with a line (VWAP, SMA…) to this chart first." : "";
    };
    type.onchange = show; brOn.onchange = show; show();
    t.onsubmit = (e) => {
      e.preventDefault();
      const k = type.value, n = parseInt(qty.value, 10);
      const order = { side, qty: n, type: k };
      if (k === "limit" || k === "stop") order.price = parseFloat(price.value);
      if (k === "trail") order.trail = { amount: parseFloat(trail.value) };
      if (k === "level") {
        const x = lines[+line.value];
        if (!x) return;
        const now = levelNow(this.view.studies, x.spec) ?? last;   // below the price: a buy limit; above: a buy stop
        order.level = { spec: x.spec, as: (side === "buy") === (now < last) ? "limit" : "stop" };
      }
      if (brOn.checked) this.paperAct({ kind: "bracket", order, stop: { price: parseFloat(stop.value) }, target: { price: parseFloat(target.value) } });
      else this.paperAct({ kind: "order", order });
    };
    t.onkeydown = (e) => { if (e.key === "Escape") this.closeTicket(); };
    this.root.appendChild(t);
    const a = anchor.getBoundingClientRect(), r = this.root.getBoundingClientRect();
    t.style.top = `${a.bottom - r.top + 4}px`;
    t.style.right = `${Math.max(4, r.right - a.right)}px`;
    qty.focus(); qty.select();
  }

  // the chart's account (kept with the chart), for config()
  paperConfig() { return this.paper ? { paper: this.paper } : {}; }
}

// one cell traded: every other chart strip and trade panel on the same account and symbol shows it
export function paperChanged(from, account, symbol) {
  for (const c of app.cells) {
    if (c === from || c.symbol !== symbol) continue;
    if (c.paper === account && c.view) c.paperRefresh(c.view);
    else if (c.account === account && c.loadAccounts) c.refresh();
  }
}

// a study line's latest value in the chart's view
function levelNow(studies, spec) {
  for (const r of Object.values(studies || {})) {
    const ln = (r.lines || []).find((l) => l.id === spec.output && r.type === spec.type);
    if (ln?.data?.length) return ln.data[ln.data.length - 1].value;
  }
  return null;
}

// the ≡ menu's section: which paper account this chart trades in (or none)
export async function paperSection(panel) {
  const box = el("div", "mpaper");
  box.appendChild(el("div", "mtitle", "Paper trading (practice in Replay)"));
  const sel = el("select", "paperacctsel");
  sel.setAttribute("aria-label", "Paper account for this chart");
  const add = (v, t) => { const o = el("option", null, t); o.value = v; sel.appendChild(o); };
  add("", "Off");
  let accts = {};
  try { accts = (await api("/api/paper/accounts")).accounts; } catch (e) { box.appendChild(el("span", "muted small", e.message)); }
  for (const [name, a] of Object.entries(accts).sort()) add(a.id, `${name} ($${amount(a.balance, 0)})`);
  sel.value = Object.values(accts).some((a) => a.id === panel.paper) ? panel.paper : "";
  sel.onchange = () => panel.setPaperAccount(sel.value);
  const link = el("a", "small", Object.keys(accts).length ? "Accounts…" : "Make an account…");
  link.href = "/config?tab=paper"; link.target = "_blank";
  box.append(sel, link);
  return box;
}
