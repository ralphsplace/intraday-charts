/* A trade panel in the grid, for the symbol of its link group (links.js), or of the active chart when it isn't
   linked. Replay practice is gone (#83); orders to the IBKR paper account come next (#84).
   Until then it shows the symbol it follows, and says so. */
import { toggleMaximize } from "./grid.js";
import { linkControl, members } from "./links.js";
import { openCellMenu } from "./saved.js";
import { app } from "./state.js";
import { btn, el, uid } from "./util.js";

export class TradePanel {
  constructor(cfg, index) {
    this.index = index;
    this.id = cfg.id || uid();
    this.link = cfg.link || "";
    this.symbol = null;
    this.buildDom();
    this.follow();
  }

  config() { return { kind: "trade", id: this.id, link: this.link }; }
  destroy() { this.dead = true; this.root.remove(); }

  // the chart it follows: the first chart of its link group, or the active chart
  chart() {
    if (this.link) return members(this).find((c) => c.setSymbol) || null;
    return app.active || app.panels[0] || null;
  }

  buildDom() {
    const root = this.root = el("section", "panel tp");
    root.dataset.cell = "trade";
    const head = el("div", "phead");
    head.appendChild(el("b", "tptitle", "Trade"));
    this.symEl = el("b", "tpsym", "–");
    const linkB = linkControl(this, () => this.follow());
    const menuB = btn("≡", (e) => openCellMenu(e.currentTarget, this), "Trade panel menu", "viewsbtn");
    menuB.title = "Add a chart, watch list or trade panel next to it, or remove it";
    this.maxBtn = btn("⤢", () => toggleMaximize(this), "Maximize this trade panel", "maxbtn");
    head.append(this.symEl, linkB, el("span", "wlgrow"), menuB, this.maxBtn);
    this.notice = el("div", "tpnotice muted small",
      "Orders to your IBKR paper account will be placed from here (the next change). Replay practice is gone; backtests run on the Backtesting page.");
    root.append(head, this.notice);
  }

  follow() { this.setSymbol(this.chart()?.symbol || this.symbol); }
  setSymbol(sym) {
    if (!sym || sym === this.symbol) return;
    this.symbol = sym;
    this.symEl.textContent = sym;
  }
  showLinked(sym) { this.setSymbol(sym); }
  linksChanged() { this.follow(); }
  activeChanged() { if (!this.link) this.follow(); }
  refresh() {}
}
