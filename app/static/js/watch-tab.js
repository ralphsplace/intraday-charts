/* One tab of a watch list: where its symbols come from, its columns, and its rows. A watch list holds any
   number of tabs (watchlist.js); only the one on view fetches.

   Sources (the list menu's values):
     ""            its own list of symbols
     <name>        a watch list saved under Load data…
     FEED          a FinViz screen or portfolio (feed.js)
     HOLDINGS      the account's stock and ETF positions (app/positions.py; HOLDINGS=on in .env)
   Rows come from /api/quotes, or /api/positions for Holdings (the quote columns plus the position's). */
import { ago } from "./data.js";
import { columnsFor } from "./columns.js";
import { Feed } from "./feed.js";
import { app } from "./state.js";
import { api, btn, el, uid } from "./util.js";

export const FEED = "@feed";
export const HOLDINGS = "@holdings";
export const MAX_SYMBOLS = 100;

export class WatchTab {
  // cfg: a tab's saved settings; changed(): its symbols or status changed (the watch list redraws)
  constructor(cfg, changed) {
    this.id = cfg.id || uid();
    this.name = (cfg.name || "").slice(0, 24);
    this.symbols = Array.isArray(cfg.symbols) ? cfg.symbols.slice(0, MAX_SYMBOLS) : [];
    this.list = cfg.list || "";
    this.columns = Array.isArray(cfg.columns) ? cfg.columns : null;      // null: the default set
    this.feed = new Feed(cfg.feed, changed);
    this.changed = changed;
    this.rows = []; this.held = null; this.seq = 0;
  }

  config() {
    return { id: this.id, name: this.name, list: this.list, symbols: this.symbols, columns: this.columns, feed: this.feed.config() };
  }

  kind() { return this.list === HOLDINGS ? "holding" : "quote"; }
  shownColumns() { return columnsFor(this.kind(), this.columns); }

  // the tab's name: its own, or what it shows
  label() {
    if (this.name) return this.name;
    if (this.list === HOLDINGS) return "Holdings";
    if (this.list === FEED) return "FinViz";
    return this.list || "Watch list";
  }

  shown() {
    if (this.list === FEED) return this.feed.symbols.slice(0, MAX_SYMBOLS);
    if (this.list === HOLDINGS) return (this.held?.rows || []).map((r) => r.symbol);
    return this.list ? (app.saved.watchlists[this.list] || []) : this.symbols;
  }

  start() { if (this.list === FEED) this.feed.load(); }
  stop() { this.feed.stop(); }

  // the rows for the day on screen (up to the Replay cursor); false when a newer fetch overtook this one
  async fetchRows() {
    const mine = ++this.seq;
    if (!app.day) { this.rows = []; return true; }
    const cursor = app.live || app.cursor == null ? "" : `&cursor=${app.cursor}`;
    if (this.list === HOLDINGS) {
      const r = await api(`/api/positions?day=${app.day}${cursor}`);
      if (mine !== this.seq) return false;
      this.held = r; this.rows = r.rows || [];
      return true;
    }
    if (this.list === FEED) this.feed.load();                // throttled: only when the list is due
    const list = this.shown();
    if (!list.length) { this.rows = []; return true; }
    const r = await api(`/api/quotes?symbols=${encodeURIComponent(list.join(","))}&day=${app.day}${cursor}`);
    if (mine !== this.seq) return false;
    this.rows = r.items;
    return true;
  }

  // the footer's line about the source: FinViz's status, or the holdings' totals and age
  status() {
    if (this.list === FEED) return this.feed.status(MAX_SYMBOLS);
    if (this.list !== HOLDINGS || !this.held) return null;
    const box = el("span", "wlfeed");
    const h = this.held;
    const say = (t, cls) => box.appendChild(el("span", cls || null, t));
    if (h.status === "off") say("Holdings are off: set HOLDINGS=on in .env, then restart the collector (docs: Layouts and the watch list).");
    else if (h.status === "missing") say("No positions yet: the collector reads them in Live mode, once a minute.");
    else if (h.status === "error") say(h.message || "TWS didn't send the positions.", "bad");
    else {
      const t = h.totals || {};
      const pnl = (x) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
      say(`Value ${Math.round(t.market_value || 0).toLocaleString("en-US")}`);
      say(`Unrl ${pnl(t.unrealized)}`, t.unrealized > 0 ? "up" : t.unrealized < 0 ? "down" : null);
      say(`Day ${pnl(t.day_pnl)}`, t.day_pnl > 0 ? "up" : t.day_pnl < 0 ? "down" : null);
      const acc = (h.accounts || []).length;
      say(`positions ${ago(h.age)}${acc > 1 ? `, ${acc} accounts` : ""}${h.others ? `; ${h.others} other position${h.others === 1 ? "" : "s"} (options and others) not listed` : ""}`,
          h.stale ? "bad" : "muted");
      if (h.stale) say("(is the collector in Live?)", "bad");
    }
    return box;
  }

  // nothing to show yet: what to say
  emptyText() {
    if (this.list === FEED || this.list === HOLDINGS) return "";
    return "No symbols: press Edit.";
  }
}

// the "+" tab button's new tab, and a tab saved before tabs existed (a watch list's own settings)
export const newTabConfig = () => ({ id: uid(), name: "", list: "", symbols: [], columns: null, feed: null });
export const legacyTab = (cfg) => ({ id: uid(), name: "", list: cfg.list || "", symbols: cfg.symbols || [], columns: null, feed: cfg.feed || null });

export const tabButton = (label, onClick, title) => btn(label, onClick, title, "wltab");
