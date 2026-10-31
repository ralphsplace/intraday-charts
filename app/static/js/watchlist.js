/* A watch list cell in the grid: tabs of symbols with chosen columns, from the cached 1-minute bars of the day
   on screen, up to the Replay cursor. Clicking a row, or moving through the list with the arrow keys, shows that
   symbol on every chart of the watch list's link group (links.js), or on the active chart when it isn't linked.
   Each tab (watch-tab.js) shows one of the app's named watch lists (lists.js; its symbols typed, from FinViz, or
   the account's holdings) with its own columns (columns.js); only the tab on view fetches. */
import { refreshAll, requestData } from "./data.js";
import { COLUMNS, DEFAULTS, SECTIONS, available, renderCell, sectionOf } from "./columns.js";
import { setActive, toggleMaximize } from "./grid.js";
import { groupOf, linkControl, members, publish } from "./links.js";
import * as lists from "./lists.js";
import { toast, toastAction } from "./notify.js";
import { openCellMenu } from "./saved.js";
import { app, save } from "./state.js";
import { api, btn, el, inUse, keepScroll, uid } from "./util.js";
import { MAX_SYMBOLS, WatchTab, legacyTab, tabConfig } from "./watch-tab.js";

export { MAX_SYMBOLS };
export const MAX_TABS = 12;
const DEMO_RE = /-DEMO$/;
// the list menu's entries besides the named lists
const NEW_SYMBOLS = "@new", NEW_FINVIZ = "@new-finviz", NEW_HOLDINGS = "@new-holdings", DELETE = "@delete";

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
    this.migrate();
  }

  // tabs saved before watch lists were named and app-wide get a named list each (once)
  async migrate() {
    const old = this.tabs.filter((t) => t.legacy);
    if (!old.length) return;
    for (const t of old) await t.migrate();
    if (this.dead) return;
    save(); this.render(); this.tab().start(); this.refresh();
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

  // delete the tab's list everywhere (asked first, on the message); the tab moves to another list or a new one
  deleteList() {
    const t = this.tab(), name = t.list;
    toastAction(`Delete the watch list "${name}" everywhere (every dashboard and tab)?`, "Delete", async () => {
      try { await lists.remove(name); } catch (e) { toast(e.message, true); return; }
      for (const c of app.cells) if (c.tabs) c.render();                 // every watch list panel
      toast(`Deleted "${name}". Its tabs say so: pick another list in their menu, or close them.`);
    });
  }

  // a new tab with a new, empty "Watch list N" (app-wide), its editor open to type the symbols
  async addTab() {
    let r;
    try { r = await lists.create("symbols", { symbols: [] }); } catch (e) { toast(e.message, true); return; }
    this.tabs.push(this.makeTab(tabConfig(r.name, r.item.id)));
    this.showTab(this.tabs.length - 1);
    this.edit("symbols");
  }

  // the list menu: show another named list in this tab, or make a new one
  async pickList(v) {
    const t = this.tab();
    this.listSel.blur();
    if (v === NEW_SYMBOLS || v === NEW_HOLDINGS) {
      let r;
      try { r = await lists.create(v === NEW_HOLDINGS ? "holdings" : "symbols", v === NEW_HOLDINGS ? {} : { symbols: [] }); }
      catch (e) { toast(e.message, true); this.render(); return; }
      v = r.name;
    }
    if (v === NEW_FINVIZ) { this.render(); this.edit("finviz", true); return; }
    if (v === DELETE) { this.render(); this.deleteList(); return; }
    t.stop();
    const [name, item] = lists.find(null, v);
    t.list = name; t.listId = item?.id || null; t.rows = []; t.held = null; t.resolve();
    save(); this.render(); t.start(); this.refresh();
    if (item?.source === "symbols" && !item.symbols.length) this.edit("symbols");
  }

  closeTab(i) {
    const before = this.config();
    this.tabs[i].stop();
    this.tabs.splice(i, 1);
    this.at = Math.min(this.at, this.tabs.length - 1);
    save(); this.render(); this.tab().start(); this.refresh();
    toastAction(`Tab "${before.tabs[i].list}" closed (the watch list itself is kept).`, "Undo", () => {
      if (this.dead) return;
      this.tabs.forEach((t) => t.stop());
      this.tabs = before.tabs.map((t) => this.makeTab(t));
      this.at = before.tab;
      save(); this.render(); this.tab().start(); this.refresh();
    });
  }

  rename(i, b) {
    const t = this.tabs[i];
    const input = el("input", "wltabname");
    Object.assign(input, { value: t.label(), maxLength: 60, spellcheck: false });
    input.setAttribute("aria-label", "Watch list name");
    let done = false;
    const finish = async (keep) => {
      if (done) return;
      done = true;
      const v = input.value.trim();
      if (keep && v && v !== t.list && t.item && lists.names().includes(v)) {
        toast(`There is already a watch list called "${v}": names are unique across the app.`, true);
      } else if (keep && v && v !== t.list && t.item) {
        try {
          const old = t.list, r = await lists.rename(old, v);     // a move: same id, new name, app-wide
          for (const c of app.cells) {
            for (const x of c.tabs || []) {
              if (x.listId === r.item.id || x.list === old) { x.list = r.name; x.listId = r.item.id; x.resolve(); }
            }
          }
          save();
        } catch (e) { toast(e.message, true); }
      }
      input.remove(); this.renderTabs(); this.render();
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
    const boxes = {};                                    // one row per section, in the sections' order
    for (const [, name] of SECTIONS) if (!boxes[name]) boxes[name] = null;
    for (const id of available(t.kind()).filter((c) => c !== "symbol")) {
      const c = COLUMNS[id], section = sectionOf(c);
      if (!boxes[section]) {
        const sec = el("div", "wlcolsec");
        sec.appendChild(el("b", null, section));
        boxes[section] = el("div", "wlcolrow");
        sec.appendChild(boxes[section]);
        sec.dataset.order = String(SECTIONS.findIndex(([, n]) => n === section));
        const after = [...this.colBox.children].find((x) => +x.dataset.order > +sec.dataset.order);
        this.colBox.insertBefore(sec, after || null);
      }
      const box = boxes[section];
      const l = el("label", "wlcol");
      const cb = el("input"); cb.type = "checkbox"; cb.checked = shown.includes(id); cb.value = id;
      cb.onchange = () => {
        const now = t.shownColumns().filter((x) => x !== "symbol");
        const next = cb.checked ? available(t.kind()).filter((x) => x === id || now.includes(x)) : now.filter((x) => x !== id);
        t.columns = next.length ? next : null;
        save(); this.render(); this.refresh();                        // new columns may need values the rows lack
      };
      l.append(cb, document.createTextNode(" " + c.label));
      if (c.tip) l.title = c.tip;
      box.appendChild(l);
      if (c.heat) {
        const h = el("label", "wlheat");
        const hb = el("input"); hb.type = "checkbox"; hb.checked = t.heat.includes(id);
        hb.setAttribute("aria-label", `Shade ${c.label} by value`);
        hb.onchange = () => { t.heat = hb.checked ? [...t.heat, id] : t.heat.filter((x) => x !== id); save(); this.render(); };
        h.append(hb, document.createTextNode("heat"));
        h.title = `Shade ${c.label}'s cells by value: deeper green or red the further from ${c.kind === "ratio" ? "1×" : "0"}`;
        box.appendChild(h);
      }
    }
    const reset = btn("Defaults", () => { t.columns = null; save(); this.colBox.hidden = true; this.toggleColumns(); this.render(); },
                      `Show the default columns: ${DEFAULTS[t.kind()].map((c) => COLUMNS[c].label).join(", ")}`, "wlcolreset");
    this.colBox.appendChild(reset);
  }

  // ---------------------------------------------------------------- the table
  // the menus, tabs and table from what's known now (no fetch)
  render() { if (!this.dead) keepScroll(this.body, () => this.renderNow()); }

  renderNow() {
    const t = this.tab();
    t.resolve();
    this.renderTabs();
    this.editB.disabled = !t.item || t.source() === "holdings";
    if (!inUse(this.listSel)) {
      this.listSel.innerHTML = "";
      const add = (v, txt) => { const o = el("option", null, txt); o.value = v; this.listSel.appendChild(o); };
      for (const n of lists.names()) add(n, n);
      if (!t.item) add(t.list, `${t.list} (deleted)`);
      add(NEW_SYMBOLS, "New watch list…");
      add(NEW_FINVIZ, "New FinViz screen or portfolio…");
      add(NEW_HOLDINGS, "New Holdings list (IBKR)");
      if (t.item) add(DELETE, `Delete "${t.list}"…`);
      this.listSel.value = t.list;
    }
    const charts = this.charts();
    if (charts.length) this.selected = charts[0].symbol;
    const target = this.link ? `the ${groupOf(this.link).name.toLowerCase()} linked charts` : "the active chart";
    const cols = t.shownColumns();
    const tb = this.table;
    tb.innerHTML = "";
    const h = el("tr");
    for (const id of cols) {
      const c = COLUMNS[id] || { label: id };
      const on = t.sort?.id === id;
      const th = el("th", "wlsort" + (on ? " on" : ""), c.label + (on ? (t.sort.dir === 1 ? " \u25b4" : " \u25be") : ""));
      th.title = (c.tip ? c.tip + ". " : "") + "Click to sort: up, down, then the list's own order";
      th.setAttribute("aria-sort", on ? (t.sort.dir === 1 ? "ascending" : "descending") : "none");
      th.onclick = () => { t.toggleSort(id); save(); this.render(); };
      if (id !== "symbol") {                               // drag a header onto another to move it there
        th.draggable = true;
        th.title += ". Drag to move the column";
        th.ondragstart = (e) => { e.dataTransfer.setData("text/x-wlcol", id); e.dataTransfer.effectAllowed = "move"; };
      }
      th.ondragover = (e) => { if (e.dataTransfer.types.includes("text/x-wlcol")) { e.preventDefault(); th.classList.add("dropto"); } };
      th.ondragleave = () => th.classList.remove("dropto");
      th.ondrop = (e) => {
        e.preventDefault(); th.classList.remove("dropto");
        const from = e.dataTransfer.getData("text/x-wlcol");
        if (from && from !== id) { t.moveColumn(from, id); save(); this.render(); }
      };
      h.appendChild(th);
    }
    tb.appendChild(h);
    const colMax = {};
    for (const id of cols) colMax[id] = Math.max(0, ...t.rows.map((r) => (typeof r[id] === "number" ? Math.abs(r[id]) : 0)));
    const byS = Object.fromEntries(t.rows.map((r) => [r.symbol, r]));
    for (const sym of this.shown()) {
      const r = byS[sym] || { symbol: sym };
      const tr = el("tr", "wlr" + (sym === this.selected ? " sel" : ""));
      tr.dataset.symbol = sym;
      tr.title = `Show ${sym} on ${target}`;
      tr.onclick = () => this.pick(sym);
      tr.append(el("td", "wlsym", sym));
      const quoteCols = cols.filter((id) => id !== "symbol");
      const own = (id) => COLUMNS[id]?.lists === "holding" || COLUMNS[id]?.lists === "finviz";     // not from the bars
      if (r.status === "ok" || (t.kind() === "holding" && r.qty != null)) {
        for (const id of quoteCols) {
          const td = el("td");
          if (r.status !== "ok" && !own(id)) { td.textContent = "–"; tr.appendChild(td); continue; }
          const v = renderCell(id, r, { colMax, heat: t.heat.includes(id) });
          if (v.node) td.appendChild(v.node); else td.textContent = v.text ?? "–";
          if (v.cls) td.className = v.cls.split(" ").some((x) => x === "up" || x === "down") ? `wlchg ${v.cls}` : v.cls;
          if (v.style) td.style.cssText = v.style;
          if (v.title) td.title = v.title;
          if (COLUMNS[id]?.kind === "text" || COLUMNS[id]?.kind === "state" || COLUMNS[id]?.kind === "date") td.classList.add("wltext");
          tr.appendChild(td);
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

  // ---------------------------------------------------------------- editing a watch list
  // mode "symbols" or "finviz"; fresh: a new FinViz list is being made (the tab's list stays as it is)
  edit(mode, fresh = false) {
    this.editor.hidden = !this.editor.hidden && this.editMode === mode && !fresh;   // the same button again closes it
    this.editMode = mode; this.fresh = fresh;
    if (this.editor.hidden) return;
    this.colBox.hidden = true;
    const t = this.tab();
    if (mode === "finviz") {
      this.text.setAttribute("aria-label", "FinViz address");
      this.text.placeholder = "The address of a FinViz screen or portfolio, e.g. https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o2000,ta_topgainers";
      this.text.value = fresh ? "" : t.feed.address || "";
      this.editMsg.textContent = "Copy it from your browser's address bar on finviz.com. Needs FinViz Elite (FINVIZ_TOKEN in .env).";
    } else {
      this.text.setAttribute("aria-label", "Symbols");
      this.text.placeholder = "Symbols separated by spaces, commas or lines, or the contents of an exported watch list file";
      this.text.value = this.tab().listed().join(" ");
      this.editMsg.textContent = `Changes "${t.label()}" everywhere it's shown.`;
    }
    this.text.focus();
  }

  async applyEdit() {
    const t = this.tab();
    if (this.editMode === "finviz") {
      const probe = new WatchTab({}, () => {}).feed;                  // checks the address and asks the collector
      const err = await probe.set(this.text.value);
      if (err) { this.editMsg.textContent = err; return; }
      try {
        if (this.fresh) {
          const r = await lists.create("finviz", { feed: probe.config() });
          t.stop(); t.list = r.name; t.listId = r.item.id;
        } else {
          await lists.update(t.list, "finviz", { feed: probe.config() });
        }
      } catch (e) { this.editMsg.textContent = e.message; return; }
      this.editor.hidden = true;
      probe.stop();
      t.resolve(); t.feed.symbols = probe.symbols; t.feed.fields = probe.fields; t.feed.view = probe.view;
      if (probe.view?.requested) t.feed.wait(probe.view);
      save(); this.render(); t.start(); this.refresh();
      return;
    }
    let r;
    try { r = await api("/api/symbols/parse", { text: this.text.value }); } catch (e) { this.editMsg.textContent = e.message; return; }
    const skipped = r.skipped?.length ? `Skipped: ${r.skipped.join(" ")}` : "";
    if (r.note && !r.symbols.length) { this.editMsg.textContent = r.note; return; }        // e.g. a thinkorswim link
    try { await lists.update(t.list, "symbols", { symbols: r.symbols.slice(0, 500) }); } catch (e) { this.editMsg.textContent = e.message; return; }
    for (const c of app.cells) for (const x of c.tabs || []) if (x.listId === t.listId) x.resolve();
    this.editMsg.textContent = [skipped, r.note || ""].filter(Boolean).join(" ");
    if (!skipped && !r.note) this.editor.hidden = true;
    save(); this.render();
    await this.refresh();
    refreshAll();
  }
}
