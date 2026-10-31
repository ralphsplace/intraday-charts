/* Adding and removing cells from the page: the Layout section of a cell's menu, and what its buttons do.
   The arithmetic is in layout-edit.js; this applies it (rebuild the grid, save, fetch what a new chart needs)
   and offers Undo after a removal. */
import { refreshAll, requestData } from "./data.js";
import { buildGrid, gridSizes, setActive, showLayout } from "./grid.js";
import { addCell, cantAdd, removeCell } from "./layout-edit.js";
import { toast, toastAction } from "./notify.js";
import { applyLayout, closeMenu, layoutSnapshot } from "./saved.js";
import { app, isWatchlist, newConfig, save } from "./state.js";
import { btn, clone, el, uid } from "./util.js";

// a new watch list starts with the symbols on screen, unlinked: it drives the active chart (links.js)
export function newWatchlistConfig() {
  return { kind: "watchlist", id: uid(), symbols: [...new Set(app.panels.map((p) => p.symbol))], list: "", link: "" };
}

// a new chart is a copy of the chart it was added from (same duration, range, price type and studies)
// a copy starts unlinked, so typing its new symbol doesn't change the chart it was copied from
function copyOf(cell) {
  if (isWatchlist(cell.config())) return { ...newConfig(), id: uid() };
  const c = clone(cell.config());
  return { ...c, id: uid(), link: "", studies: (c.studies || []).map((s) => ({ ...s, uid: uid() })) };
}

function apply(r) {
  app.layout = r.layout;
  app.configs = r.configs;
  app.prefs.sizes = { ...(app.prefs.sizes || {}), [r.layout]: r.sizes };
  showLayout();
  buildGrid();
  save();
}

export function addNext(cell, where, kind) {
  save();
  const i = app.cells.indexOf(cell);
  const cfg = kind === "watchlist" ? newWatchlistConfig() : copyOf(cell);
  const r = addCell({ layout: app.layout, configs: app.configs, sizes: gridSizes() }, i, where, cfg);
  if (r.error) { toast(r.error, true); return null; }
  apply(r);
  const added = app.cells[r.index];
  if (kind !== "watchlist") {
    setActive(added);
    if (app.live) requestData([added.symbol]);
    added.symIn.focus();                                  // type the new chart's symbol straight away (selected)
  }
  refreshAll();
  return added;
}

export function removeHere(cell) {
  save();
  const before = layoutSnapshot();
  const r = removeCell({ layout: app.layout, configs: app.configs, sizes: gridSizes() }, app.cells.indexOf(cell));
  if (r.error) { toast(r.error, true); return; }
  const what = isWatchlist(cell.config()) ? "Watch list" : `${cell.symbol} chart`;
  apply(r);
  refreshAll();
  toastAction(`${what} removed.`, "Undo", () => applyLayout(before));
}

// the Layout section of a cell's menu
export function layoutSection(cell) {
  const box = el("div", "mlayout");
  box.appendChild(el("div", "mtitle", "Layout"));
  const grid = el("div", "mgrid");
  const i = app.cells.indexOf(cell);
  const add = (text, where, kind) => {
    const b = btn(text, () => { closeMenu(); addNext(cell, where, kind); });
    const why = cantAdd(app.layout, i, where);
    if (why) { b.disabled = true; b.title = why; }
    b.dataset.action = `${kind}-${where}`;
    return b;
  };
  const what = isWatchlist(cell.config()) ? "watch list" : "chart";
  const rm = btn(`Remove this ${what}`, () => { closeMenu(); removeHere(cell); });
  rm.dataset.action = "remove";
  if (app.cells.length <= 1) { rm.disabled = true; rm.title = "The last chart can't be removed"; }
  grid.append(add("+ Chart left", "left", "chart"), add("+ Chart right", "right", "chart"), add("+ Row below", "below", "chart"),
              add("+ Watch list left", "left", "watchlist"), add("+ Watch list right", "right", "watchlist"), rm);
  box.appendChild(grid);
  return box;
}
