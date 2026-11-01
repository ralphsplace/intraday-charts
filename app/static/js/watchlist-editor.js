/* A watch list panel's editor (mixed into WatchList): type or paste the symbols of a list, or the address of a
   FinViz screen or portfolio, new or changed. Changes are app-wide: every tab showing the list follows. */
import { refreshAll } from "./data.js";
import * as lists from "./lists.js";
import { app, save } from "./state.js";
import { api, btn, el } from "./util.js";
import { WatchTab } from "./watch-tab.js";

export class WatchListEditor {
  buildEditor() {
      this.editor = el("form", "wleditor"); this.editor.hidden = true;
      this.text = el("textarea"); this.text.rows = 4; this.text.setAttribute("aria-label", "Symbols");
      const ok = el("button", "primary", "Apply"); ok.type = "submit";
      const cancel = btn("Cancel", () => { this.editor.hidden = true; });
      this.editMsg = el("span", "muted small");
      const row = el("div", "wlrow"); row.append(ok, cancel, this.editMsg);
      this.editor.append(this.text, row);
      this.editor.onsubmit = (e) => { e.preventDefault(); this.applyEdit(); };
    return this.editor;
  }

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
