/* A watch list cell in the grid: a list of symbols with fixed columns (last, change, change %, volume, high,
   low) from the cached 1-minute bars of the day on screen, up to the Replay cursor. Clicking a row, or moving
   through the list with the arrow keys, shows that symbol on every chart of the watch list's link group
   (links.js), or on the active chart when it isn't linked.
   The symbols come from one of three places: its own list, a watch list saved under Load data…, or a FinViz
   screen or portfolio (fetched by the collector; feed.js). Data: /api/quotes. */
import { refreshAll, requestData } from "./data.js";
import { Feed } from "./feed.js";
import { setActive, toggleMaximize } from "./grid.js";
import { groupOf, linkControl, members, publish } from "./links.js";
import { openCellMenu } from "./saved.js";
import { app, save } from "./state.js";
import { api, btn, el, fmtValue, inUse, uid } from "./util.js";

export const COLUMNS = [
  ["symbol", "Symbol"], ["last", "Last"], ["change", "Chg"], ["pct", "Chg %"], ["volume", "Volume"],
  ["high", "High"], ["low", "Low"],
];
export const MAX_SYMBOLS = 100;
const DEMO_RE = /-DEMO$/;
const FEED = "@feed";                           // the list menu's value for an outside source

// large values (e.g. NYSE up - down volume) shortened like the charts' axes: 25.04M
const num = (x) => (x == null ? "–" : Math.abs(x) >= 1e6 ? fmtValue(x) : x.toFixed(2));
const signed = (x) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + num(Math.abs(x)));

export class WatchList {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.symbols = Array.isArray(cfg.symbols) ? cfg.symbols.slice(0, MAX_SYMBOLS) : [];
    this.list = cfg.list || "";                 // a saved watch list's name, FEED, or "" for its own list
    this.link = cfg.link || "";                 // link group (links.js); "" drives the active chart
    this.feed = new Feed(cfg.feed, () => { this.render(); this.refresh(); });
    this.rows = []; this.selected = null; this.seq = 0;
    this.buildDom();
    if (this.list === FEED) this.feed.load();
  }

  config() {
    return { kind: "watchlist", id: this.id, symbols: this.symbols, list: this.list, link: this.link, feed: this.feed.config() };
  }
  destroy() { this.dead = true; this.feed.stop(); this.root.remove(); }
  shown() {
    if (this.list === FEED) return this.feed.symbols.slice(0, MAX_SYMBOLS);
    return this.list ? (app.saved.watchlists[this.list] || []) : this.symbols;
  }
  // the charts a pick changes: the link group's, or the active chart
  charts() {
    if (this.link) return members(this).filter((c) => c.setSymbol);
    const a = app.active || app.panels[0];
    return a ? [a] : [];
  }

  buildDom() {
    const root = this.root = el("section", "panel wl");
    root.dataset.cell = "watchlist";
    const head = el("div", "phead");
    head.appendChild(el("b", "wltitle", "Watch list"));
    this.listSel = el("select", "wllist"); this.listSel.setAttribute("aria-label", "List");
    this.listSel.title = "Its own list, a watch list saved under Load data…, or a FinViz screen or portfolio";
    this.listSel.onchange = () => {
      const v = this.listSel.value;
      if (v === FEED && !this.feed.address) { this.listSel.value = this.list; this.edit(FEED); return; }
      this.list = v; save(); this.render();
      if (v === FEED) this.feed.load(); else this.feed.stop();
      this.refresh();
    };
    const editB = btn("Edit", () => this.edit(this.list === FEED ? FEED : ""), "Edit the symbols", "wledit");
    const linkB = linkControl(this, () => this.render());
    const menuB = btn("≡", (e) => openCellMenu(e.currentTarget, this), "Watch list menu", "viewsbtn");
    menuB.title = "Add a chart or watch list next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this watch list", "maxbtn");
    head.append(this.listSel, linkB, editB, el("span", "wlgrow"), menuB, this.maxBtn);

    this.editor = el("form", "wleditor"); this.editor.hidden = true;
    this.text = el("textarea"); this.text.rows = 4; this.text.setAttribute("aria-label", "Symbols");
    const ok = el("button", "primary", "Apply"); ok.type = "submit";
    const cancel = btn("Cancel", () => { this.editor.hidden = true; });
    this.editMsg = el("span", "muted small");
    const row = el("div", "wlrow"); row.append(ok, cancel, this.editMsg);
    this.editor.append(this.text, row);
    this.editor.onsubmit = (e) => { e.preventDefault(); this.applyEdit(); };

    this.body = el("div", "wlbody");
    this.body.tabIndex = 0;
    this.body.setAttribute("aria-label", "Watch list: arrow keys move through it and change the linked charts");
    this.body.onkeydown = (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const list = this.shown();
      if (!list.length) return;
      const at = list.indexOf(this.selected);
      this.pick(list[Math.max(0, Math.min(list.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))]);
    };
    this.table = el("table", "wltable");
    this.body.appendChild(this.table);
    this.foot = el("div", "wlfoot muted small");
    root.append(head, this.editor, this.body, this.foot);
    this.render();
  }

  // the menu and the table from what's known now (no fetch)
  render() {
    if (this.dead) return;
    if (!inUse(this.listSel)) {
      this.listSel.innerHTML = "";
      const add = (v, t) => { const o = el("option", null, t); o.value = v; this.listSel.appendChild(o); };
      add("", "Own list");
      for (const n of Object.keys(app.saved.watchlists || {}).sort()) add(n, n);
      if (this.list && this.list !== FEED && !app.saved.watchlists?.[this.list]) add(this.list, `${this.list} (deleted)`);
      add(FEED, this.feed.address ? "FinViz" : "FinViz screen or portfolio…");
      this.listSel.value = this.list;
    }
    const charts = this.charts();
    if (charts.length) this.selected = charts[0].symbol;
    const target = this.link ? `the ${groupOf(this.link).name.toLowerCase()} linked charts` : "the active chart";
    const t = this.table;
    t.innerHTML = "";
    const h = el("tr");
    for (const [, label] of COLUMNS) h.appendChild(el("th", null, label));
    t.appendChild(h);
    const byS = Object.fromEntries(this.rows.map((r) => [r.symbol, r]));
    for (const sym of this.shown()) {
      const r = byS[sym] || { symbol: sym };
      const tr = el("tr", "wlr" + (sym === this.selected ? " sel" : ""));
      tr.dataset.symbol = sym;
      tr.title = `Show ${sym} on ${target}`;
      tr.onclick = () => this.pick(sym);
      const dir = r.change > 0 ? " up" : r.change < 0 ? " down" : "";
      tr.append(el("td", "wlsym", sym));
      if (r.status === "ok") {
        tr.append(el("td", null, num(r.last)), el("td", "wlchg" + dir, signed(r.change)), el("td", "wlchg" + dir, r.pct == null ? "–" : signed(r.pct) + "%"),
                  el("td", null, r.volume == null ? "–" : fmtValue(r.volume).replace(/\.00$/, "")), el("td", null, num(r.high)), el("td", null, num(r.low)));
      } else {
        const td = el("td", "muted", r.status === "missing" ? "not cached for this day" : r.status === "none yet" ? "no bars yet" : "");
        td.colSpan = COLUMNS.length - 1;
        tr.appendChild(td);
      }
      t.appendChild(tr);
    }
    this.renderFoot();
  }

  renderFoot() {
    const missing = this.rows.filter((r) => r.status === "missing" && !DEMO_RE.test(r.symbol)).map((r) => r.symbol);
    this.foot.innerHTML = "";
    if (this.list === FEED) this.foot.appendChild(this.feed.status(MAX_SYMBOLS));
    const n = this.shown().length;
    const empty = this.list === FEED ? "" : "No symbols: press Edit.";
    if (n || empty) this.foot.appendChild(el("span", null, n ? `${n} symbol${n === 1 ? "" : "s"}, ${app.live ? "live" : app.day || ""}` : empty));
    if (missing.length) {
      const b = btn(`Fetch ${missing.length} from TWS`, () => { requestData(missing); b.disabled = true; b.textContent = "Asked TWS…"; },
                    null, "wlfetch");
      b.title = missing.join(" ");
      this.foot.appendChild(b);
    }
  }

  async refresh() {
    if (this.dead) return;
    if (this.list === FEED) this.feed.load();             // throttled: only when the list is due
    const list = this.shown(), mine = ++this.seq;
    if (!list.length || !app.day) { this.rows = []; this.render(); return; }
    const cursor = app.live || app.cursor == null ? "" : `&cursor=${app.cursor}`;
    try {
      const r = await api(`/api/quotes?symbols=${encodeURIComponent(list.join(","))}&day=${app.day}${cursor}`);
      if (mine !== this.seq || this.dead) return;
      this.rows = r.items;
    } catch (e) { if (mine === this.seq) this.foot.textContent = "Error: " + e.message; return; }
    this.render();
  }

  pick(sym) {
    this.selected = sym;
    if (this.link) {
      publish(this, sym);                                 // every chart and watch list of the group
    } else {
      const chart = this.charts()[0];
      if (!chart) return;
      setActive(chart);
      chart.setSymbol(sym);                               // which passes it on to the chart's own group
    }
    this.render();
  }

  // links.js: another cell of the group changed symbol, or the group or active chart changed
  showLinked(sym) { this.selected = sym; this.render(); }
  linksChanged() { this.render(); }
  activeChanged() { this.render(); }

  edit(mode) {
    this.editor.hidden = !this.editor.hidden || this.editMode !== mode ? false : true;
    this.editMode = mode;
    if (this.editor.hidden) return;
    if (mode === FEED) {
      this.text.setAttribute("aria-label", "FinViz address");
      this.text.placeholder = "The address of a FinViz screen or portfolio, e.g. https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers";
      this.text.value = this.feed.address || "";
      this.editMsg.textContent = "Copy it from your browser's address bar on finviz.com. Needs FinViz Elite (FINVIZ_TOKEN in .env).";
    } else {
      this.text.setAttribute("aria-label", "Symbols");
      this.text.placeholder = "Symbols separated by spaces, commas or lines (a thinkorswim share link works too)";
      this.text.value = this.shown().join(" ");
      this.editMsg.textContent = this.list && this.list !== FEED ? `Editing a copy: saved list "${this.list}" stays as it is.` : "";
    }
    this.text.focus();
  }

  async applyEdit() {
    if (this.editMode === FEED) {
      const before = this.list;
      this.list = FEED;                                   // so the new symbols' rows are asked for as they arrive
      const err = await this.feed.set(this.text.value);
      if (err) { this.list = before; this.editMsg.textContent = err; return; }
      this.editor.hidden = true;
      save(); this.render(); this.refresh();
      return;
    }
    let r;
    try { r = await api("/api/symbols/parse", { text: this.text.value }); } catch (e) { this.editMsg.textContent = e.message; return; }
    this.symbols = r.symbols.slice(0, MAX_SYMBOLS);
    this.list = ""; this.feed.stop();
    this.editMsg.textContent = r.skipped?.length ? `Skipped: ${r.skipped.join(" ")}` : "";
    if (!r.skipped?.length) this.editor.hidden = true;
    save(); this.render();
    await this.refresh();
    refreshAll();
  }
}
