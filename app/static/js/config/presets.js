/* The Config page's recommended paper rules (app/paper/presets.py): price above or below VWAP, SMA 50 / 200,
   EMA 9 / 21 and the opening range, breakouts, trend, slope, momentum, and two trend rules made of those. Tick them
   and add them; each becomes an ordinary saved rule (a rule of the same name already saved is kept as it is).
   Data: /api/paper/rules/presets. */
import { $, api, el } from "../util.js";

let say = () => {}, after = () => {};

export async function loadPresets() {
  const { presets } = await api("/api/paper/rules/presets");
  const box = $("ppPresetList");
  box.innerHTML = "";
  let group = null, ul = null;
  for (const p of presets) {
    if (p.group !== group) {
      group = p.group;
      box.appendChild(el("h4", "sec", group));
      ul = box.appendChild(el("ul", "pp-presetlist"));
    }
    const li = el("li");
    const cb = el("input"); cb.type = "checkbox"; cb.value = p.name; cb.disabled = p.added;
    cb.setAttribute("aria-label", `Add "${p.name}"`);
    const lab = el("label"); lab.append(cb, el("b", null, ` ${p.name}`), el("span", "muted small", ` · ${p.about}`));
    if (p.added) lab.appendChild(el("span", "pp-added small", " added"));
    li.appendChild(lab);
    ul.appendChild(li);
  }
  const left = presets.filter((p) => !p.added).length;
  $("ppPresetAll").disabled = !left;
  $("ppPresets").querySelector("summary").dataset.left = left ? `${left} not added yet` : "all added";
}

async function add(names) {
  try {
    const r = await api("/api/paper/rules/presets", { names });
    say("ppPresetMsg", (r.added.length ? `Added ${r.added.length}: ${r.added.join(", ")}.` : "Nothing new to add.") +
        (r.kept.length ? ` Kept your own: ${r.kept.join(", ")}.` : ""));
  } catch (e) { say("ppPresetMsg", e.message, true); return; }
  await loadPresets();
  after();
}

// sayFn(id, text, bad); changed(): the rules changed (the rule menus load again)
export function initPresets(sayFn, changed) {
  say = sayFn; after = changed;
  $("ppPresetAdd").onclick = () => {
    const names = [...$("ppPresetList").querySelectorAll("input:checked:not(:disabled)")].map((x) => x.value);
    if (!names.length) { say("ppPresetMsg", "Tick the rules to add first.", true); return; }
    add(names);
  };
  $("ppPresetAll").onclick = () => add(null);
}
