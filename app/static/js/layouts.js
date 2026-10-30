/* Window layouts. A layout is a list of rows, each the number of charts in it. Uniform layouts (every row the
   same) share their columns, so a column splitter runs from top to bottom; in mixed ones (e.g. 2 over 4) each row
   has its own columns and its own column splitters. Both have row splitters.

   Two kinds of id: the named ones below (the Layout menu's list), and "rows" ids such as "2/4" (2 charts over 4),
   "3/5" or "4" (one row of 4), made on the Dashboards page or by adding and removing charts (layout-edit.js). */
export const MAX_PER_ROW = 6;            // app/templates.py has the same limit
export const MAX_ROWS = 4;

export const LAYOUTS = {
  "1x1": { label: "1 chart", rows: [1] },
  "2x1": { label: "2 side by side", rows: [2] },
  "3x1": { label: "3 side by side", rows: [3] },
  "2x2": { label: "2 × 2", rows: [2, 2] },
  "3x2": { label: "3 × 2", rows: [3, 3] },
  "3x3": { label: "3 × 3", rows: [3, 3, 3] },
  "4x3": { label: "4 × 3", rows: [4, 4, 4] },
  "2/4": { label: "2 over 4", rows: [2, 4] },
};

// the rows of a layout id, or null when it isn't one
export function rowsOf(id) {
  if (LAYOUTS[id]) return LAYOUTS[id].rows;
  if (typeof id !== "string" || !/^\d+(\/\d+)*$/.test(id)) return null;      // "4" (one row), "2/4", "3/2/1"
  const rows = id.split("/").map(Number);
  return rows.length <= MAX_ROWS && rows.every((n) => n >= 1 && n <= MAX_PER_ROW) ? rows : null;
}

export const isLayout = (id) => rowsOf(id) !== null;
export function layoutLabel(id) {
  if (LAYOUTS[id]) return LAYOUTS[id].label;
  const rows = rowsOf(id) || [1];
  return rows.length === 1 ? `${rows[0]} side by side` : rows.join(" over ");
}

// everything the grid needs to know about a layout
export function shape(id) {
  const rows = rowsOf(id) || [1];
  const first = rows.map((_, r) => rows.slice(0, r).reduce((a, b) => a + b, 0));   // index of each row's first chart
  return { rows, count: rows.reduce((a, b) => a + b, 0), uniform: rows.every((n) => n === rows[0]), first,
           rowOf: (i) => rowOf(rows, i) };
}

function rowOf(rows, i) {
  let r = 0;
  while (i >= rows[r]) { i -= rows[r]; r++; }
  return r;
}
