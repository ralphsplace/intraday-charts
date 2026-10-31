/* Symbol linking between the cells of a window (charts, watch lists, and any kind added later), like the link
   colours of TWS and thinkorswim: cells in the same colour group follow each other's symbol. Any number of
   cells can share a group, and a window can have several groups.

   One interface for every kind of cell:
     cell.link              the group's id ("red", ...), or "" when not linked
     cell.showLinked(sym)   another cell of its group changed symbol: follow it (without publishing again)
   A cell whose own symbol changes (typed, or a watch list row picked) calls publish(cell, sym).
   A watch list in no group drives the active chart. */
import { app, save } from "./state.js";
import { el } from "./util.js";

export const GROUPS = [
  { id: "", name: "Not linked", color: "" },
  { id: "red", name: "Red", color: "#e5534b" },
  { id: "green", name: "Green", color: "#3fb950" },
  { id: "blue", name: "Blue", color: "#4d9de0" },
  { id: "yellow", name: "Yellow", color: "#d4a72c" },
  { id: "purple", name: "Purple", color: "#a371f7" },
  { id: "orange", name: "Orange", color: "#f0883e" },
];
const known = (id) => !!id && GROUPS.some((g) => g.id === id);
export const groupOf = (id) => GROUPS.find((g) => g.id === id) || GROUPS[0];

// the other cells of a cell's group, in reading order
export const members = (cell) => (cell.link ? app.cells.filter((c) => c !== cell && c.link === cell.link) : []);

export function publish(from, symbol) {
  for (const c of members(from)) c.showLinked?.(symbol);
}

// Earlier watch lists named one chart by its id ("active" for the active chart): give both a group of their own
// (the first colour not in use). Settings in, settings changed in place; unknown groups are dropped.
export function migrateLinks(configs) {
  const used = new Set(configs.map((c) => c?.link).filter(known));
  for (const c of configs) {
    if (!c || !c.link || known(c.link)) continue;
    const chart = c.kind === "watchlist" ? configs.find((x) => x && x !== c && x.id === c.link) : null;
    const group = chart ? (known(chart.link) ? chart.link : GROUPS.find((g) => g.id && !used.has(g.id))?.id) : "";
    if (chart && group) { chart.link = group; used.add(group); }
    c.link = group || "";
  }
  return configs;
}

/* A cell header's link control: a coloured square over an invisible menu of the groups (so it takes little
   room, and the browser's own menu shows the names). onChange runs after the cell joins another group. */
export function linkControl(cell, onChange) {
  const box = el("span", "linkbox");
  const sel = el("select", "linksel");
  sel.setAttribute("aria-label", "Symbol link");
  for (const g of GROUPS) { const o = el("option", null, g.name); o.value = g.id; sel.appendChild(o); }
  const paint = () => {
    const g = groupOf(cell.link);
    sel.value = g.id;
    box.style.setProperty("--link", g.color || "transparent");
    box.classList.toggle("on", !!g.id);
    const n = members(cell).length;
    box.title = g.id ? `Linked: ${g.name} (${n} other${n === 1 ? "" : "s"}): cells of the same colour show the same symbol`
                     : "Not linked. Pick a colour: charts and watch lists of the same colour show the same symbol";
  };
  sel.onchange = () => { cell.link = sel.value; save(); paintAll(); onChange?.(); };
  box.appendChild(sel);
  cell.paintLink = paint;
  paint();
  return box;
}

// after a change of group, every cell's control (its count of others) and every watch list's highlight
export function paintAll() {
  for (const c of app.cells) { c.paintLink?.(); c.linksChanged?.(); }
}
