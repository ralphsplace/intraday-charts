/* The Studies dialog: the catalogue, this chart's studies, copy to all charts, reset. */
import { tfLabel } from "../timeframes.js";
import { openModal } from "../dialogs/modal.js";
import { openStudySettings } from "../dialogs/settings.js";
import { app, normStudies, save, spec } from "../state.js";
import { $, btn, clone, el } from "../util.js";

export function openStudies() { renderCatalog(); renderActiveList(); openModal("studiesDlg"); $("studySearch").focus(); }

export function renderCatalog() {
  const q = $("studySearch").value.trim().toLowerCase();
  const list = $("catalogList");
  list.innerHTML = "";
  for (const cat of [...new Set(app.catalog.map((s) => s.category))]) {
    const items = app.catalog.filter((s) => s.category === cat && (!q || (s.name + " " + s.description).toLowerCase().includes(q)));
    if (!items.length) continue;
    const sec = el("div", "cat");
    sec.appendChild(el("h4", null, cat));
    for (const s of items) {
      const row = el("div", "item");
      const txt = el("div", "txt", s.name);
      txt.appendChild(el("small", null, s.description));
      row.append(txt, btn("Add", () => app.active.addStudy(s.type), "Add " + s.name));
      sec.appendChild(row);
    }
    list.appendChild(sec);
  }
}

export function renderActiveList() {
  const p = app.active, list = $("activeList");
  $("activeTitle").textContent = `On this chart (${p.symbol} ${tfLabel(p.tf)})`;
  list.innerHTML = "";
  if (!p.studies.length) { list.appendChild(el("p", "muted", "No studies. Add one from the list.")); return; }
  for (const s of p.studies) {
    const res = p.view?.studies[s.uid];
    const row = el("div", "arow" + (s.visible ? "" : " hidden"));
    row.append(el("span", "txt", res?.label || spec(s.type)?.name || s.type),
               btn("Settings", () => openStudySettings(p, s.uid)), btn(s.visible ? "Hide" : "Show", () => p.toggleStudy(s.uid)),
               btn("Remove", () => p.removeStudy(s.uid)));
    list.appendChild(row);
  }
}

export function init() {
  $("studySearch").oninput = renderCatalog;
  $("copyStudies").onclick = () => {
    if (!confirm("Give every chart in this layout the same studies as this chart?")) return;
    for (const p of app.panels) if (p !== app.active) { p.studies = normStudies(clone(app.active.studies).map((s) => ({ ...s, uid: null }))); p.refresh(); }
    save();
  };
  $("resetStudies").onclick = () => { app.active.studies = normStudies(clone(app.defaults)); app.active.changed(); };

}
