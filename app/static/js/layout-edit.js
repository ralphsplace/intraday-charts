/* Adding and removing cells (charts, watch lists) in a window layout. Pure functions: a layout id, the cells'
   settings in reading order and the splitter sizes in, the new ones out; nothing here touches the page.

   where: "left" or "right" of cell i in its row, or "below": a new row of one cell under cell i's row.
   In a row of equal widths the new cell makes them equal again; otherwise it takes half the width of the cell
   it's added next to. A new row gets an average row's height.
   Settings past the layout's count (cells hidden when switching to a smaller layout) are kept at the end. */
import { LAYOUTS, MAX_PER_ROW, MAX_ROWS, shape } from "./layouts.js";

// the id for a list of rows: a named layout's when the rows match one (keeps its name in the menu), else "2/5" etc.
export function layoutId(rows) {
  const named = Object.entries(LAYOUTS).find(([, l]) => l.rows.join("/") === rows.join("/"));
  return named ? named[0] : rows.join("/");
}

// sizes with one column list per row (uniform layouts share one list)
function perRow(sh, sizes) {
  const rows = sizes?.rows?.length === sh.rows.length ? [...sizes.rows] : sh.rows.map(() => 1);
  const cols = sh.rows.map((n, r) => {
    const c = sh.uniform ? sizes?.cols : sizes?.cols?.[r];
    return Array.isArray(c) && c.length === n ? [...c] : Array(n).fill(1);
  });
  return { rows, cols };
}

function finish(rows, sz) {
  const uniform = rows.every((n) => n === rows[0]);
  return { layout: layoutId(rows), sizes: { rows: sz.rows, cols: uniform ? sz.cols[0] : sz.cols } };
}

// why a cell can't be added there, or "" when it can
export function cantAdd(layout, i, where) {
  const sh = shape(layout), r = sh.rowOf(i);
  if (where === "below") return sh.rows.length >= MAX_ROWS ? `A window has at most ${MAX_ROWS} rows` : "";
  return sh.rows[r] >= MAX_PER_ROW ? `A row has at most ${MAX_PER_ROW} charts` : "";
}

export function addCell({ layout, configs, sizes }, i, where, cfg) {
  const why = cantAdd(layout, i, where);
  if (why) return { error: why };
  const sh = shape(layout), r = sh.rowOf(i), c = i - sh.first[r];
  const rows = [...sh.rows], sz = perRow(sh, sizes), out = [...configs];
  let at;
  if (where === "below") {
    rows.splice(r + 1, 0, 1);
    sz.rows.splice(r + 1, 0, sz.rows.reduce((a, b) => a + b, 0) / sz.rows.length);
    sz.cols.splice(r + 1, 0, [1]);
    at = sh.first[r] + sh.rows[r];
  } else {
    rows[r] += 1;
    if (sz.cols[r].every((w) => w === sz.cols[r][0])) {
      sz.cols[r] = Array(rows[r]).fill(1);                // equal widths stay equal
    } else {                                              // else the new cell takes half its neighbour's width
      const half = sz.cols[r][c] / 2;
      sz.cols[r][c] = half;
      sz.cols[r].splice(where === "left" ? c : c + 1, 0, half);
    }
    at = where === "left" ? i : i + 1;
  }
  out.splice(at, 0, cfg);
  return { ...finish(rows, sz), configs: out, index: at };
}

export function removeCell({ layout, configs, sizes }, i) {
  const sh = shape(layout);
  if (sh.count <= 1) return { error: "The last chart can't be removed" };
  const r = sh.rowOf(i), c = i - sh.first[r];
  const rows = [...sh.rows], sz = perRow(sh, sizes), out = [...configs];
  rows[r] -= 1;
  sz.cols[r].splice(c, 1);
  if (!rows[r]) { rows.splice(r, 1); sz.rows.splice(r, 1); sz.cols.splice(r, 1); }
  out.splice(i, 1);
  return { ...finish(rows, sz), configs: out };
}
