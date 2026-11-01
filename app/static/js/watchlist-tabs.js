/* A watch list panel's tabs and its list menu (mixed into WatchList): show, add, close (with Undo) and rename
   tabs; pick, make or delete the named list a tab shows. A rename is a move, app-wide: every tab showing the list
   follows it. */
import * as lists from "./lists.js";
import { toast, toastAction } from "./notify.js";
import { app, save } from "./state.js";
import { btn, el, inUse, morph } from "./util.js";
import { tabConfig } from "./watch-tab.js";

export const MAX_TABS = 12;
// the list menu's entries besides the named lists
const NEW_SYMBOLS = "@new", NEW_FINVIZ = "@new-finviz", NEW_HOLDINGS = "@new-holdings", DELETE = "@delete";

export class WatchListTabs {
  renderTabs() {
    if (this.tabBar.querySelector("input")) return;                  // a tab being renamed
    const bar = el("div");                                           // drawn fresh, moved onto the live bar (morph)
    this.tabs.forEach((t, i) => {
      const b = btn(t.label(), () => this.showTab(i), null, "wltab" + (i === this.at ? " on" : ""));
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", i === this.at ? "true" : "false");
      b.title = i === this.at ? "Double-click to rename" : `Show ${t.label()}`;
      b.dataset.key = t.id;
      b.ondblclick = (e) => this.rename(i, e.currentTarget);
      bar.appendChild(b);
      if (i === this.at && this.tabs.length > 1) {
        const x = btn("×", () => this.closeTab(i), `Close the ${t.label()} tab`, "wltabx");
        bar.appendChild(x);
      }
    });
    if (this.tabs.length < MAX_TABS) {
      const add = btn("+", () => this.addTab(), "Add a tab", "wltabadd");
      bar.appendChild(add);
    }
    morph(this.tabBar, bar);
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

  // the list menu: every named list, the tab's own when it has none or it was deleted, and the actions
  renderListMenu() {
    const t = this.tab();
    if (inUse(this.listSel)) return;
    this.listSel.innerHTML = "";
    const add = (v, txt) => { const o = el("option", null, txt); o.value = v; this.listSel.appendChild(o); };
    for (const n of lists.names()) add(n, n);
    if (!t.item) add(t.list, !t.list ? "Pick a watch list…" : app.listsUnknown ? t.list : `${t.list} (deleted)`);
    add(NEW_SYMBOLS, "New watch list…");
    add(NEW_FINVIZ, "New FinViz screen or portfolio…");
    add(NEW_HOLDINGS, "New Holdings list (IBKR)");
    if (t.item) add(DELETE, `Delete "${t.list}"…`);
    this.listSel.value = t.list;
  }
}
