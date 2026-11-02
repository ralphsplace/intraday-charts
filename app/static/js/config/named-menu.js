/* The menu at the top of a Config section that edits named things (paper rules, paper strategies): pick one or
   "New …", Rename in place (the menu becomes a box while typing), and Delete (asks once). The server keeps them
   (base: /api/paper/rules, /api/paper/strategies); each answer carries the new list (key: "rules", "strategies"). */
import { api, el } from "../util.js";

export const NEW = "\u0000new";
const enc = encodeURIComponent;

// o: { sel, renameBtn, deleteBtn, base, key, what, say, items() -> {name: item}, set(items), pick(name), changed() }
export function namedMenu(o) {
  let current = NEW;
  const names = () => Object.keys(o.items()).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const fill = () => {
    o.sel.innerHTML = "";
    for (const [v, t] of [[NEW, `New ${o.what}…`], ...names().map((n) => [n, n])]) { const x = el("option", null, t); x.value = v; o.sel.appendChild(x); }
    if (current !== NEW && !o.items()[current]) current = NEW;
    o.sel.value = current;
    o.renameBtn.disabled = o.deleteBtn.disabled = current === NEW;
  };
  const show = (name) => { current = name; fill(); o.pick(current); };
  o.sel.onchange = () => show(o.sel.value);
  o.renameBtn.onclick = () => {
    const input = el("input", "cfg-input"), sel = o.sel;
    Object.assign(input, { value: current, maxLength: 60, spellcheck: false });
    input.setAttribute("aria-label", `New name for the ${o.what}`);
    sel.replaceWith(input); input.focus(); input.select();
    let finished = false;
    const done = async (keep) => {
      if (finished) return;
      finished = true;
      input.replaceWith(sel);
      const to = input.value.trim();
      if (!keep || !to || to === current) return;
      try {
        const r = await api(`${o.base}/${enc(current)}/rename`, { to });
        o.set(r); current = r.name; o.say(`Renamed to "${r.name}".`);
      } catch (e) { o.say(e.message, true); }
      show(current); o.changed();
    };
    input.onkeydown = (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); };
    input.onblur = () => done(true);
  };
  o.deleteBtn.onclick = async (e) => {
    const b = e.currentTarget;
    if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Delete? Yes"; setTimeout(() => { b.dataset.sure = ""; b.textContent = "Delete"; }, 4000); return; }
    b.dataset.sure = ""; b.textContent = "Delete";
    try { o.set(await api(`${o.base}/${enc(current)}`, null, "DELETE")); o.say(`Deleted "${current}".`); current = NEW; }
    catch (err) { o.say(err.message, true); return; }
    show(current); o.changed();
  };
  return { show, fill, current: () => current, names };
}
