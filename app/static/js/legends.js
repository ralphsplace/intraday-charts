/* The legend on each pane: studies and drawings with Settings / Hide / Remove, and the label boxes. */
import { openDrawingSettings, openStudySettings } from "./dialogs/settings.js";
import { drawingLabel, drawingsFor, removeDrawing } from "./drawings.js";
import { OUTPUTS } from "./outputs/index.js";
import { gatherOutputs, studyColor } from "./study-layers.js";
import { COLORS } from "./styles.js";
import { toolFor } from "./tools/index.js";
import { spec } from "./state.js";
import { btn, el, morph } from "./util.js";

// legends for a Panel (mixed into Panel)
export class Legends {
  // ---------------------------------------------------------------- legends, labels, drawings list
  paneTops() {
    const tops = [];
    let y = 0;
    for (const p of this.chart.panes()) { tops.push(y); y += p.getHeight() + 1; }
    return tops;
  }

  // drawn into a fresh box and moved onto the live one (morph): a refresh keeps the rows and their buttons
  drawLegends() {
    if (this.dead) return;
    const box = el("div");
    this.drawLegendsInto(box);
    morph(this.legends, box);
  }

  drawLegendsInto(box) {
    const v = this.view;
    if (!v || !this.chart.panes().length) return;
    const lists = this.paneTops().map((top, i) => {
      const d = el("div", "pane-legend"); d.style.top = (top + 4) + "px"; box.appendChild(d);
      if (i === 0) {
        const n = this.studies.length + drawingsFor(this.symbol).length;
        if (n) {                                            // nothing to list: no tag
          d.appendChild(btn(this.legendOpen ? "Hide list" : `Studies (${n})`, () => { this.legendOpen = !this.legendOpen; this.drawLegends(); },
                            "Show or hide the study list", "legtoggle"));
        }
      }
      d.classList.toggle("compact", this.compact());
      d.classList.toggle("open", !!this.legendOpen);
      return d;
    });
    const gathered = gatherOutputs(this, v);                   // e.g. the ATR label boxes
    for (const o of OUTPUTS) {
      const e = o.legend?.(this, gathered[o.key] || []);
      if (e) lists[0].appendChild(e);
    }
    for (const s of this.studies) {
      const res = v.studies[s.uid];
      const pane = s.visible ? (this.rendered[s.uid]?.pane ?? 0) : 0;
      const row = el("div", "leg" + (s.visible ? "" : " hidden"));
      row.dataset.key = s.uid;
      const sw = el("span", "sw2"); sw.style.background = studyColor(res) || COLORS.muted;
      const name = el("span", "name", res?.label || spec(s.type)?.name || s.type);
      row.append(sw, name);
      if (res?.note) row.appendChild(el("span", "note", res.note));
      if (res && !res.ok) row.appendChild(el("span", "err", res.error));
      const acts = el("span", "acts");
      acts.append(btn("Settings", () => openStudySettings(this, s.uid)), btn(s.visible ? "Hide" : "Show", () => this.toggleStudy(s.uid)),
                  btn("×", () => this.removeStudy(s.uid), "Remove " + name.textContent));
      row.appendChild(acts);
      (lists[pane] || lists[0]).appendChild(row);
    }
    for (const d of drawingsFor(this.symbol)) {
      const row = el("div", "leg drawing");
      row.dataset.key = "drawing:" + d.id;
      const sw = el("span", "sw2"); sw.style.background = d.color;
      row.append(sw, el("span", "name", drawingLabel(d)));
      const acts = el("span", "acts");
      acts.append(...(toolFor(d.type).actions?.(this, d) || []));
      acts.append(btn("Settings", () => openDrawingSettings(this.symbol, d)), btn("×", () => removeDrawing(this.symbol, d.id), "Delete " + drawingLabel(d)));
      row.appendChild(acts);
      lists[0].appendChild(row);
    }
  }
}
