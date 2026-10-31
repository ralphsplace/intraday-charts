/* The settings dialog, built from a parameter list: used by studies, price types and drawings. */
import { closeModal, openModal } from "../dialogs/modal.js";
import { saveDrawings } from "../drawings.js";
import { app, defaultsFor, spec } from "../state.js";
import { $ } from "../util.js";
import { fillForm, readForm } from "../settings-form.js";
import { defaultsOf } from "../params.js";
import { toolFor } from "../tools/index.js";
import { PriceTypes as PT } from "../pricetypes.js";

const fillSettings = (params, values) => fillForm($("settingsForm"), params, values);

export function openSettings({ title, desc, params, values, defaults, onApply }) {
  app.editing = { params, defaults, onApply };
  $("settingsTitle").textContent = title;
  $("settingsDesc").textContent = desc || "";
  fillSettings(params, values);
  openModal("settingsDlg");
}

export function openPriceSettings(panel) {
  const t = PT.get(panel.price.type);
  openSettings({ title: "Price: " + t.name, desc: t.description, params: t.params, values: panel.price.params,
                 defaults: PT.defaults(t.id), onApply: (vals) => panel.setPrice(PT.normalize({ type: t.id, params: vals })) });
}

export function openStudySettings(panel, id) {
  const s = panel.studies.find((x) => x.uid === id);
  const sp = s && spec(s.type);
  if (!sp) return;
  openSettings({ title: sp.name, desc: sp.description, params: sp.params, values: s.params, defaults: defaultsFor(s.type),
                 onApply: (vals) => { Object.assign(s.params, vals); panel.changed(); } });
}

// a drawing's settings, from its tool (tools/)
export function openDrawingSettings(sym, d) {
  const tool = toolFor(d.type), { title, desc, params } = tool.settings(d);
  openSettings({ title, desc, params, values: d, defaults: defaultsOf(params),
                 onApply: (vals) => { Object.assign(d, vals); tool.applied?.(d); saveDrawings(sym); } });
}

export function init() {
  $("settingsDefaults").onclick = () => app.editing && fillSettings(app.editing.params, app.editing.defaults);
  $("settingsApply").onclick = () => {
    if (!app.editing) return;
    const vals = readForm($("settingsForm"));
    closeModal("settingsDlg");
    app.editing.onApply(vals);
  };
  $("settingsForm").onsubmit = (e) => { e.preventDefault(); $("settingsApply").click(); };

}
