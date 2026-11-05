/* A signal strategy on a chart (mixed into Panel; app/signals/chart.py, /api/signal-strategies/<name>/chart): its
   entries and exits as arrows on this chart's bars, for any symbol and day, as a backtest would have traded them
   bar by bar. Signals only: nothing is traded. Chosen in the chart's ≡ menu (signalsSection); a strip under the
   header names the strategy and how many trades it made, with × to take it off. In Replay, only what had happened
   before the cursor. */
import { app, save } from "./state.js";
import { api, btn, el } from "./util.js";

const enc = encodeURIComponent;

export class ChartSignals {
  buildSignals() {
    this.sigBar = el("div", "sigbar"); this.sigBar.hidden = true;
    this.sigInfo = el("span", "siginfo");
    const off = btn("×", () => this.setSignals(""), "Take the signals off this chart", "sigoff");
    this.sigBar.append(el("b", "sigtag", "Signals"), this.sigInfo, el("span", "wlgrow"), off);
    return this.sigBar;
  }

  setSignals(name) {
    this.signals = name || "";
    this.sigKey = null;
    save();
    if (!this.signals) { this.markers = null; this.sigBar.hidden = true; this.renderMarkers(); return; }
    if (this.view) this.signalsRefresh(this.view);
  }

  // after every render: the arrows for this chart's symbol, day, bars and cursor (asked again only when one changed)
  async signalsRefresh(v) {
    this.sigBar.hidden = !this.signals;
    if (!this.signals) return;
    if (v.period) { this.sigInfo.textContent = `${this.signals}: signals show on minute charts`; this.markers = null; this.renderMarkers(); return; }
    const cursor = app.live ? null : v.cursor ?? null;
    const last = v.bars.length ? v.bars[v.bars.length - 1].time : 0;
    const key = [this.signals, v.symbol, app.day, this.tf, cursor, last].join("|");
    if (key === this.sigKey) return;
    this.sigKey = key;
    const q = `symbol=${enc(v.symbol)}&day=${enc(app.day)}&tf=${this.tf}` + (cursor != null ? `&cursor=${cursor}` : "");
    let r;
    try { r = await api(`/api/signal-strategies/${enc(this.signals)}/chart?${q}`); }
    catch (e) { if (key === this.sigKey) { this.sigInfo.textContent = `${this.signals}: ${e.message}`; this.markers = null; this.renderMarkers(); } return; }
    if (key !== this.sigKey || this.dead) return;
    this.markers = r.markers;
    this.sigShown = key;                                  // the arrows on screen are for this (the tests wait on it)
    this.sigInfo.textContent = `${r.strategy_name} · ${r.trades} trade${r.trades === 1 ? "" : "s"} ${cursor != null ? "so far " : ""}today`;
    this.renderMarkers();
  }

  signalsConfig() { return this.signals ? { signals: this.signals } : {}; }
}

// the chart's ≡ menu: which signal strategy's entries and exits it shows
export async function signalsSection(panel) {
  const box = el("div", "msignals");
  box.appendChild(el("div", "mtitle", "Signals (a signal strategy's entries and exits)"));
  const sel = el("select", "sigsel");
  sel.setAttribute("aria-label", "Signal strategy shown on this chart");
  sel.title = "A signal strategy's entries and exits as arrows on this chart (signals only: nothing is traded)";
  const add = (v, t) => { const o = el("option", null, t); o.value = v; sel.appendChild(o); };
  add("", "None");
  let names = [];
  try { names = Object.keys((await api("/api/signal-strategies")).strategies); }
  catch (e) { box.appendChild(el("div", "muted small", "Signal strategies: " + e.message)); }
  for (const n of names.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))) add(n, n);
  if (panel.signals && !names.includes(panel.signals)) add(panel.signals, `${panel.signals} (no longer exists)`);
  sel.value = panel.signals || "";
  sel.onchange = () => panel.setSignals(sel.value);
  box.appendChild(sel);
  const link = el("a", "small", names.length ? "Signal strategies…" : "Make a signal strategy…");
  link.href = "/config?tab=strategies"; link.target = "_blank";
  box.appendChild(link);
  return box;
}
