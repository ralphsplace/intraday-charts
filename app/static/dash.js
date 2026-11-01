/* Page switcher: a drop-down in each page's toolbar listing every dashboard, then the other pages (Earnings,
   Manage dashboards…). Fills any element with id "dashNav". Shared by the chart, earnings, expected-move and dashboards pages. */
(() => {
  const me = window.DASHBOARD || null;
  window.dashUrl = (name) => "/" + encodeURIComponent(name);
  async function fill() {
    const host = document.getElementById("dashNav");
    if (!host) return;
    let d;
    try { d = await (await fetch("/api/dashboards")).json(); } catch (e) { return; }
    const sel = document.createElement("select");
    sel.className = "dashsel";
    sel.title = "Switch dashboard (each has its own address)";
    sel.setAttribute("aria-label", "Dashboard");
    for (const it of d.items) {
      const o = document.createElement("option");
      o.value = it.name;
      o.textContent = it.name + (it.id === d.default ? "  (default)" : "");
      if (me && it.id === me.id) o.selected = true;
      sel.appendChild(o);
    }
    const pages = { "\u0000earnings": ["Earnings", "/earnings"], "\u0000expected-move": ["Expected move", "/expected-move"],
                    "\u0000options": ["Option chain", "/options"],
                    "\u0000paper": ["Paper trading", "/paper"],
                    "\u0000config": ["Config", "/config"],
                    "\u0000manage": ["Manage dashboards…", "/dashboards"] };
    for (const [v, [text, path]] of Object.entries(pages)) {
      const o = document.createElement("option");
      o.value = v; o.textContent = text;
      if (!me && location.pathname === path) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = () => { location.href = pages[sel.value] ? pages[sel.value][1] : window.dashUrl(sel.value); };
    host.innerHTML = "";
    host.appendChild(sel);
    try {   // a check that needs attention shows as a small link on every page
      const env = await (await fetch("/api/environment")).json();
      const bad = env.checks.filter((c) => c.status !== "ok");
      if (bad.length) {
        const a = document.createElement("a");
        a.href = "/dashboards#environment";
        a.className = "envwarn";
        a.textContent = `\u26A0 ${bad.length}`;
        a.setAttribute("aria-label", `Environment check: ${bad.length} to look at`);
        a.title = "Environment check: " + bad.map((c) => `${c.name}: ${c.detail}`).join("\n");
        host.appendChild(a);
      }
    } catch (e) { /* the page works without it */ }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fill); else fill();
})();
