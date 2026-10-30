/* A watch list cell in the grid: a list of symbols with fixed columns (last, change, change %, volume, high,
   low) from the cached 1-minute bars of the day on screen, up to the Replay cursor. Clicking a row, or moving
   through the list with the arrow keys, shows that symbol on the linked chart (the active one, or a chosen one).
   The list is its own or a saved watch list (Load data… keeps those). Data: /api/quotes. */
import { refreshAll, requestData } from "./data.js";
import { setActive, toggleMaximize } from "./grid.js";
import { openCellMenu } from "./saved.js";
import { app, save } from "./state.js";
import { api, btn, el, fmtValue, inUse, uid } from "./util.js";

export const COLUMNS = [
  ["symbol", "Symbol"], ["last", "Last"], ["change", "Chg"], ["pct", "Chg %"], ["volume", "Volume"],
  ["high", "High"], ["low", "Low"],
];
const MAX_SYMBOLS = 100;
const DEMO_RE = /-DEMO$/;

// large values (e.g. NYSE up - down volume) shortened like the charts' axes: 25.04M
const num = (x) => (x == null ? "–" : Math.abs(x) >= 1e6 ? fmtValue(x) : x.toFixed(2));
const signed = (x) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + num(Math.abs(x)));

export class WatchList {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.symbols = Array.isArray(cfg.symbols) ? cfg.symbols.slice(0, MAX_SYMBOLS) : [];
    this.list = cfg.list || "";                 // a saved watch list's name, or "" for its own list
    this.link = cfg.link || "active";           // "active", or a chart's id
    this.rows = []; this.selected = null; this.seq = 0;
    this.buildDom();
  }

  config() { return { kind: "watchlist", id: this.id, symbols: this.symbols, list: this.list, link: this.link }; }
  destroy() { this.dead = true; this.root.remove(); }
  shown() { return this.list ? (app.saved.watchlists[this.list] || []) : this.symbols; }
  chart() {
    return (this.link !== "active" && app.panels.find((p) => p.id === this.link)) || app.active || app.panels[0] || null;
  }

  buildDom() {
    const root = this.root = el("section", "panel wl");
    root.dataset.cell = "watchlist";
    const head = el("div", "phead");
    head.appendChild(el("b", "wltitle", "Watch list"));
    this.listSel = el("select", "wllist"); this.listSel.setAttribute("aria-label", "List");
    this.listSel.title = "Its own list, or a watch list saved under Load data…";
    this.listSel.onchange = () => { this.list = this.listSel.value; save(); this.render(); this.refresh(); };
    const editB = btn("Edit", () => this.edit(), "Edit the symbols", "wledit");
    const linkL = el("label", "wllinkl", "Chart ");
    this.linkSel = el("select", "wllink"); this.linkSel.setAttribute("aria-label", "Linked chart");
    this.linkSel.title = "The chart a click on a row changes";
    this.linkSel.onchange = () => { this.link = this.linkSel.value; save(); this.render(); };
    linkL.appendChild(this.linkSel);
    const menuB = btn("\u2261", (e) => openCellMenu(e.currentTarget, this), "Watch list menu", "viewsbtn");
    menuB.title = "Add a chart or watch list next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this watch list", "maxbtn");
    head.append(this.listSel, editB, linkL, el("span", "wlgrow"), menuB, this.maxBtn);

    this.editor = el("form", "wleditor"); this.editor.hidden = true;
    this.text = el("textarea"); this.text.rows = 4; this.text.setAttribute("aria-label", "Symbols");
    this.text.placeholder = "Symbols separated by spaces, commas or lines (a thinkorswim share link works too)";
    const ok = el("button", "primary", "Apply"); ok.type = "submit";
    const cancel = btn("Cancel", () => { this.editor.hidden = true; });
    this.editMsg = el("span", "muted small");
    const row = el("div", "wlrow"); row.append(ok, cancel, this.editMsg);
    this.editor.append(this.text, row);
    this.editor.onsubmit = (e) => { e.preventDefault(); this.applyEdit(); };

    this.body = el("div", "wlbody");
    this.body.tabIndex = 0;
    this.body.setAttribute("aria-label", "Watch list: arrow keys move through it and change the linked chart");
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

  // the menus and the table from what's known now (no fetch)
  render() {
    if (!inUse(this.listSel)) {
      this.listSel.innerHTML = "";
      const own = el("option", null, "Own list"); own.value = ""; this.listSel.appendChild(own);
      for (const n of Object.keys(app.saved.watchlists || {}).sort()) { const o = el("option", null, n); o.value = n; this.listSel.appendChild(o); }
      if (this.list && !app.saved.watchlists?.[this.list]) { const o = el("option", null, `${this.list} (deleted)`); o.value = this.list; this.listSel.appendChild(o); }
      this.listSel.value = this.list;
    }
    if (!inUse(this.linkSel)) {
      this.linkSel.innerHTML = "";
      const act = el("option", null, "Active chart"); act.value = "active"; this.linkSel.appendChild(act);
      app.panels.forEach((p, i) => { const o = el("option", null, `${i + 1}: ${p.symbol} ${p.tfSel?.selectedOptions[0]?.text || ""}`.trim()); o.value = p.id; this.linkSel.appendChild(o); });
      if (this.link !== "active" && !app.panels.some((p) => p.id === this.link)) this.link = "active";
      this.linkSel.value = this.link;
    }
    this.selected = this.chart()?.symbol || null;
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
      tr.title = `Show ${sym} on the ${this.link === "active" ? "active" : "linked"} chart`;
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
    const missing = this.rows.filter((r) => r.status === "missing" && !DEMO_RE.test(r.symbol)).map((r) => r.symbol);
    this.foot.innerHTML = "";
    const n = this.shown().length;
    this.foot.appendChild(el("span", null, n ? `${n} symbol${n === 1 ? "" : "s"}, ${app.live ? "live" : app.day || ""}` : "No symbols: press Edit."));
    if (missing.length) {
      const b = btn(`Fetch ${missing.length} from TWS`, () => { requestData(missing); b.disabled = true; b.textContent = "Asked TWS…"; },
                    null, "wlfetch");
      b.title = missing.join(" ");
      this.foot.appendChild(b);
    }
  }

  async refresh() {
    if (this.dead) return;
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
    const chart = this.chart();
    if (!chart) return;
    this.selected = sym;
    setActive(chart);
    chart.setSymbol(sym);
    this.render();
  }

  edit() {
    this.editor.hidden = !this.editor.hidden;
    if (this.editor.hidden) return;
    this.text.value = this.shown().join(" ");
    this.editMsg.textContent = this.list ? `Editing a copy: saved list "${this.list}" stays as it is.` : "";
    this.text.focus();
  }

  async applyEdit() {
    let r;
    try { r = await api("/api/symbols/parse", { text: this.text.value }); } catch (e) { this.editMsg.textContent = e.message; return; }
    this.symbols = r.symbols.slice(0, MAX_SYMBOLS);
    this.list = "";
    this.editMsg.textContent = r.skipped?.length ? `Skipped: ${r.skipped.join(" ")}` : "";
    if (!r.skipped?.length) this.editor.hidden = true;
    save(); this.render();
    await this.refresh();
    refreshAll();
  }
}
