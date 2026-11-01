/* A trade panel in the grid: a paper account's Buy / Sell ticket for the symbol of its link group (links.js), or of
   the active chart when it isn't linked, at the Replay cursor. It shows the position, P/L and equity, the working
   orders (× cancels one) and the day's fills, and trades through the same practice session as the charts' paper
   strips (paper-practice.js, /api/paper/practice), so a chart of that symbol in that account shows the same orders.
   Simulated on the NAS from the cached bars: nothing here talks to TWS or IBKR, and nothing places a real order. */
import { amount, dollars, fmtMin } from "./format.js";
import { toggleMaximize } from "./grid.js";
import { linkControl, members } from "./links.js";
import { toast } from "./notify.js";
import { paperChanged } from "./paper-practice.js";
import { openCellMenu } from "./saved.js";
import { app, save } from "./state.js";
import { tradeTicket } from "./trade-ticket.js";
import { api, btn, el, uid } from "./util.js";

const SHORT = { market: "MKT", limit: "LMT", stop: "STP", trail: "TRAIL", level: "LVL" };

// accounts made, renamed or deleted in Config (another tab) show when this one comes back into view
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) for (const c of app.cells) if (c instanceof TradePanel) c.loadAccounts();
});

export class TradePanel {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.link = cfg.link || "";
    this.account = cfg.account || "";           // a paper account's id
    this.symbol = null;
    this.session = null;
    this.seq = 0;
    this.buildDom();
    this.loadAccounts();
  }

  config() { return { kind: "trade", id: this.id, link: this.link, account: this.account }; }
  destroy() { this.dead = true; this.root.remove(); }

  // the chart it follows: the first chart of its link group, or the active chart
  chart() {
    if (this.link) return members(this).find((c) => c.setSymbol) || null;
    return app.active || app.panels[0] || null;
  }

  // the replay time it trades at: the window's cursor, else the end of the followed chart's bars
  cursor() {
    if (app.cursor != null) return app.cursor;
    const c = this.chart();
    if (c?.view?.symbol === this.symbol && c.view.cursor != null) return c.view.cursor;
    return Math.max(241, ...app.panels.map((p) => p.view?.last_minute || 0));
  }

  where() { return { account: this.account, symbol: this.symbol, day: app.day, cursor: this.cursor() }; }

  buildDom() {
    const root = this.root = el("section", "panel tp");
    root.dataset.cell = "trade";
    const head = el("div", "phead");
    head.appendChild(el("b", "tptitle", "Paper trade"));
    this.symEl = el("b", "tpsym", "–");
    this.acctSel = el("select", "tpacct");
    this.acctSel.setAttribute("aria-label", "Paper account");
    this.acctSel.title = "The paper account this panel trades in (simulated: never a real order)";
    this.acctSel.onchange = () => { this.account = this.acctSel.value; this.session = null; this.ticket.reset(); save(); this.refresh(); };
    const linkB = linkControl(this, () => this.follow());
    const menuB = btn("≡", (e) => openCellMenu(e.currentTarget, this), "Trade panel menu", "viewsbtn");
    menuB.title = "Add a chart, watch list or trade panel next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this trade panel", "maxbtn");
    head.append(this.symEl, this.acctSel, linkB, el("span", "wlgrow"), menuB, this.maxBtn);

    this.info = el("div", "tpinfo");
    this.notice = el("div", "tpnotice muted small");
    this.ticket = tradeTicket((a) => this.act(a));
    this.body = el("div", "tpbody");
    this.orders = el("table", "wltable tporders");
    this.fills = el("table", "wltable tpfills");
    this.body.append(el("div", "tpsub", "Working orders"), this.orders, el("div", "tpsub", "Fills today"), this.fills);
    root.append(head, this.info, this.notice, this.ticket.form, this.body);
  }

  async loadAccounts() {
    let accts = {};
    try { accts = (await api("/api/paper/accounts")).accounts; }
    catch (e) { this.notice.textContent = "Paper accounts: " + e.message; return; }
    if (this.dead) return;
    const sel = this.acctSel, keep = this.account;
    sel.innerHTML = "";
    const add = (v, t) => { const o = el("option", null, t); o.value = v; sel.appendChild(o); };
    add("", Object.keys(accts).length ? "Pick an account…" : "No accounts yet");
    for (const [name, a] of Object.entries(accts).sort(([x], [y]) => x.localeCompare(y, undefined, { numeric: true }))) add(a.id, `${name} ($${amount(a.balance, 0)})`);
    const known = Object.values(accts).some((a) => a.id === keep);
    sel.value = known ? keep : "";
    if (!known && keep) { this.account = ""; save(); }        // deleted in Config
    if (!this.session) this.refresh();
  }

  // ---------------------------------------------------------------- following a symbol (links.js)
  follow() {
    const c = this.chart();
    this.setSymbol(c?.symbol || this.symbol);
  }
  setSymbol(sym) {
    if (!sym || sym === this.symbol) return;
    this.symbol = sym; this.session = null; this.ticket.reset();
    this.refresh();
  }
  showLinked(sym) { this.setSymbol(sym); }
  linksChanged() { this.follow(); }
  activeChanged() { if (!this.link) this.follow(); }

  // ---------------------------------------------------------------- the session at the cursor
  async refresh() {
    if (this.dead) return;
    if (!this.symbol) { const c = this.chart(); if (c?.symbol) this.symbol = c.symbol; }
    this.symEl.textContent = this.symbol || "–";
    if (!this.account) return this.idle("Pick a paper account to trade " + (this.symbol || "") + ". Accounts are made in Config, Paper accounts.");
    if (!this.symbol || !app.day) return this.idle("Waiting for a chart.");
    if (app.live) return this.idle("Paper trading works in Replay: turn Live off and step through a past day.");
    const seq = ++this.seq;
    let r;
    try { r = await api("/api/paper/practice", this.where()); }
    catch (e) { if (seq === this.seq) this.idle("Paper: " + e.message); return; }
    if (seq !== this.seq || this.dead) return;
    this.show(r);
  }

  idle(text) {
    this.session = null;
    this.info.innerHTML = ""; this.orders.innerHTML = ""; this.fills.innerHTML = "";
    this.notice.textContent = text;
    this.ticket.update(null, 0, false);
    this.ticket.form.hidden = this.body.hidden = true;            // nothing to trade yet
  }

  show(r) {
    this.session = r;
    this.ticket.form.hidden = this.body.hidden = false;
    const q = r.equity, ahead = r.later_actions > 0;
    this.info.innerHTML = "";
    const pos = q.position ? `${q.position > 0 ? "Long" : "Short"} ${Math.abs(q.position)} @ ${q.avg.toFixed(2)}` : "Flat";
    this.info.append(el("span", "tppos" + (q.position > 0 ? " up" : q.position < 0 ? " down" : ""), pos));
    if (q.position) this.info.appendChild(el("span", q.unrealized >= 0 ? "up" : "down", `Unrl ${dollars(q.unrealized, { d: 2 })}`));
    this.info.append(el("span", q.realized >= 0 ? "up" : "down", `Real ${dollars(q.realized, { d: 2 })}`),
                     el("span", "muted", `Equity $${amount(q.equity, 0)}`));
    if (r.price != null) this.info.appendChild(el("span", "muted", `Last ${r.price.toFixed(2)} at ${fmtMin(r.cursor)}`));
    this.notice.innerHTML = "";
    if (r.demo) this.notice.appendChild(el("span", null, "Synthetic data. "));
    if (r.closed) this.notice.appendChild(el("span", null, "The session has ended: every trade was closed at the last regular-hours bar."));
    if (ahead) {
      this.notice.append(el("span", null, `The replay is before ${r.later_actions} of ${r.account}'s trades. `),
                         btn("Remove them", () => this.rewind(), "Remove the trades after the replay time", "tprewind"));
    }
    this.ticket.update(r.price, q.equity, !ahead && !r.closed && r.price != null);
    this.renderOrders(r.orders);
    this.renderFills(r.fills);
    for (const f of r.new_fills) toast(`Paper ${r.account}: ${f.side.toUpperCase()} ${f.qty} ${r.symbol} @ ${f.price.toFixed(2)}${f.note ? " (" + f.note + ")" : ""}`);
    for (const why of r.refused) toast("Paper: " + why, true);
  }

  renderOrders(orders) {
    const t = this.orders;
    t.innerHTML = "";
    if (!orders.length) { const td = el("td", "muted", "None"); td.colSpan = 5; t.appendChild(el("tr")).appendChild(td); return; }
    const head = el("tr");
    for (const h of ["Side", "Type", "Shares", "Price", ""]) head.appendChild(el("th", null, h));
    t.appendChild(head);
    for (const o of orders) {
      const tr = el("tr");
      tr.dataset.id = o.id;
      tr.append(el("td", o.side === "buy" ? "up" : "down", o.side.toUpperCase()), el("td", null, SHORT[o.type] + (o.active ? "" : " (waits)")),
                el("td", null, String(o.qty)), el("td", null, o.price != null ? o.price.toFixed(2) : "–"));
      tr.appendChild(el("td")).appendChild(btn("×", () => this.act({ kind: "cancel", id: o.id }), `Cancel the ${o.side} ${SHORT[o.type]} order`, "paperx"));
      t.appendChild(tr);
    }
  }

  renderFills(fills) {
    const t = this.fills;
    t.innerHTML = "";
    if (!fills.length) { const td = el("td", "muted", "None yet"); td.colSpan = 5; t.appendChild(el("tr")).appendChild(td); return; }
    const head = el("tr");
    for (const h of ["Time", "Side", "Shares", "Price", "Why"]) head.appendChild(el("th", null, h));
    t.appendChild(head);
    for (const f of [...fills].reverse()) {
      t.appendChild(el("tr")).append(el("td", null, fmtMin(f.minute)), el("td", f.side === "buy" ? "up" : "down", f.side.toUpperCase()),
                                     el("td", null, String(f.qty)), el("td", null, f.price.toFixed(2)), el("td", "muted", f.note || ""));
    }
  }

  // ---------------------------------------------------------------- doing something
  async act(action) {
    if (!this.session) return;
    try { this.show(await api("/api/paper/practice/act", { ...this.where(), ...action })); }
    catch (e) { toast("Paper: " + e.message, true); return; }
    this.ticket.reset();
    paperChanged(this, this.account, this.symbol);
  }

  async rewind() {
    try { this.show(await api("/api/paper/practice/rewind", this.where())); toast("Removed the later trades."); }
    catch (e) { toast("Paper: " + e.message, true); return; }
    paperChanged(this, this.account, this.symbol);
  }
}
