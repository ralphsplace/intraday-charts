/* The Config page's Backtesting accounts section: the named accounts backtests run with (new, rename, delete) and
   the settings of each, or of new accounts (the defaults): starting cash, commissions, slippage, shorting.
   Data: /api/backtest-accounts, /api/backtest-account-defaults. Simulated on the NAS; nothing here talks to the broker. */
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

export async function loadAccounts(say) {
  data = await api("/api/backtest-accounts");
  renderAccounts(say);
  renderSettings(say);
}

function renderAccounts(say) {
  const t = $("cfgAcct");
  t.innerHTML = "";
  const head = el("tr");
  for (const h of ["Name", "Starting cash", "Settings", ""]) head.appendChild(el("th", null, h));
  t.appendChild(head);
  const names = Object.keys(data.accounts).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  if (!names.length) {
    const td = el("td", "muted", "No backtesting accounts yet: New account makes one (backtests run with the defaults for new accounts until then)."); td.colSpan = 4;
    t.appendChild(el("tr")).appendChild(td);
  }
  for (const name of names) {
    const a = data.accounts[name], s = a.settings;
    const tr = el("tr");
    tr.dataset.name = name;
    const nameTd = el("td", "cfg-name", name);
    const what = `$${s.commission.per_share}/share (min $${s.commission.minimum}), slippage $${s.slippage}` + (s.shorting ? ", shorting" : ", long only");
    const acts = el("td", "cfg-acts");
    acts.append(btn("Settings", () => { target = name; renderSettings(say); $("cfgAcctForm").scrollIntoView({ block: "nearest" }); },
                    `Settings of "${name}"`, "cfg-psettings"),
                btn("Rename", () => rename(nameTd, name, say), `Rename "${name}"`, "cfg-rename"),
                twoClicks("Delete", "Delete? Yes", `Delete "${name}"`, () => post(`/api/backtest-accounts/${enc(name)}`, "DELETE", `Deleted "${name}".`, say), "danger"));
    tr.append(nameTd, el("td", null, money(a.start_cash)), el("td", "muted small", what), acts);
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
  try { await api(url, method ? null : {}, method || "POST"); say("cfgAcctMsg", done); }
  catch (e) { say("cfgAcctMsg", e.message, true); }
  await loadAccounts(say);
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
        await api(`/api/backtest-accounts/${enc(name)}/rename`, { to });
        if (target === name) target = to;
        say("cfgAcctMsg", `Renamed "${name}" to "${to}".`);
      } catch (e) { say("cfgAcctMsg", e.message, true); }
    }
    await loadAccounts(say);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); };
  input.onblur = () => finish(true);
}

// the settings form: of new accounts (the defaults) or of one account
function renderSettings(say) {
  if (target !== NEW && !data.accounts[target]) target = NEW;
  const sel = $("cfgAcctFor");
  sel.innerHTML = "";
  const add = (v, t) => { const o = el("option", null, t); o.value = v; sel.appendChild(o); };
  add(NEW, "New accounts (the defaults)");
  for (const n of Object.keys(data.accounts).sort()) add(n, n);
  sel.value = target;
  const values = flat(target === NEW ? data.defaults : data.accounts[target]);
  fillForm($("cfgAcctForm"), PARAMS, values);
  $("cfgAcctReset").hidden = target !== NEW;
  $("cfgAcctNote").textContent = target === NEW
    ? "What a new account starts with."
    : `Changes apply to "${target}" in backtests started from now on.`;
}

async function saveSettings(say) {
  const body = nested(readForm($("cfgAcctForm")));
  try {
    if (target === NEW) await api("/api/backtest-account-defaults", body, "PUT");
    else await api(`/api/backtest-accounts/${enc(target)}`, body, "PUT");
    say("cfgAcctMsg", target === NEW ? "Saved the defaults for new accounts." : `Saved "${target}".`);
  } catch (e) { say("cfgAcctMsg", e.message, true); return; }
  await loadAccounts(say);
}

export function initAccounts(say) {
  $("cfgAcctNew").onclick = async () => {
    try { const r = await api("/api/backtest-accounts", {}); target = r.name; say("cfgAcctMsg", `Made "${r.name}" with ${money(r.item.start_cash)}.`); }
    catch (e) { say("cfgAcctMsg", e.message, true); }
    await loadAccounts(say);
  };
  $("cfgAcctFor").onchange = (e) => { target = e.target.value; renderSettings(say); };
  $("cfgAcctSave").onclick = () => saveSettings(say);
  $("cfgAcctForm").onsubmit = (e) => { e.preventDefault(); saveSettings(say); };
  $("cfgAcctReset").onclick = async () => {
    try { data.defaults = await api("/api/backtest-account-defaults", null, "DELETE"); say("cfgAcctMsg", "Back to the built-in defaults."); }
    catch (e) { say("cfgAcctMsg", e.message, true); }
    renderSettings(say);
  };
}
