/* The Config page's Dashboards section (formerly the /dashboards page): every dashboard with its address, make
   default, rename, duplicate (with this browser's window) and delete; create one from a template, a saved layout
   or rows of charts; and the environment check. Data: /api/dashboards, /api/environment. */
import { layoutKey } from "../keys.js";
import { $, api, el } from "../util.js";

export function initDashboards() {
  let data = null, renaming = null, confirming = null;
  const say = (t, ok) => { $("msg").textContent = t || ""; $("msg").className = "msg " + (ok ? "ok" : t ? "err" : ""); };
  const button = (text, fn, cls, title) => { const b = el("button", cls, text); b.type = "button"; b.onclick = fn; if (title) b.title = title; return b; };

  async function reload() {
    data = await api("/api/dashboards");
    $("rootAddr").textContent = location.host + "/";
    $("nameRule").textContent = "Names: " + data.name_rule + ".";
    render();
  }

  function render() {
    const tb = $("rows");
    tb.innerHTML = "";
    for (const it of data.items) {
      const tr = el("tr");
      const name = el("td");
      if (renaming === it.id) {
        const inp = el("input", "rename"); inp.value = it.name; inp.maxLength = 40; inp.setAttribute("aria-label", "New name");
        const done = async () => {
          const v = inp.value.trim();
          if (!v || v === it.name) { renaming = null; return render(); }
          try { await api("/api/dashboards/" + it.id, { name: v }, "PATCH"); renaming = null; say(`Renamed to "${v}".`, true); await reload(); }
          catch (e) { say(e.message); inp.focus(); }
        };
        inp.onkeydown = (e) => { if (e.key === "Enter") done(); if (e.key === "Escape") { renaming = null; render(); } };
        name.appendChild(inp);
        setTimeout(() => inp.focus(), 0);
      } else {
        const a = el("a", null, it.name); a.href = window.dashUrl(it.name); name.appendChild(a);
        if (it.id === data.default) { name.append(" "); name.appendChild(el("span", "badge", "default")); }
      }
      const addr = el("td", "addr", "/" + it.name);
      const acts = el("td"); const box = el("div", "acts"); acts.appendChild(box);
      if (it.id !== data.default)
        box.appendChild(button("Make default", async () => { await act(() => api(`/api/dashboards/${it.id}/default`, {}), `"${it.name}" now opens at /.`); },
                               null, "Open this one at the plain address"));
      box.appendChild(button("Rename", () => { renaming = it.id; confirming = null; render(); }));
      box.appendChild(button("Duplicate", () => duplicate(it)));
      if (confirming === it.id) {
        box.appendChild(button("Confirm delete", async () => { confirming = null; await act(() => api("/api/dashboards/" + it.id, null, "DELETE"), `Deleted "${it.name}".`); }, "danger"));
        box.appendChild(button("Keep", () => { confirming = null; render(); }));
      } else if (data.items.length > 1) {
        box.appendChild(button("Delete", () => { confirming = it.id; renaming = null; render(); }, "danger"));
      }
      tr.append(name, addr, acts);
      tb.appendChild(tr);
    }
  }

  async function act(fn, ok) {
    try { await fn(); say(ok, true); await reload(); } catch (e) { say(e.message); }
  }

  function freeName(base) {
    const taken = new Set(data.items.map((i) => i.name.toLowerCase()));
    for (let i = 2; ; i++) { const n = `${base}-${i}`.slice(0, 40); if (!taken.has(n.toLowerCase())) return n; }
  }

  async function duplicate(it) {
    const name = freeName(it.name);
    try {
      const made = await api("/api/dashboards", { name, type: "charts", copy_of: it.id });
      // copy this browser's window for it too
      try { const v = localStorage.getItem(layoutKey(it.id)); if (v) localStorage.setItem(layoutKey(made.id), v); } catch (e) { /* unavailable */ }
      say(`Made "${name}". Rename it if you like.`, true);
      await reload();
    } catch (e) { say(e.message); }
  }

  $("createForm").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("newName").value.trim();
    try {
      const [kind, key] = ($("newStart").value || ":").split(/:(.*)/s);
      const made = await api("/api/dashboards", { name, type: "charts", start_layout: kind === "layout" ? key : null,
                                                  start_template: kind === "template" ? key : null,
                                                  start_rows: kind === "rows" ? [+$("newTop").value, +$("newBottom").value] : null });
      location.href = window.dashUrl(made.name);
    } catch (err) { say(err.message); $("newName").focus(); }
  };

  // "Top and bottom rows of charts": shows the two counts
  $("newStart").onchange = () => {
    const on = $("newStart").value === "rows:";
    $("rowsWrap").hidden = !on;
    $("rowsWrap").querySelectorAll("input").forEach((i) => { i.disabled = !on; });
  };
  $("newStart").onchange();

  Promise.all([api("/api/dashboards"), api("/api/saved/layouts").catch(() => ({}))]).then(([d, lays]) => {
    $("rowsWrap").querySelectorAll("input").forEach((i) => { i.max = d.max_per_row || 6; });
    for (const [k, label] of Object.entries(d.templates || {})) {
      const o = el("option", null, label); o.value = "template:" + k; $("newStart").appendChild(o);
    }
    for (const n of Object.keys(lays).sort()) {
      const o = el("option", null, `Saved layout: ${n}`); o.value = "layout:" + n; $("newStart").appendChild(o);
    }
  }).catch(() => {});
  async function environment() {
    const box = $("env");
    box.innerHTML = "";
    let d;
    try { d = await api("/api/environment"); } catch (e) { box.appendChild(el("div", "detail", e.message)); return; }
    const words = { ok: "OK", warn: "Check", fail: "Fail" };
    for (const c of d.checks) {
      const pill = el("span", "pill " + c.status, words[c.status] || c.status);
      const a = el("div"); a.setAttribute("role", "cell"); a.appendChild(pill);
      const b = el("div", null, c.name); b.setAttribute("role", "cell");
      const t = el("div", "detail", c.detail); t.setAttribute("role", "cell");
      box.append(a, b, t);
    }
  }
  $("recheck").onclick = environment;
  environment();
  reload().catch((e) => say(e.message));
}
