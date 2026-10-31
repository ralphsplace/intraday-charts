/* Saved chart views and window layouts (kept on the server), and their menu. */
import { refreshAll, requestData } from "./data.js";
import { buildGrid, setActive, showLayout } from "./grid.js";
import { layoutSection } from "./layout-actions.js";
import { isLayout, layoutLabel } from "./layouts.js";
import { defaultSpan, isPeriod, rangeLabel, tfLabel } from "./timeframes.js";
import { app, normStudies, save } from "./state.js";
import { $, api, btn, clone, el } from "./util.js";

let menuFor = null;
export function closeMenu() { $("savedMenu").hidden = true; menuFor = null; }

export function layoutSnapshot() {
  save();
  return { layout: app.layout, configs: clone(app.configs.slice(0, app.cells.length)),
           sizes: clone((app.prefs.sizes || {})[app.layout] || null),
           prefs: { fitLevels: app.prefs.fitLevels, extShade: app.prefs.extShade, sync: app.prefs.sync } };
}

export async function applyLayout(d) {
  if (!d || !isLayout(d.layout)) return;
  app.layout = d.layout;
  app.configs = clone(d.configs || []).map((c) => ({ ...c, studies: normStudies(c.studies) }));
  app.prefs.sizes = app.prefs.sizes || {};
  if (d.sizes) app.prefs.sizes[d.layout] = d.sizes; else delete app.prefs.sizes[d.layout];
  Object.assign(app.prefs, d.prefs || {});
  showLayout();
  $("fitLevels").checked = app.prefs.fitLevels; $("extShade").checked = app.prefs.extShade; $("syncCrosshair").checked = app.prefs.sync;
  buildGrid(); save();
  if (app.live) requestData([...new Set(app.panels.map((p) => p.symbol))]);
  await refreshAll();
}

export function applyView(panel, d, keepSymbol) {
  const i = app.cells.indexOf(panel);
  if (i < 0) return;
  app.configs[i] = { id: panel.id, link: panel.link, symbol: keepSymbol ? panel.symbol : (d.symbol || panel.symbol), tf: d.tf || 3, days: d.days || 1,
                     spans: d.spans, price: d.price, style: d.style, studies: normStudies(clone(d.studies || [])) };
  buildGrid(); save();
  if (app.live) requestData([app.configs[i].symbol]);
  setActive(app.cells[i]);
  refreshAll();
}

export async function openSavedMenu(anchor, kind, panel) {
  if (menuFor === anchor) return closeMenu();
  menuFor = anchor;
  const m = $("savedMenu");
  m.innerHTML = "";
  const title = kind === "views" ? `Chart views` : "Window layouts";
  m.appendChild(el("div", "mtitle", title));
  const row = el("div", "mrow");
  const name = el("input"); name.type = "text"; name.maxLength = 60;
  name.placeholder = kind === "views" ? `Name for this chart's view` : "Name for this layout";
  const saveB = btn("Save", null, null, "primary");
  row.append(name, saveB);
  m.appendChild(row);
  const keep = el("label", "mkeep");
  const keepCb = el("input"); keepCb.type = "checkbox";
  if (kind === "views") {
    keep.append(keepCb, " Keep this chart's symbol when loading");
    m.appendChild(keep);
  }
  const list = el("div", "mlist");
  m.appendChild(list);
  const msg = el("div", "muted small");
  m.appendChild(msg);

  const items = () => app.saved[kind] || {};
  const describe = (d) => kind === "views"
    ? `${d.symbol} ${tfLabel(d.tf)}, ${rangeLabel(d.tf, isPeriod(d.tf) ? (d.spans || {})[d.tf] || defaultSpan(d.tf) : d.days || 1).toLowerCase()}, ${(d.studies || []).length} studies`
    : `${layoutLabel(d.layout)}: ${(d.configs || []).map((c) => c.symbol).join(" ")}`;
  function renderList() {
    list.innerHTML = "";
    const names = Object.keys(items()).sort((a, b) => a.localeCompare(b));
    if (!names.length) list.appendChild(el("div", "muted small", "Nothing saved yet."));
    for (const n of names) {
      const it = el("div", "mitem");
      const load = btn("", async () => {
        closeMenu();
        if (kind === "views") applyView(panel, items()[n], keepCb.checked);
        else await applyLayout(items()[n]);
      });
      load.className = "mload";
      load.append(el("b", null, n), el("span", "muted small", describe(items()[n])));
      load.title = `Load "${n}"`;
      const del = btn("\u00d7", async () => {
        app.saved[kind] = await api(`/api/saved/${kind}/${encodeURIComponent(n)}`, null, "DELETE");
        renderList();
      }, `Delete ${n}`, "mdel");
      del.title = `Delete "${n}"`;
      it.append(load, del);
      list.appendChild(it);
    }
  }
  name.oninput = () => { saveB.textContent = items()[name.value.trim()] ? "Replace" : "Save"; };
  const doSave = async () => {
    const n = name.value.trim();
    if (!n) { name.focus(); msg.textContent = "Type a name first."; return; }
    const data = kind === "views" ? clone(panel.config()) : layoutSnapshot();
    try {
      app.saved[kind] = await api(`/api/saved/${kind}/${encodeURIComponent(n)}`, data, "PUT");
      name.value = ""; saveB.textContent = "Save";
      msg.textContent = `Saved "${n}".`;
      renderList();
    } catch (e) { msg.textContent = e.message; }
  };
  saveB.onclick = doSave;
  name.onkeydown = (e) => { if (e.key === "Enter") doSave(); if (e.key === "Escape") closeMenu(); };
  if (kind === "views") m.appendChild(layoutSection(panel));     // add a chart or watch list next to it, or remove it
  renderList();
  placeMenu(m, anchor);
  name.focus();
  api(`/api/saved/${kind}`).then((d) => { app.saved[kind] = d; renderList(); }).catch(() => {});
}

// under its button, or above it when there's no room below (a bottom-row chart); never past the window's edge
function placeMenu(m, anchor) {
  m.hidden = false;
  const r = anchor.getBoundingClientRect();
  const w = Math.min(340, window.innerWidth - 16);
  m.style.width = w + "px";
  m.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + "px";
  m.style.maxHeight = (window.innerHeight - 16) + "px";
  m.style.overflowY = "auto";
  const h = m.offsetHeight;
  const below = r.bottom + 4, above = r.top - 4 - h;
  m.style.top = (below + h <= window.innerHeight - 8 ? below : above >= 8 ? above : Math.max(8, window.innerHeight - 8 - h)) + "px";
}

// a watch list's menu: just its Layout section
export function openCellMenu(anchor, cell) {
  if (menuFor === anchor) return closeMenu();
  menuFor = anchor;
  const m = $("savedMenu");
  m.innerHTML = "";
  m.appendChild(layoutSection(cell));
  placeMenu(m, anchor);
}

export function init() {
  document.addEventListener("mousedown", (e) => {
    if (!$("savedMenu").hidden && !$("savedMenu").contains(e.target) && !e.target.closest(".viewsbtn, #layoutsBtn")) closeMenu();
  });

  $("layoutsBtn").onclick = (e) => openSavedMenu(e.currentTarget, "layouts");

}
