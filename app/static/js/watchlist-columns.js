/* A watch list panel's column chooser (mixed into WatchList): the columns a tab's kind of list can show
   (columns.js), grouped by section, with heat shading where a column has it, and Defaults. */
import { COLUMNS, DEFAULTS, SECTIONS, available, sectionOf } from "./columns.js";
import { save } from "./state.js";
import { btn, el } from "./util.js";

export class WatchListColumns {
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
}
