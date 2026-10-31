/* A watch list cell in the grid: tabs of symbols with chosen columns, from the cached 1-minute bars of the day
   on screen, up to the Replay cursor. Clicking a row, or moving through the list with the arrow keys, shows that
   symbol on every chart of the watch list's link group (links.js), or on the active chart when it isn't linked.
   Each tab (watch-tab.js) has its own source (own list, saved list, FinViz, the account's holdings) and columns
   (columns.js); only the tab on view fetches. */
import { refreshAll, requestData } from "./data.js";
import { COLUMNS, DEFAULTS, available, cellText } from "./columns.js";
import { setActive, toggleMaximize } from "./grid.js";
import { groupOf, linkControl, members, publish } from "./links.js";
import { toastAction } from "./notify.js";
import { openCellMenu } from "./saved.js";
import { app, save } from "./state.js";
import { api, btn, el, inUse, uid } from "./util.js";
import { FEED, HOLDINGS, MAX_SYMBOLS, WatchTab, legacyTab, newTabConfig } from "./watch-tab.js";

export { MAX_SYMBOLS };
export const MAX_TABS = 12;
const DEMO_RE = /-DEMO$/;

export class WatchList {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.link = cfg.link || "";                 // link group (links.js); "" drives the active chart
    const tabs = Array.isArray(cfg.tabs) && cfg.tabs.length ? cfg.tabs : [legacyTab(cfg)];
    this.tabs = tabs.slice(0, MAX_TABS).map((t) => this.makeTab(t));
    this.at = Math.min(Math.max(0, cfg.tab | 0), this.tabs.length - 1);
    this.selected = null;
    this.buildDom();
    this.tab().start();
  }

  makeTab(cfg) {
    const t = new WatchTab(cfg, () => { if (t === this.tab()) { this.render(); this.refresh(); } });
    return t;
  }
  tab() { return this.tabs[this.at]; }

  config() { return { kind: "watchlist", id: this.id, link: this.link, tab: this.at, tabs: this.tabs.map((t) => t.config()) }; }
  destroy() { this.dead = true; this.tabs.forEach((t) => t.stop()); this.root.remove(); }
  shown() { return this.tab().shown(); }

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
    this.listSel.title = "This tab's symbols: its own list, a watch list saved under Load data…, a FinViz screen or portfolio, or your holdings";
    this.listSel.onchange = () => {
      const t = this.tab(), v = this.listSel.value;
      if (v === FEED && !t.feed.address) { this.listSel.value = t.list; this.edit(FEED); return; }
      t.list = v; t.rows = []; t.held = null;
      save(); this.render();
      if (v === FEED) t.start(); else t.stop();
      this.refresh();
    };
    const editB = btn("Edit", () => this.edit(this.tab().list === FEED ? FEED : ""), "Edit this tab's symbols", "wledit");
    const colB = btn("Columns", () => this.toggleColumns(), "Choose this tab's columns", "wlcolbtn");
    const linkB = linkControl(this, () => this.render());
    const menuB = btn("≡", (e) => openCellMenu(e.currentTarget, this), "Watch list menu", "viewsbtn");
    menuB.title = "Add a chart or watch list next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this watch list", "maxbtn");
    head.append(this.listSel, linkB, editB, colB, el("span", "wlgrow"), menuB, this.maxBtn);

    this.tabBar = el("div", "wltabs");
    this.tabBar.setAttribute("role", "tablist");

    this.colBox = el("div", "wlcols"); this.colBox.hidden = true;

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
    root.append(head, this.tabBar, this.colBox, this.editor, this.body, this.foot);
    this.render();
  }

  // ---------------------------------------------------------------- tabs
  renderTabs() {
    if (this.tabBar.querySelector("input")) return;                  // a tab being renamed
    this.tabBar.innerHTML = "";
    this.tabs.forEach((t, i) => {
      const b = btn(t.label(), () => this.showTab(i), null, "wltab" + (i === this.at ? " on" : ""));
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", i === this.at ? "true" : "false");
      b.title = i === this.at ? "Double-click to rename" : `Show ${t.label()}`;
      b.ondblclick = () => this.rename(i, b);
      this.tabBar.appendChild(b);
      if (i === this.at && this.tabs.length > 1) {
        const x = btn("×", () => this.closeTab(i), `Close the ${t.label()} tab`, "wltabx");
        this.tabBar.appendChild(x);
      }
    });
    if (this.tabs.length < MAX_TABS) {
      const add = btn("+", () => this.addTab(), "Add a tab", "wltabadd");
      this.tabBar.appendChild(add);
    }
  }

  showTab(i) {
    if (i === this.at) return;
    this.tab().stop();
    this.at = i; this.editor.hidden = true; this.colBox.hidden = true;
    save(); this.render();
    this.tab().start();
    this.refresh();
  }

  addTab() {
    this.tabs.push(this.makeTab(newTabConfig()));
    this.showTab(this.tabs.length - 1);
    this.edit("");                                                  // its own list: type the symbols
  }

  closeTab(i) {
    const before = this.config();
    this.tabs[i].stop();
    this.tabs.splice(i, 1);
    this.at = Math.min(this.at, this.tabs.length - 1);
    save(); this.render(); this.tab().start(); this.refresh();
    toastAction(`Tab "${before.tabs[i].name || this.labelOf(before.tabs[i])}" closed.`, "Undo", () => {
      if (this.dead) return;
      this.tabs.forEach((t) => t.stop());
      this.tabs = before.tabs.map((t) => this.makeTab(t));
      this.at = before.tab;
      save(); this.render(); this.tab().start(); this.refresh();
    });
  }

  labelOf(cfg) { return new WatchTab(cfg, () => {}).label(); }

  rename(i, b) {
    const t = this.tabs[i];
    const input = el("input", "wltabname");
    Object.assign(input, { value: t.label(), maxLength: 24, spellcheck: false });
    input.setAttribute("aria-label", "Tab name");
    let done = false;
    const finish = (keep) => {
      if (done) return;
      done = true;
      if (keep) { const v = input.value.trim(); t.name = v === t.label() && !t.name ? "" : v; save(); }
      input.remove(); this.renderTabs();
    };
    input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); };
    input.onblur = () => finish(true);
    b.replaceWith(input);
    input.focus(); input.select();
  }

  // ---------------------------------------------------------------- columns
  toggleColumns() {
    this.colBox.hidden = !this.colBox.hidden;
    if (this.colBox.hidden) return;
    this.editor.hidden = true;
    const t = this.tab(), shown = t.shownColumns();
    this.colBox.innerHTML = "";
    for (const id of available(t.kind()).filter((c) => c !== "symbol")) {
      const l = el("label", "wlcol");
      const cb = el("input"); cb.type = "checkbox"; cb.checked = shown.includes(id); cb.value = id;
      cb.onchange = () => {
        const now = t.shownColumns().filter((c) => c !== "symbol");
        const next = cb.checked ? available(t.kind()).filter((c) => c === id || now.includes(c)) : now.filter((c) => c !== id);
        t.columns = next.length ? next : null;
        save(); this.render();
      };
      l.append(cb, document.createTextNode(" " + COLUMNS[id].label));
      if (COLUMNS[id].tip) l.title = COLUMNS[id].tip;
      this.colBox.appendChild(l);
    }
    const reset = btn("Defaults", () => { t.columns = null; save(); this.colBox.hidden = true; this.toggleColumns(); this.render(); },
                      `Show the default columns: ${DEFAULTS[t.kind()].map((c) => COLUMNS[c].label).join(", ")}`, "wlcolreset");
    this.colBox.appendChild(reset);
  }

  // ---------------------------------------------------------------- the table
  // the menus, tabs and table from what's known now (no fetch)
  render() {
    if (this.dead) return;
    const t = this.tab();
    this.renderTabs();
    if (!inUse(this.listSel)) {
      this.listSel.innerHTML = "";
      const add = (v, txt) => { const o = el("option", null, txt); o.value = v; this.listSel.appendChild(o); };
      add("", "Own list");
      for (const n of Object.keys(app.saved.watchlists || {}).sort()) add(n, n);
      if (t.list && t.list !== FEED && t.list !== HOLDINGS && !app.saved.watchlists?.[t.list]) add(t.list, `${t.list} (deleted)`);
      add(FEED, t.feed.address ? "FinViz" : "FinViz screen or portfolio…");
      add(HOLDINGS, "Holdings (IBKR)");
      this.listSel.value = t.list;
    }
    const charts = this.charts();
    if (charts.length) this.selected = charts[0].symbol;
    const target = this.link ? `the ${groupOf(this.link).name.toLowerCase()} linked charts` : "the active chart";
    const cols = t.shownColumns();
    const tb = this.table;
    tb.innerHTML = "";
    const h = el("tr");
    for (const id of cols) { const th = el("th", null, COLUMNS[id].label); if (COLUMNS[id].tip) th.title = COLUMNS[id].tip; h.appendChild(th); }
    tb.appendChild(h);
    const byS = Object.fromEntries(t.rows.map((r) => [r.symbol, r]));
    for (const sym of this.shown()) {
      const r = byS[sym] || { symbol: sym };
      const tr = el("tr", "wlr" + (sym === this.selected ? " sel" : ""));
      tr.dataset.symbol = sym;
      tr.title = `Show ${sym} on ${target}`;
      tr.onclick = () => this.pick(sym);
      tr.append(el("td", "wlsym", sym));
      const quoteCols = cols.filter((id) => id !== "symbol");
      if (r.status === "ok" || (t.kind() === "holding" && r.qty != null)) {
        for (const id of quoteCols) {
          const [txt, dir] = r.status === "ok" || COLUMNS[id].has === "holding" ? cellText(id, r) : ["–", ""];
          tr.appendChild(el("td", dir ? `wlchg ${dir}` : null, txt));
        }
      } else {
        const td = el("td", "muted", r.status === "missing" ? "not cached for this day" : r.status === "none yet" ? "no bars yet" : "");
        td.colSpan = quoteCols.length;
        tr.appendChild(td);
      }
      tb.appendChild(tr);
    }
    this.renderFoot();
  }

  renderFoot() {
    const t = this.tab();
    const missing = t.rows.filter((r) => r.status === "missing" && !DEMO_RE.test(r.symbol)).map((r) => r.symbol);
    this.foot.innerHTML = "";
    const st = t.status();
    if (st) this.foot.appendChild(st);
    const n = this.shown().length, empty = t.emptyText();
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
    const t = this.tab();
    try {
      if (!(await t.fetchRows()) || this.dead || t !== this.tab()) return;
    } catch (e) { this.foot.textContent = "Error: " + e.message; return; }
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

  // ---------------------------------------------------------------- editing a tab's symbols
  edit(mode) {
    this.editor.hidden = !this.editor.hidden && this.editMode === mode;     // the same button again closes it
    this.editMode = mode;
    if (this.editor.hidden) return;
    this.colBox.hidden = true;
    const t = this.tab();
    if (mode === FEED) {
      this.text.setAttribute("aria-label", "FinViz address");
      this.text.placeholder = "The address of a FinViz screen or portfolio, e.g. https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers";
      this.text.value = t.feed.address || "";
      this.editMsg.textContent = "Copy it from your browser's address bar on finviz.com. Needs FinViz Elite (FINVIZ_TOKEN in .env).";
    } else {
      this.text.setAttribute("aria-label", "Symbols");
      this.text.placeholder = "Symbols separated by spaces, commas or lines (a thinkorswim share link works too)";
      this.text.value = this.shown().join(" ");
      this.editMsg.textContent = t.list ? `Editing a copy: "${t.label()}" stays as it is.` : "";
    }
    this.text.focus();
  }

  async applyEdit() {
    const t = this.tab();
    if (this.editMode === FEED) {
      const before = t.list;
      t.list = FEED;                                      // so the new symbols' rows are asked for as they arrive
      const err = await t.feed.set(this.text.value);
      if (err) { t.list = before; this.editMsg.textContent = err; return; }
      this.editor.hidden = true;
      save(); this.render(); this.refresh();
      return;
    }
    let r;
    try { r = await api("/api/symbols/parse", { text: this.text.value }); } catch (e) { this.editMsg.textContent = e.message; return; }
    t.symbols = r.symbols.slice(0, MAX_SYMBOLS);
    t.list = ""; t.stop();
    this.editMsg.textContent = r.skipped?.length ? `Skipped: ${r.skipped.join(" ")}` : "";
    if (!r.skipped?.length) this.editor.hidden = true;
    save(); this.render();
    await this.refresh();
    refreshAll();
  }
}
