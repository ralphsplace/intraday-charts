/* The grid of charts: building it for a layout, the active chart, column/row splitters, maximize. */
import { fillDays } from "./data.js";
import { setTools } from "./drawings.js";
import { Panel } from "./panel.js";
import { LAYOUTS, layoutLabel, shape } from "./layouts.js";
import { migrateLinks, paintAll } from "./links.js";
import { app, isWatchlist, newConfig, save } from "./state.js";
import { WatchList } from "./watchlist.js";
import { $, el } from "./util.js";

// ================================================================ layout
export function setActive(p) {
  if (app.active === p) return;
  app.active = p;
  app.panels.forEach((x) => x.root.classList.toggle("active", x === p));
  for (const c of app.cells) if (!c.link) c.activeChanged?.();   // unlinked watch lists follow the active chart
}

export function buildGrid() {
  app.cells.forEach((p) => p.destroy());
  app.cells = []; app.panels = [];
  const sh = shape(app.layout), n = sh.count;
  while (app.configs.length < n) app.configs.push(newConfig());
  migrateLinks(app.configs);
  const grid = $("grid");
  grid.querySelectorAll(".splitter, .gridrow").forEach((e) => e.remove());
  app.maximized = null;
  grid.className = "grid " + (n === 1 ? "single" : n <= 3 ? "few" : "many");
  // uniform layouts: the charts sit in the grid itself; mixed ones: a box per row, each with its own columns
  const boxes = sh.uniform ? [] : sh.rows.map(() => grid.appendChild(el("div", "gridrow")));
  for (let i = 0; i < n; i++) {
    const cfg = app.configs[i];
    const p = isWatchlist(cfg) ? new WatchList(cfg, i) : new Panel(cfg, i);
    (sh.uniform ? grid : boxes[sh.rowOf(i)]).appendChild(p.root);
    app.cells.push(p);
    if (p instanceof Panel) { p.fillSymbols(); app.panels.push(p); }
  }
  paintAll();
  applyGridSizes();
  setActive(app.panels[0]);
  updateBanner();
  fillDays();
  if (app.tool) setTools(app.tool);           // a tool armed in the top bar stays armed on the new charts
}

// ---------------------------------------------------------------- resizing: splitters and maximize
export const MIN_SHARE = 0.12;   // no column or row narrower than 12% of its row or of the grid

// sizes as fractions: rows, and columns (one list in uniform layouts, one list per row in mixed ones)
export function gridSizes() {
  const sh = shape(app.layout), saved = (app.prefs.sizes || {})[app.layout] || {};
  const fit = (a, n) => (Array.isArray(a) && a.length === n && a.every(Number.isFinite) ? [...a] : Array(n).fill(1));
  return { rows: fit(saved.rows, sh.rows.length),
           cols: sh.uniform ? fit(saved.cols, sh.rows[0]) : sh.rows.map((n, r) => fit((saved.cols || [])[r], n)) };
}
export function setGridSizes(sz) {
  app.prefs.sizes = { ...(app.prefs.sizes || {}), [app.layout]: sz };
}

const rowBoxes = () => [...$("grid").querySelectorAll(".gridrow")];
const tracks = (fr) => fr.map((f) => `minmax(0, ${f}fr)`).join(" ");
const ONE = "minmax(0, 1fr)";

export function applyGridSizes() {
  const grid = $("grid"), sh = shape(app.layout), boxes = rowBoxes();
  if (app.maximized) {
    grid.style.gridTemplateColumns = ONE; grid.style.gridTemplateRows = ONE;
    boxes.forEach((b) => { b.hidden = !b.contains(app.maximized.root); b.style.gridTemplateColumns = ONE; });
  } else {
    const { cols, rows } = gridSizes();
    grid.style.gridTemplateColumns = sh.uniform ? tracks(cols) : ONE;
    grid.style.gridTemplateRows = tracks(rows);
    boxes.forEach((b, r) => { b.hidden = false; b.style.gridTemplateColumns = tracks(cols[r]); });
  }
  app.cells.forEach((p) => {
    p.root.hidden = !!app.maximized && app.maximized !== p;
    p.maxBtn.classList.toggle("active", app.maximized === p);
    p.maxBtn.textContent = app.maximized === p ? "⤡" : "⤢";
  });
  requestAnimationFrame(placeSplitters);
}

export function toggleMaximize(p) {
  app.maximized = app.maximized === p ? null : p;
  if (p instanceof Panel) setActive(p);
  applyGridSizes();
}

// the splitters a layout has: between columns (whole height when uniform, else per row) and between rows
function splitterSpecs(sh) {
  const out = [];
  const colRows = sh.uniform ? [0] : sh.rows.map((_, r) => r);
  for (const r of colRows) for (let i = 0; i < sh.rows[r] - 1; i++) out.push({ kind: "col", i, r });
  for (let i = 0; i < sh.rows.length - 1; i++) out.push({ kind: "row", i, r: 0 });
  return out;
}

// splitters are created once per layout and only moved afterwards, so a drag in progress keeps its pointer
export function placeSplitters() {
  const grid = $("grid"), sh = shape(app.layout), boxes = rowBoxes();
  let sps = [...grid.querySelectorAll(".splitter")];
  const specs = splitterSpecs(sh);
  if (sps.length !== specs.length) {
    sps.forEach((e) => e.remove());
    specs.forEach((s) => addSplitter(s.kind, s.i, s.r));
    sps = [...grid.querySelectorAll(".splitter")];
  }
  const show = !app.maximized && app.cells.length;
  const g = grid.getBoundingClientRect();
  for (const sp of sps) {
    sp.hidden = !show;
    if (!show) continue;
    const i = +sp.dataset.i, r = +sp.dataset.r;
    if (sp.dataset.kind === "row") {
      sp.style.top = (app.cells[sh.first[i]].root.getBoundingClientRect().bottom - g.top - 1) + "px";
      continue;
    }
    sp.style.left = (app.cells[sh.first[r] + i].root.getBoundingClientRect().right - g.left - 1) + "px";
    if (!sh.uniform) {                                   // only as tall as its own row
      const b = boxes[r].getBoundingClientRect();
      sp.style.top = (b.top - g.top) + "px"; sp.style.height = b.height + "px"; sp.style.bottom = "auto";
    }
  }
}

// kind "col": between charts i and i+1 of row r (any row, when the layout is uniform); kind "row": below row i
export function addSplitter(kind, i, r = 0) {
  const grid = $("grid");
  const sh = shape(app.layout);
  const sp = el("div", "splitter " + kind);
  sp.dataset.kind = kind; sp.dataset.i = i; sp.dataset.r = r;
  // the list of fractions this splitter moves a boundary in
  const line = (sz) => (kind === "row" ? sz.rows : sh.uniform ? sz.cols : sz.cols[r]);
  sp.title = "Drag to resize. Double-click to make all " +
    (kind === "row" ? "rows" : sh.uniform ? "columns" : "charts in this row") + " equal.";
  sp.addEventListener("dblclick", () => {
    const sz = gridSizes(); line(sz).fill(1); setGridSizes(sz); save(); applyGridSizes();
  });
  sp.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    sp.setPointerCapture(e.pointerId);
    const start = line(gridSizes()), total = start.reduce((a, b) => a + b, 0);
    const span = kind === "row" ? grid.clientHeight : sh.uniform ? grid.clientWidth : rowBoxes()[r].clientWidth;
    const origin = kind === "col" ? e.clientX : e.clientY;
    const pair = start[i] + start[i + 1], min = MIN_SHARE * total;
    sp.classList.add("dragging");
    const move = (ev) => {
      const delta = ((kind === "col" ? ev.clientX : ev.clientY) - origin) / span * total;
      const a = Math.min(Math.max(start[i] + delta, min), pair - min);
      const sz = gridSizes(), l = line(sz); l[i] = a; l[i + 1] = pair - a;
      setGridSizes(sz); applyGridSizes();
    };
    const up = () => {
      sp.removeEventListener("pointermove", move); sp.removeEventListener("pointerup", up);
      sp.classList.remove("dragging"); save();
    };
    sp.addEventListener("pointermove", move);
    sp.addEventListener("pointerup", up);
  });
  grid.appendChild(sp);
}

export function updateBanner() { $("demoBanner").hidden = !app.panels.some((p) => (p.symbol || "").endsWith("-DEMO")); }

export function init() {
  window.addEventListener("resize", () => requestAnimationFrame(placeSplitters));
  // the grid also moves and resizes without the window doing so: the top bar wrapping to a second row (a late
  // warning badge, wider fonts), the replay bar going away in Live. Splitters left behind would sit on charts.
  new ResizeObserver(() => requestAnimationFrame(placeSplitters)).observe($("grid"));
  showLayout();
}

// the Layout menu: the named layouts, plus this window's own when it was made on the Dashboards page (e.g. 3 over 5)
export function showLayout() {
  const menu = $("layout");
  menu.innerHTML = "";
  const ids = Object.keys(LAYOUTS);
  if (!LAYOUTS[app.layout]) ids.push(app.layout);
  for (const id of ids) { const o = el("option", null, layoutLabel(id)); o.value = id; menu.appendChild(o); }
  menu.value = app.layout;
}
