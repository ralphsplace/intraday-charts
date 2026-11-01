/* A watch list cell in the grid: tabs of symbols with chosen columns, from the cached 1-minute bars of the day
   on screen, up to the Replay cursor. Clicking a row, or moving through the list with the arrow keys, shows that
   symbol on every chart of the watch list's link group (links.js), or on the active chart when it isn't linked.
   Each tab (watch-tab.js) shows one of the app's named watch lists (lists.js; its symbols typed, from FinViz, or
   the account's holdings) with its own columns (columns.js); only the tab on view fetches. */
import { setActive, toggleMaximize } from "./grid.js";
import { linkControl, members, publish } from "./links.js";
import { openCellMenu } from "./saved.js";
import { app } from "./state.js";
import { btn, el, mixParts, uid } from "./util.js";
import { MAX_SYMBOLS, WatchTab, tabConfig } from "./watch-tab.js";
import { WatchListColumns } from "./watchlist-columns.js";
import { WatchListEditor } from "./watchlist-editor.js";
import { WatchListTable } from "./watchlist-table.js";
import { MAX_TABS, WatchListTabs } from "./watchlist-tabs.js";

export { MAX_SYMBOLS, MAX_TABS };

// one panel: its tabs and link group, and the parts that draw and change it (tabs, columns, table, editor)
export class WatchList {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.link = cfg.link || "";                 // link group (links.js); "" drives the active chart
    const tabs = Array.isArray(cfg.tabs) && cfg.tabs.length ? cfg.tabs : [tabConfig("", null)];     // no list yet: pick one
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
    this.listSel.title = "The watch list this tab shows (app-wide, kept on the NAS), or a new one";
    this.listSel.onchange = () => this.pickList(this.listSel.value);
    this.editB = btn("Edit", () => this.edit(this.tab().source() === "finviz" ? "finviz" : "symbols"), "Edit this watch list", "wledit");
    const editB = this.editB;
    const colB = btn("Columns", () => this.toggleColumns(), "Choose this tab's columns", "wlcolbtn");
    const linkB = linkControl(this, () => this.render());
    const menuB = btn("≡", (e) => openCellMenu(e.currentTarget, this), "Watch list menu", "viewsbtn");
    menuB.title = "Add a chart or watch list next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this watch list", "maxbtn");
    head.append(this.listSel, linkB, editB, colB, el("span", "wlgrow"), menuB, this.maxBtn);

    this.tabBar = el("div", "wltabs");
    this.tabBar.setAttribute("role", "tablist");

    this.colBox = el("div", "wlcols"); this.colBox.hidden = true;
    this.buildEditor();

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
}

mixParts(WatchList, WatchListTabs, WatchListColumns, WatchListTable, WatchListEditor);
