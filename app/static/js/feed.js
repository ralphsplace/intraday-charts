/* A watch list's outside source (a FinViz screen or portfolio): asks the server for the symbols the collector
   fetched, has them fetched again when due, and says how things stand. The server decides what's due and checks
   every address; the source's sign-in token never reaches the page. Data: /api/lists/source. */
import { ago } from "./format.js";
import { api, btn, el } from "./util.js";

const CHECK_MS = 60_000;       // a list on screen asks this often whether it's due (FinViz itself: every 15 minutes)
const WAIT_MS = 3000;          // after asking the collector: look for its answer this often…
const WAIT_TRIES = 20;         // …this many times (a minute)

export class Feed {
  // cfg: {source, address, label} as saved, or nothing; changed(): the symbols or the status changed
  constructor(cfg, changed) {
    this.source = cfg?.source || "finviz";
    this.address = cfg?.address || "";
    this.label = cfg?.label || "";
    this.changed = changed;
    this.symbols = []; this.fields = {}; this.view = null; this.error = ""; this.waiting = false; this.noAnswer = false;
    this.checked = 0; this.timer = null;
  }

  config() { return this.address ? { source: this.source, address: this.address, label: this.label } : null; }
  // the list's FinViz address changed (or the tab was opened): start over from it
  configure(cfg) {
    this.stop();
    this.source = cfg?.source || "finviz"; this.address = cfg?.address || ""; this.label = cfg?.label || "";
    this.symbols = []; this.fields = {}; this.view = null; this.checked = 0;
  }
  stop() { clearTimeout(this.timer); this.timer = null; this.waiting = false; }

  ask(address, opts) {
    return api("/api/lists/source", { source: this.source, address, refresh: !!opts.refresh, ask: opts.ask !== false });
  }

  // a new address: checked by the server, then fetched; returns an error message for the editor, or ""
  async set(address) {
    let v;
    try { v = await this.ask(address, { refresh: true }); } catch (e) { return e.message; }
    this.symbols = [];
    this.take(v);
    if (v.requested) this.wait(v);
    return "";
  }

  // when on screen: at most once a minute, the server says whether the list is due and asks the collector if so
  load(force = false) {
    if (!this.address || this.waiting || (!force && Date.now() - this.checked < CHECK_MS)) return;
    this.checked = Date.now();
    this.fetch(force);
  }

  async fetch(refresh) {
    let v;
    try { v = await this.ask(this.address, { refresh }); } catch (e) { this.error = e.message; this.changed(); return; }
    this.take(v);
    if (v.requested) this.wait(v);
  }

  take(v) {
    this.view = v; this.error = "";
    this.address = v.address; this.label = v.label;
    if (v.status === "ok") { this.symbols = v.symbols; this.fields = v.fields || {}; }      // on an error, the last ones stay
    this.changed();
  }

  // the collector was asked: look for an answer newer than the one there was
  wait(v) {
    this.stop();
    const before = v.fetched || 0;
    let n = 0;
    const tick = async () => {
      if (!this.waiting) return;
      if (++n > WAIT_TRIES) { this.waiting = false; this.noAnswer = true; this.changed(); return; }
      try {
        const r = await this.ask(this.address, { ask: false });
        if (!this.waiting) return;
        if ((r.fetched || 0) > before) { this.waiting = false; this.noAnswer = false; this.take(r); return; }
      } catch { /* try again */ }
      this.timer = setTimeout(tick, WAIT_MS);
    };
    this.waiting = true; this.noAnswer = false;
    this.changed();
    this.timer = setTimeout(tick, WAIT_MS);
  }

  // the watch list's footer line for this source
  status(max) {
    const box = el("span", "wlfeed");
    const v = this.view;
    const name = v?.source_name || "FinViz";
    if (this.label) {
      const a = el("a", "wlfeedlabel", this.label);
      a.href = this.address; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.title = `Open it on ${name}`;
      box.appendChild(a);
    }
    let say = "";
    if (this.error) say = this.error;
    else if (this.waiting) say = `Asking ${name}…`;
    else if (this.noAnswer) say = "No answer yet: is the TWS collector running?";
    else if (v?.status === "off") say = `${name} lists are off: set FINVIZ_TOKEN in .env, then restart the collector.`;
    else if (v?.status === "error") say = v.message || `${name} didn't send the list.`;
    else if (v?.status === "ok") {
      say = `fetched ${ago(v.age)}`;
      if ((v.total || 0) > max) say += `, showing the first ${max} of ${v.total}`;
    }
    if (say) box.appendChild(el("span", v?.status === "error" || this.error ? "bad" : null, say));
    if (this.address && !this.waiting) {
      const b = btn("Refresh list", () => this.load(true), `Fetch the list from ${name} again now`, "wlrefresh");
      box.appendChild(b);
    }
    return box;
  }
}
