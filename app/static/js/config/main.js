/* The Config page: everything set up once and kept on the NAS. Sections: the dashboards (config/dashboards.js,
   with the environment check), the named watch lists (rename, delete), each watch list type's default columns,
   every study's default settings and colours, and paper trading's accounts, rules, strategies and backtest
   defaults (config/paper.js, rules.js, strategies.js, backtests.js). Changes are saved as they're made. */
import { fillForm, readForm } from "../settings-form.js";
import { initBacktestDefaults, loadBacktestDefaults } from "./backtests.js";
import { initDashboards } from "./dashboards.js";
import { initPaper, loadPaper } from "./paper.js";
import { initRules, loadRules } from "./rules.js";
import { initStrategies, loadStrategies } from "./strategies.js";
import { $, api, btn, el, load, store } from "../util.js";

const TAB_KEY = "intraday-charts:config-tab";
const KINDS = [["quote", "Symbols"], ["finviz", "FinViz"], ["holding", "Holdings"]];
const SOURCES = { symbols: "Symbols", finviz: "FinViz", holdings: "Holdings (IBKR)" };

let cfg = null, kind = "quote", study = null;
const say = (id, t, bad) => { $(id).textContent = t || ""; $(id).classList.toggle("bad", !!bad); };
const sayRule = (t, bad) => say("ppRuleMsg", t, bad);
const sayStrat = (t, bad) => say("ppStratMsg", t, bad);

async function reload() {
  cfg = await api("/api/config");
  $("cfgPath").textContent = cfg.path;
  renderLists(); renderColumns(); renderStudyList();
  if (study) showStudy(study);
  await Promise.all([loadPaper(say), loadRules(sayRule), loadStrategies(sayStrat), loadBacktestDefaults(say)]);
}

// ---------------------------------------------------------------- watch lists
function renderLists() {
  const t = $("cfgLists");
  t.innerHTML = "";
  const head = el("tr");
  for (const h of ["Name", "Source", "Contents", ""]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  const names = Object.keys(cfg.watchlists).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  if (!names.length) {
    const td = el("td", "muted", "No watch lists yet: + in a watch list panel makes one."); td.colSpan = 4;
    t.appendChild(el("tr")).appendChild(td);
  }
  for (const name of names) {
    const v = cfg.watchlists[name];
    const tr = el("tr");
    tr.dataset.name = name;
    const nameTd = el("td", "cfg-name", name);
    const what = v.source === "symbols" ? (v.symbols.length ? v.symbols.slice(0, 12).join(" ") + (v.symbols.length > 12 ? ` … (${v.symbols.length})` : "") : "empty")
      : v.source === "finviz" ? (v.feed?.label || v.feed?.address || "") : "the account's stock and ETF positions";
    const acts = el("td", "cfg-acts");
    acts.append(btn("Rename", () => rename(tr, nameTd, name), `Rename "${name}"`, "cfg-rename"),
                btn("Delete", (e) => confirmDelete(e.currentTarget, name), `Delete "${name}" everywhere`, "cfg-delete danger"));
    tr.append(nameTd, el("td", null, SOURCES[v.source] || v.source), el("td", "muted small cfg-what", what), acts);
    t.appendChild(tr);
  }
}

function rename(tr, td, name) {
  const input = el("input", "cfg-input");
  Object.assign(input, { value: name, maxLength: 60, spellcheck: false });
  input.setAttribute("aria-label", `New name for ${name}`);
  td.innerHTML = ""; td.appendChild(input); input.focus(); input.select();
  let done = false;
  const finish = async (keep) => {
    if (done) return;
    done = true;
    const to = input.value.trim();
    if (keep && to && to !== name) {
      try { await api(`/api/watchlists/${encodeURIComponent(name)}/rename`, { to }); say("cfgStatus", `Renamed "${name}" to "${to}".`); }
      catch (e) { say("cfgStatus", e.message, true); }
    }
    await reload();
  };
  input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); };
  input.onblur = () => finish(true);
}

// two clicks, without a browser dialog: the button asks first
function confirmDelete(b, name) {
  if (b.dataset.sure !== "1") {
    b.dataset.sure = "1"; b.textContent = "Delete? Yes";
    setTimeout(() => { if (b.isConnected) { b.dataset.sure = ""; b.textContent = "Delete"; } }, 4000);
    return;
  }
  api(`/api/watchlists/${encodeURIComponent(name)}`, null, "DELETE")
    .then(() => { say("cfgStatus", `Deleted "${name}".`); return reload(); })
    .catch((e) => say("cfgStatus", e.message, true));
}

// ---------------------------------------------------------------- watch list columns
const COL = (id) => cfg.watch_columns.columns.find((c) => c.id === id);
const canShow = (c) => c.lists === "all" || c.lists === kind;

function renderColumns() {
  const kinds = $("cfgKinds");
  kinds.innerHTML = "";
  for (const [k, label] of KINDS) {
    const b = btn(label, () => { kind = k; renderColumns(); }, null, "cfg-kind" + (k === kind ? " on" : ""));
    b.setAttribute("role", "tab"); b.setAttribute("aria-selected", k === kind ? "true" : "false");
    kinds.appendChild(b);
  }
  const chosen = cfg.watch_columns.defaults[kind];
  const factory = cfg.watch_columns.factory[kind];
  const ol = $("cfgChosen");
  ol.innerHTML = "";
  chosen.forEach((id, i) => {
    const c = COL(id) || { label: id };
    const li = el("li", "cfg-col");
    li.dataset.id = id;
    li.appendChild(el("span", "cfg-col-name", c.label));
    if (id !== "symbol") {
      const move = (d) => {                                   // from the order now: clicks can come faster than saves
        const now = cfg.watch_columns.defaults[kind], at = now.indexOf(id);
        if (at > 0 && at + d >= 1 && at + d < now.length) setColumns(swap(now, at, at + d));
      };
      const up = btn("▲", () => move(-1), `Move ${c.label} left`, "cfg-up"); up.disabled = i <= 1;
      const down = btn("▼", () => move(1), `Move ${c.label} right`, "cfg-down"); down.disabled = i === chosen.length - 1;
      li.append(up, down, btn("×", () => setColumns(cfg.watch_columns.defaults[kind].filter((x) => x !== id)), `Remove ${c.label}`, "cfg-remove"));
    }
    ol.appendChild(li);
  });
  const avail = $("cfgAvail");
  avail.innerHTML = "";
  for (const c of cfg.watch_columns.columns.filter((x) => canShow(x) && !chosen.includes(x.id))) {
    const b = btn("+ " + c.label, () => setColumns([...cfg.watch_columns.defaults[kind], c.id]), c.tip || c.label, "cfg-add");
    b.dataset.id = c.id;
    avail.appendChild(b);
  }
  $("cfgColsReset").disabled = chosen.join() === factory.join();
}

const swap = (a, i, j) => { const b = [...a]; [b[i], b[j]] = [b[j], b[i]]; return b; };

// shown at once, saved in order: each save waits for the one before, so the last click is what's kept
let saving = Promise.resolve();
function setColumns(ids) {
  const k = kind;
  cfg.watch_columns = { ...cfg.watch_columns, defaults: { ...cfg.watch_columns.defaults, [k]: ids } };
  renderColumns();
  saving = saving.then(async () => {
    try {
      const r = await api(`/api/config/watch-columns/${k}`, ids.filter((x) => x !== "symbol"), "PUT");
      if (cfg.watch_columns.defaults[k] === ids) { cfg.watch_columns = r; renderColumns(); }   // nothing newer since
      say("cfgColsMsg", "Saved.");
    } catch (e) { say("cfgColsMsg", e.message, true); }
  });
  return saving;
}

// ---------------------------------------------------------------- study defaults
function renderStudyList() {
  const ul = $("cfgStudyList"), q = $("cfgFind").value.trim().toLowerCase();
  ul.innerHTML = "";
  let cat = null;
  for (const s of cfg.studies.filter((x) => !q || x.name.toLowerCase().includes(q))) {
    if (s.category !== cat) { cat = s.category; ul.appendChild(el("li", "cfg-cat", cat)); }
    const li = el("li");
    const b = btn(s.name + (s.customized.length ? " •" : ""), () => showStudy(s.type), s.customized.length
      ? `Your defaults: ${s.customized.join(", ")}` : "Built-in defaults", "cfg-study" + (s.type === study ? " on" : ""));
    b.dataset.type = s.type;
    li.appendChild(b);
    ul.appendChild(li);
  }
}

function showStudy(type) {
  study = type;
  const s = cfg.studies.find((x) => x.type === type);
  if (!s) return;
  $("cfgStudyName").textContent = s.name;
  $("cfgStudyDesc").textContent = s.description || "";
  fillForm($("cfgStudyForm"), s.params, Object.fromEntries(s.params.map((p) => [p.key, p.default])));
  $("cfgStudyReset").disabled = !s.customized.length;
  say("cfgStudyMsg", s.customized.length ? `Your defaults for: ${s.customized.join(", ")}.` : "Built-in defaults.");
  renderStudyList();
  $("sec-studies").querySelector(".cfg-sform").hidden = false;
}

async function saveStudy() {
  if (!study) return;
  try {
    const s = await api(`/api/config/studies/${study}`, readForm($("cfgStudyForm")), "PUT");
    cfg.studies = cfg.studies.map((x) => (x.type === study ? s : x));
    showStudy(study);
    say("cfgStudyMsg", s.customized.length ? `Saved. New ${s.name} studies start with these settings.` : "Saved: the same as the built-in defaults.");
  } catch (e) { say("cfgStudyMsg", e.message, true); }
}

async function resetStudy() {
  if (!study) return;
  await api(`/api/config/studies/${study}`, null, "DELETE").catch((e) => say("cfgStudyMsg", e.message, true));
  await reload();
  say("cfgStudyMsg", "Back to the built-in defaults.");
}

// ---------------------------------------------------------------- sections
function showSection(sec) {
  for (const b of document.querySelectorAll(".cfg-tabs button")) {
    const on = b.dataset.sec === sec;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false");
    $("sec-" + b.dataset.sec).hidden = !on;
  }
  store(TAB_KEY, sec);
  if (sec === "backtests" && cfg) loadBacktestDefaults(say).catch((e) => say("cfgBtMsg", e.message, true));   // accounts may have changed
}

for (const b of document.querySelectorAll(".cfg-tabs button")) b.onclick = () => showSection(b.dataset.sec);
$("cfgColsReset").onclick = async () => {
  cfg.watch_columns = await api(`/api/config/watch-columns/${kind}`, null, "DELETE");
  say("cfgColsMsg", "Back to the built-in columns."); renderColumns();
};
$("cfgFind").oninput = renderStudyList;
$("cfgStudySave").onclick = saveStudy;
$("cfgStudyReset").onclick = resetStudy;
$("cfgStudyForm").onsubmit = (e) => { e.preventDefault(); saveStudy(); };
$("sec-studies").querySelector(".cfg-sform").hidden = true;

initPaper(say);
initRules(sayRule);
initStrategies(sayStrat);
for (const a of document.querySelectorAll("a[data-goto]")) a.onclick = (e) => { e.preventDefault(); showSection(a.dataset.goto); };
initBacktestDefaults(say);
initDashboards();
// the section asked for in the address (?tab=dashboards), else the last one shown in this browser
const SECTIONS = [...document.querySelectorAll(".cfg-tabs button")].map((b) => b.dataset.sec);
const asked = new URLSearchParams(location.search).get("tab");
showSection(SECTIONS.includes(asked) ? asked : SECTIONS.includes(load(TAB_KEY)) ? load(TAB_KEY) : "dashboards");
if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();   // e.g. #environment: shown now
reload().catch((e) => say("cfgStatus", "Error: " + e.message, true));
