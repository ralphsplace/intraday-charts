/* A trade panel in the grid: Buy / Sell on your IBKR paper account (#84; app/live_orders.py, tools/trader.py), for the
   symbol of its link group (links.js), or of the active chart when it isn't linked. It shows the account TWS reports,
   the position, working orders (× cancels one) and today's fills, as TWS says them, asked again every few seconds.

   Orders go out only in Live, only with LIVE_ORDERS=paper, and only while TWS reports a paper account (DU…): the
   server and the collector's trader both check, and the panel says why when they won't. Market data and everything
   else stay read-only. */
import { dollars, fmtMin } from "./format.js";
import { toggleMaximize } from "./grid.js";
import { linkControl, members } from "./links.js";
import { toast } from "./notify.js";
import { openCellMenu } from "./saved.js";
import { app } from "./state.js";
import { tradeTicket } from "./trade-ticket.js";
import { api, btn, el, uid } from "./util.js";

const SHORT = { market: "MKT", limit: "LMT", stop: "STP", trail: "TRAIL" };
const EVERY = 3000;                                     // ms between asking TWS's view again
const enc = encodeURIComponent;

export class TradePanel {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.link = cfg.link || "";
    this.symbol = null;
    this.live = null;                                   // the last /api/live view
    this.seq = 0;
    this.buildDom();
    this.follow();
    this.timer = setInterval(() => { if (!document.hidden) this.refresh(); }, EVERY);
  }

  config() { return { kind: "trade", id: this.id, link: this.link }; }
  destroy() { this.dead = true; clearInterval(this.timer); this.root.remove(); }

  // the chart it follows: the first chart of its link group, or the active chart
  chart() {
    if (this.link) return members(this).find((c) => c.setSymbol) || null;
    return app.active || app.panels[0] || null;
  }

  // the last price on the followed chart, in Live (what the ticket's defaults and distances start from)
  lastPrice() {
    const v = this.chart()?.view;
    return app.live && v?.symbol === this.symbol && v.bars?.length ? v.price : null;
  }

  buildDom() {
    const root = this.root = el("section", "panel tp");
    root.dataset.cell = "trade";
    const head = el("div", "phead");
    head.appendChild(el("b", "tptitle", "Trade"));
    this.symEl = el("b", "tpsym", "–");
    this.acctEl = el("span", "tpacct muted small", "");
    const linkB = linkControl(this, () => this.follow());
    const menuB = btn("≡", (e) => openCellMenu(e.currentTarget, this), "Trade panel menu", "viewsbtn");
    menuB.title = "Add a chart, watch list or trade panel next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this trade panel", "maxbtn");
    head.append(this.symEl, this.acctEl, linkB, el("span", "wlgrow"), menuB, this.maxBtn);
    this.info = el("div", "tpinfo");
    this.notice = el("div", "tpnotice muted small");
    this.ticket = tradeTicket((a) => this.act(a), () => this.chart()?.tf || 1);
    this.body = el("div", "tpbody");
    this.orders = el("table", "wltable tporders");
    this.fills = el("table", "wltable tpfills");
    this.body.append(el("div", "tpsub", "Working orders"), this.orders, el("div", "tpsub", "Fills today"), this.fills);
    root.append(head, this.info, this.notice, this.ticket.form, this.body);
  }

  // ---------------------------------------------------------------- following a symbol (links.js)
  follow() { this.setSymbol(this.chart()?.symbol || this.symbol); }
  setSymbol(sym) {
    if (!sym || sym === this.symbol) return;
    this.symbol = sym; this.live = null; this.ticket.reset();
    this.symEl.textContent = sym;
    this.refresh();
  }
  showLinked(sym) { this.setSymbol(sym); }
  linksChanged() { this.follow(); }
  activeChanged() { if (!this.link) this.follow(); }

  // ---------------------------------------------------------------- TWS's view of the symbol
  async refresh() {
    if (this.dead || !this.symbol) return;
    const seq = ++this.seq;
    let v;
    try { v = await api(`/api/live?symbol=${enc(this.symbol)}`); }
    catch (e) { if (seq === this.seq) this.notice.textContent = e.message; return; }
    if (seq !== this.seq || this.dead) return;
    this.show(v);
  }

  show(v) {
    const before = this.live?.symbol === v.symbol ? this.live.fills.length : null;
    for (const f of before == null ? [] : v.fills.slice(before)) {     // fills since the last look: say so, with a sound
      toast(`IBKR paper: ${f.side.toUpperCase()} ${f.qty} ${v.symbol} @ ${f.price.toFixed(2)}`);
    }
    this.live = v;
    this.acctEl.textContent = v.account ? `IBKR paper ${v.account}` : v.on ? "IBKR paper" : "Orders off";
    this.acctEl.title = v.ready ? `Orders go to IBKR paper account ${v.account}` : v.why_not || "";
    const p = v.position, last = this.lastPrice();
    this.info.innerHTML = "";
    const pos = p.qty ? `${p.qty > 0 ? "Long" : "Short"} ${Math.abs(p.qty)} @ ${p.avg?.toFixed(2) ?? "–"}` : "Flat";
    this.info.appendChild(el("span", "tppos" + (p.qty > 0 ? " up" : p.qty < 0 ? " down" : ""), pos));
    if (p.qty && last != null && p.avg != null) {
      const u = (last - p.avg) * p.qty;
      this.info.appendChild(el("span", u >= 0 ? "up" : "down", `Unrl ${dollars(u, { d: 2 })}`));
    }
    if (last != null) this.info.appendChild(el("span", "muted", `Last ${last.toFixed(2)}`));
    this.notice.textContent = !v.ready ? v.why_not : !app.live ? "Orders go to IBKR in Live: turn Live on to trade."
      : last == null ? "Waiting for the chart's live price." : "";
    const can = v.ready && app.live && last != null;
    this.ticket.update(last, can, v.max_shares);
    this.renderOrders(v.orders, v.ready && app.live);
    this.renderFills(v.fills);
  }

  renderOrders(orders, canCancel) {
    const t = this.orders;
    t.innerHTML = "";
    if (!orders.length) { const td = el("td", "muted", "None"); td.colSpan = 5; t.appendChild(el("tr")).appendChild(td); return; }
    const head = el("tr");
    for (const h of ["Side", "Type", "Shares", "Price", ""]) head.appendChild(el("th", null, h));
    t.appendChild(head);
    for (const o of orders) {
      const tr = el("tr");
      tr.dataset.id = o.id;
      tr.title = `TWS order ${o.id}: ${o.status}` + (o.parent ? ` (attached to ${o.parent})` : "");
      tr.append(el("td", o.side === "buy" ? "up" : "down", o.side.toUpperCase()), el("td", null, SHORT[o.type] || o.type),
                el("td", null, String(o.qty)), el("td", null, o.price != null ? o.price.toFixed(2) : "–"));
      const x = btn("×", () => this.act({ kind: "cancel", id: o.id }), `Cancel the ${o.side} ${SHORT[o.type] || o.type} order`, "tpx");
      x.disabled = !canCancel;
      tr.appendChild(el("td")).appendChild(x);
      t.appendChild(tr);
    }
  }

  renderFills(fills) {
    const t = this.fills;
    t.innerHTML = "";
    if (!fills.length) { const td = el("td", "muted", "None yet"); td.colSpan = 4; t.appendChild(el("tr")).appendChild(td); return; }
    const head = el("tr");
    for (const h of ["Time", "Side", "Shares", "Price"]) head.appendChild(el("th", null, h));
    t.appendChild(head);
    for (const f of [...fills].reverse()) {
      const when = f.time ? fmtMin(minuteET(f.time)) : "–";
      t.appendChild(el("tr")).append(el("td", null, when), el("td", f.side === "buy" ? "up" : "down", f.side.toUpperCase()),
                                     el("td", null, String(f.qty)), el("td", null, f.price.toFixed(2)));
    }
  }

  // ---------------------------------------------------------------- sending an order, a cancel or a flatten
  async act(a) {
    if (!this.live?.ready || !app.live) return;
    const body = { action: a.kind, symbol: this.symbol, ...(a.order ? { order: a.order } : {}), ...(a.stop ? { stop: a.stop } : {}),
                   ...(a.target ? { target: a.target } : {}), ...(a.kind === "cancel" ? { order_id: a.id } : {}) };
    let r;
    try { r = await api("/api/live/orders", body); }
    catch (e) { toast("IBKR paper: " + e.message, true); return; }
    toast(`IBKR paper ${this.live.account || ""}: ${r.message}`);
    this.ticket.reset();
    if (r.view) this.show(r.view); else this.refresh();
  }
}

// a fill's time (epoch seconds) as the minute of the day in New York
function minuteET(t) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "numeric", hourCycle: "h23" })
    .formatToParts(new Date(t * 1000));
  const get = (k) => +parts.find((x) => x.type === k).value;
  return get("hour") * 60 + get("minute");
}
