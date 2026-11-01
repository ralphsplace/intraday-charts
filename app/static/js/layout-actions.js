/* Adding and removing cells from the page: the Layout section of a cell's menu, and what its buttons do.
   The arithmetic is in layout-edit.js; this applies it (rebuild the grid, save, fetch what a new chart needs)
   and offers Undo after a removal. */
import { refreshAll, requestData } from "./data.js";
import { buildGrid, gridSizes, setActive, showLayout } from "./grid.js";
import { addCell, cantAdd, removeCell } from "./layout-edit.js";
import { toast, toastAction } from "./notify.js";
import { applyLayout, closeMenu, layoutSnapshot } from "./saved.js";
import * as lists from "./lists.js";
import { app, cellKind, isChart, newConfig, save } from "./state.js";
import { btn, clone, el, uid } from "./util.js";
import { tabConfig } from "./watch-tab.js";

// a new watch list panel shows a new named list ("Watch list N") of the symbols on screen; unlinked, it drives the
// active chart (links.js). null (and a message) when the list can't be made.
async function newWatchlistConfig() {
  if (app.listsUnknown) { toast("The watch lists couldn't be loaded: see the note in the corner.", true); return null; }
  try {
    const r = await lists.create("symbols", { symbols: [...new Set(app.panels.map((p) => p.symbol))] });
    return { kind: "watchlist", id: uid(), link: "", tabs: [tabConfig(r.name, r.item.id)] };
  } catch (e) { toast(e.message, true); return null; }
}

// a new trade panel: no account yet (it asks), following the active chart
const newTradeConfig = () => ({ kind: "trade", id: uid(), link: "", account: "" });

// the kinds of cell the Layout section adds: their names, and how a new one starts
const KINDS = {
  chart: { name: "chart", Name: "Chart", make: (cell) => copyOf(cell) },
  watchlist: { name: "watch list", Name: "Watch list", make: () => newWatchlistConfig() },
  trade: { name: "trade panel", Name: "Trade panel", make: () => newTradeConfig() },
};

// a new chart is a copy of the chart it was added from (same duration, range, price type and studies)
// a copy starts unlinked, so typing its new symbol doesn't change the chart it was copied from
function copyOf(cell) {
  if (!isChart(cell.config())) return { ...newConfig(), id: uid() };
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

export async function addNext(cell, where, kind) {
  save();
  const cfg = await KINDS[kind].make(cell);
  if (!cfg) return null;
  const i = app.cells.indexOf(cell);
  if (i < 0) return null;                                  // removed while the list was being made
  const r = addCell({ layout: app.layout, configs: app.configs, sizes: gridSizes() }, i, where, cfg);
  if (r.error) { toast(r.error, true); return null; }
  apply(r);
  const added = app.cells[r.index];
  if (kind === "chart") {
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
  const k = cellKind(cell.config());
  const what = k === "chart" ? `${cell.symbol} chart` : KINDS[k].Name;
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
  const what = KINDS[cellKind(cell.config())].name;
  const rm = btn(`Remove this ${what}`, () => { closeMenu(); removeHere(cell); });
  rm.dataset.action = "remove";
  if (app.cells.length <= 1) { rm.disabled = true; rm.title = "The last chart can't be removed"; }
  grid.append(add("+ Chart left", "left", "chart"), add("+ Chart right", "right", "chart"), add("+ Row below", "below", "chart"),
              add("+ Watch list left", "left", "watchlist"), add("+ Watch list right", "right", "watchlist"), el("span"),
              add("+ Trade panel left", "left", "trade"), add("+ Trade panel right", "right", "trade"), rm);
  box.appendChild(grid);
  return box;
}
