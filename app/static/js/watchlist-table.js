/* A watch list panel's table and footer (mixed into WatchList): the tab's rows with their columns, sorting by a
   header, moving a column by dragging its header onto another, the selected row, and the footer's status and
   "Fetch from TWS". Everything is drawn from what's known now; refresh() fetches. */
import { requestData } from "./data.js";
import { COLUMNS, renderCell } from "./columns.js";
import { groupOf } from "./links.js";
import { app, save } from "./state.js";
import { btn, el, keepScroll, morph } from "./util.js";

const DEMO_RE = /-DEMO$/;

export class WatchListTable {
  // the menus, tabs and table from what's known now (no fetch)
  render() { if (!this.dead) keepScroll(this.body, () => this.renderNow()); }

  renderNow() {
    const t = this.tab();
    t.resolve();
    this.renderTabs();
    this.editB.disabled = !t.item || t.source() === "holdings";
    this.renderListMenu();
    const charts = this.charts();
    if (charts.length) this.selected = charts[0].symbol;
    const target = this.link ? `the ${groupOf(this.link).name.toLowerCase()} linked charts` : "the active chart";
    const cols = t.shownColumns();
    const tb = el("table");                                // drawn fresh, moved onto the live table (morph)
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
      th.dataset.key = id;
      th.ondragover = (e) => { if (e.dataTransfer.types.includes("text/x-wlcol")) { e.preventDefault(); e.currentTarget.classList.add("dropto"); } };
      th.ondragleave = (e) => e.currentTarget.classList.remove("dropto");
      th.ondrop = (e) => {
        e.preventDefault(); e.currentTarget.classList.remove("dropto");
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
      tr.dataset.symbol = sym; tr.dataset.key = sym;
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
    morph(this.table, tb);
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
}
