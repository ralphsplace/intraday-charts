/* One tab of a watch list panel: which named watch list it shows (lists.js), its columns, heat and sorting, and
   its rows. A panel holds any number of tabs (watchlist.js); only the one on view fetches.

   The list itself is app-wide and kept on the NAS; the tab refers to it by id (and name), so renaming the list
   anywhere renames the tab. A list's source decides where its symbols come from:
     symbols     typed or imported symbols
     finviz      a FinViz screen or portfolio (feed.js)
     holdings    the account's stock and ETF positions (app/positions.py; HOLDINGS=on in .env)
   Rows come from /api/quotes, or /api/positions for holdings (the quote columns plus the position's). */
import { ago } from "./data.js";
import { columnsFor, sortValue } from "./columns.js";
import { Feed } from "./feed.js";
import * as lists from "./lists.js";
import { app } from "./state.js";
import { api, el, orElse, uid } from "./util.js";

export const MAX_SYMBOLS = 100;

export class WatchTab {
  // cfg: a tab's saved settings; changed(): its symbols or status changed (the watch list redraws)
  constructor(cfg, changed) {
    this.id = cfg.id || uid();
    this.listId = cfg.listId || null;
    this.list = cfg.list || "";                                          // the list's name when last seen
    this.columns = Array.isArray(cfg.columns) ? cfg.columns : null;      // null: the default set
    this.heat = Array.isArray(cfg.heat) ? cfg.heat : [];                  // columns shaded by value
    this.sort = cfg.sort && typeof cfg.sort.id === "string" ? { id: cfg.sort.id, dir: cfg.sort.dir === -1 ? -1 : 1 } : null;
    this.feed = new Feed(null, changed);
    this.changed = changed;
    this.rows = []; this.held = null; this.seq = 0;
    // tabs saved before lists were named and app-wide: their own symbols, a FinViz screen or the holdings
    if (!cfg.listId && (["", "@feed", "@holdings"].includes(this.list) || cfg.symbols?.length)) this.legacy = cfg;
    this.resolve();
  }

  config() {
    const old = this.legacy ? { symbols: this.legacy.symbols, feed: this.legacy.feed } : {};   // until it's moved
    return { id: this.id, listId: this.listId, list: this.list, columns: this.columns, heat: this.heat, sort: this.sort, ...old };
  }

  // the named list this tab shows (found by id first: it may have been renamed elsewhere); null when deleted
  resolve() {
    const [name, item] = lists.find(this.listId, this.list);
    this.item = item;
    if (name) { this.list = name; this.listId = item.id || this.listId; }
    if (item?.source === "finviz" && item.feed?.address !== this.feed.address) this.feed.configure(item.feed);
    return item;
  }

  // a tab saved before named lists: becomes a named list of its own ("Watch list N"), once
  async migrate() {
    const cfg = this.legacy;
    if (!cfg || app.listsUnknown) return;                 // the lists didn't load: try again on the next page load
    const source = cfg.list === "@feed" ? "finviz" : cfg.list === "@holdings" ? "holdings" : "symbols";
    if (source === "finviz" && !cfg.feed?.address) { delete this.legacy; return; }
    const r = await orElse(lists.create(source, source === "symbols" ? { symbols: cfg.symbols || [] } : source === "finviz" ? { feed: cfg.feed } : {},
                                        cfg.name && cfg.name !== "Watch list" && !app.saved.watchlists[cfg.name] ? cfg.name : undefined),
                           null, "Moving an old watch list tab to a named list");   // "Watch list" was the old default: numbered
    if (!r) return;                                        // kept, so nothing the tab held is lost
    delete this.legacy;
    this.list = r.name; this.listId = r.item.id; this.resolve();
  }

  source() { return this.item?.source || "symbols"; }
  kind() { return this.source() === "holdings" ? "holding" : this.source() === "finviz" ? "finviz" : "quote"; }
  shownColumns() { return columnsFor(this.kind(), this.columns); }
  label() { return this.list || "Watch list"; }

  // the list's symbols in its own order
  listed() {
    if (!this.item) return [];
    if (this.source() === "finviz") return this.feed.symbols.slice(0, MAX_SYMBOLS);
    if (this.source() === "holdings") return (this.held?.rows || []).map((r) => r.symbol);
    return (this.item.symbols || []).slice(0, MAX_SYMBOLS);
  }

  // the symbols as shown: sorted by the chosen column (rows without a value last), or in the list's order
  shown() {
    const list = this.listed();
    if (!this.sort || !this.shownColumns().includes(this.sort.id)) return list;
    const byS = Object.fromEntries(this.rows.map((r) => [r.symbol, r]));
    const { id, dir } = this.sort;
    const key = (s) => sortValue(id, byS[s] || { symbol: s });
    return list.map((s, i) => [s, key(s), i]).sort((a, b) => {
      if (a[1] == null || b[1] == null) return (a[1] == null) - (b[1] == null) || a[2] - b[2];
      if (typeof a[1] !== typeof b[1]) return typeof a[1] === "number" ? -1 : 1;
      return (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : a[2] - b[2]) * dir;
    }).map((x) => x[0]);
  }

  // a column dragged onto another: it takes that column's place (Symbol stays first)
  moveColumn(from, to) {
    const cols = this.shownColumns().filter((c) => c !== "symbol" && c !== from);
    const at = to === "symbol" ? 0 : cols.indexOf(to) + (this.shownColumns().indexOf(from) < this.shownColumns().indexOf(to) ? 1 : 0);
    cols.splice(Math.max(0, at), 0, from);
    this.columns = cols;
  }

  // a click on a column's header: ascending, descending, then the list's own order
  toggleSort(id) {
    if (!this.sort || this.sort.id !== id) this.sort = { id, dir: 1 };
    else if (this.sort.dir === 1) this.sort = { id, dir: -1 };
    else this.sort = null;
  }

  start() { if (this.source() === "finviz") this.feed.load(); }
  stop() { this.feed.stop(); }

  // the rows for the day on screen (up to the Replay cursor); false when a newer fetch overtook this one
  async fetchRows() {
    const mine = ++this.seq;
    if (!app.day) { this.rows = []; return true; }
    const cursor = app.live || app.cursor == null ? "" : `&cursor=${app.cursor}`;
    const cols = `&cols=${this.shownColumns().join(",")}`;
    if (this.item && this.source() === "holdings") {
      const r = await api(`/api/positions?day=${app.day}${cursor}${cols}`);
      if (mine !== this.seq) return false;
      this.held = r; this.rows = r.rows || [];
      return true;
    }
    if (this.source() === "finviz") this.feed.load();      // throttled: only when the list is due
    const list = this.listed();
    if (!list.length) { this.rows = []; return true; }
    const r = await api(`/api/quotes?symbols=${encodeURIComponent(list.join(","))}&day=${app.day}${cursor}${cols}`);
    if (mine !== this.seq) return false;
    const extra = this.source() === "finviz" ? this.feed.fields : {};      // FinViz's own columns
    this.rows = r.items.map((x) => ({ ...(extra[x.symbol] || {}), ...x }));
    return true;
  }

  // the footer's line about the source: FinViz's status, or the holdings' totals and age
  status() {
    if (this.legacy) return null;                         // becoming a named list
    if (!this.item && app.listsUnknown) return el("span", "wlfeed bad", "The watch lists couldn't be loaded: the note in the corner says why. Reload the page once it's fixed.");
    if (!this.item) return el("span", "wlfeed bad", `The watch list "${this.list}" was deleted: pick another in the menu.`);
    if (this.source() === "finviz") return this.feed.status(MAX_SYMBOLS);
    if (this.source() !== "holdings" || !this.held) return null;
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
    if (!this.item || this.source() !== "symbols") return "";
    return "No symbols: press Edit.";
  }
}

// a tab showing the named list `name` (with its id), and a panel saved before tabs existed (its own settings)
export const tabConfig = (name, listId) => ({ id: uid(), list: name, listId, columns: null });
export const legacyTab = (cfg) => ({ id: uid(), name: "", list: cfg.list || "", symbols: cfg.symbols || [], columns: null, feed: cfg.feed || null });
