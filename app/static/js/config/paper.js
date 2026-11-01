/* The Config page's Paper accounts section: the named paper accounts (new, rename, reset, delete) and the
   settings of each, or of new accounts (the defaults): starting cash, commissions, slippage, shorting.
   Data: /api/paper/accounts, /api/paper/defaults. Simulated on the NAS; nothing here talks to the broker. */
import { fillForm, readForm } from "../settings-form.js";
import { $, api, btn, el } from "../util.js";

const NEW = "\u0000new";                                   // the settings menu's entry for new accounts
// the settings form's fields (settings-form.js)
const PARAMS = [
  { key: "start_cash", label: "Starting cash ($)", type: "float", min: 100, max: 100000000, step: 1000, section: "Account" },
  { key: "per_share", label: "Commission per share ($)", type: "float", min: 0, max: 1, step: 0.001, section: "Commission (IBKR Fixed by default)" },
  { key: "minimum", label: "Minimum per order ($)", type: "float", min: 0, max: 100, step: 0.5, section: "Commission (IBKR Fixed by default)" },
  { key: "max_pct", label: "At most, % of the trade's value", type: "float", min: 0, max: 100, step: 0.5, section: "Commission (IBKR Fixed by default)" },
  { key: "slippage", label: "Slippage per share ($), on market and stop fills", type: "float", min: 0, max: 10, step: 0.01, section: "Fills" },
  { key: "shorting", label: "Allow short selling", type: "bool", section: "Fills" },
];
const flat = (a) => ({ start_cash: a.start_cash, ...a.settings.commission, slippage: a.settings.slippage, shorting: a.settings.shorting });
const nested = (v) => ({ start_cash: v.start_cash, settings: { commission: { per_share: v.per_share, minimum: v.minimum, max_pct: v.max_pct },
                                                              slippage: v.slippage, shorting: v.shorting } });
const money = (x) => "$" + Math.round(x).toLocaleString("en-US");
const enc = encodeURIComponent;

let data = null, target = NEW;

export async function loadPaper(say) {
  data = await api("/api/paper/accounts");
  renderAccounts(say);
  renderSettings(say);
}

function renderAccounts(say) {
  const t = $("cfgPaper");
  t.innerHTML = "";
  const head = el("tr");
  for (const h of ["Name", "Starting cash", "Balance", "Settings", ""]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  const names = Object.keys(data.accounts).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  if (!names.length) {
    const td = el("td", "muted", "No paper accounts yet: New account makes one."); td.colSpan = 5;
    t.appendChild(el("tr")).appendChild(td);
  }
  for (const name of names) {
    const a = data.accounts[name], s = a.settings;
    const tr = el("tr");
    tr.dataset.name = name;
    const nameTd = el("td", "cfg-name", name);
    const what = `$${s.commission.per_share}/share (min $${s.commission.minimum}), slippage $${s.slippage}` + (s.shorting ? ", shorting" : ", long only");
    const acts = el("td", "cfg-acts");
    acts.append(btn("Settings", () => { target = name; renderSettings(say); $("cfgPaperForm").scrollIntoView({ block: "nearest" }); },
                    `Settings of "${name}"`, "cfg-psettings"),
                btn("Rename", () => rename(nameTd, name, say), `Rename "${name}"`, "cfg-rename"),
                twoClicks("Reset", "Reset? Yes", `Reset "${name}" to its starting cash`, () => post(`/api/paper/accounts/${enc(name)}/reset`, null, `Reset "${name}" to ${money(a.start_cash)}.`, say)),
                twoClicks("Delete", "Delete? Yes", `Delete "${name}"`, () => post(`/api/paper/accounts/${enc(name)}`, "DELETE", `Deleted "${name}".`, say), "danger"));
    tr.append(nameTd, el("td", null, money(a.start_cash)), el("td", a.balance >= a.start_cash ? "up" : "down", money(a.balance)),
              el("td", "muted small", what), acts);
    t.appendChild(tr);
  }
}

// a button that asks first, without a browser dialog: the first click changes its label, the second does it
function twoClicks(label, sure, title, fn, cls = "") {
  const b = btn(label, (e) => {
    const me = e.currentTarget;
    if (me.dataset.sure !== "1") {
      me.dataset.sure = "1"; me.textContent = sure;
      setTimeout(() => { if (me.isConnected) { me.dataset.sure = ""; me.textContent = label; } }, 4000);
      return;
    }
    fn();
  }, title, cls);
  return b;
}

async function post(url, method, done, say) {
  try { await api(url, method ? null : {}, method || "POST"); say("cfgPaperMsg", done); }
  catch (e) { say("cfgPaperMsg", e.message, true); }
  await loadPaper(say);
}

function rename(td, name, say) {
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
      try {
        await api(`/api/paper/accounts/${enc(name)}/rename`, { to });
        if (target === name) target = to;
        say("cfgPaperMsg", `Renamed "${name}" to "${to}".`);
      } catch (e) { say("cfgPaperMsg", e.message, true); }
    }
    await loadPaper(say);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); };
  input.onblur = () => finish(true);
}

// the settings form: of new accounts (the defaults) or of one account
function renderSettings(say) {
  if (target !== NEW && !data.accounts[target]) target = NEW;
  const sel = $("cfgPaperFor");
  sel.innerHTML = "";
  const add = (v, t) => { const o = el("option", null, t); o.value = v; sel.appendChild(o); };
  add(NEW, "New accounts (the defaults)");
  for (const n of Object.keys(data.accounts).sort()) add(n, n);
  sel.value = target;
  const values = flat(target === NEW ? data.defaults : data.accounts[target]);
  fillForm($("cfgPaperForm"), PARAMS, values);
  $("cfgPaperReset").hidden = target !== NEW;
  $("cfgPaperNote").textContent = target === NEW
    ? "What a new account starts with."
    : `Changes apply to "${target}" from now on; its history is kept. Starting cash changes its balance by the difference.`;
}

async function saveSettings(say) {
  const body = nested(readForm($("cfgPaperForm")));
  try {
    if (target === NEW) await api("/api/paper/defaults", body, "PUT");
    else await api(`/api/paper/accounts/${enc(target)}`, body, "PUT");
    say("cfgPaperMsg", target === NEW ? "Saved the defaults for new accounts." : `Saved "${target}".`);
  } catch (e) { say("cfgPaperMsg", e.message, true); return; }
  await loadPaper(say);
}

export function initPaper(say) {
  $("cfgPaperNew").onclick = async () => {
    try { const r = await api("/api/paper/accounts", {}); target = r.name; say("cfgPaperMsg", `Made "${r.name}" with ${money(r.item.start_cash)}.`); }
    catch (e) { say("cfgPaperMsg", e.message, true); }
    await loadPaper(say);
  };
  $("cfgPaperFor").onchange = (e) => { target = e.target.value; renderSettings(say); };
  $("cfgPaperSave").onclick = () => saveSettings(say);
  $("cfgPaperForm").onsubmit = (e) => { e.preventDefault(); saveSettings(say); };
  $("cfgPaperReset").onclick = async () => {
    try { data.defaults = await api("/api/paper/defaults", null, "DELETE"); say("cfgPaperMsg", "Back to the built-in defaults."); }
    catch (e) { say("cfgPaperMsg", e.message, true); }
    renderSettings(say);
  };
}
