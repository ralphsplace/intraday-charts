/* A chart's header: symbol, saved views, candle duration, range, price type, studies, drawing tools, maximize. */
import { openPriceSettings } from "./dialogs/settings.js";
import { openStudies } from "./dialogs/studies.js";
import { setActive, toggleMaximize } from "./grid.js";
import { linkControl } from "./links.js";
import { openSavedMenu } from "./saved.js";
import { save } from "./state.js";
import { btn, el } from "./util.js";
import { parseTf, rangesFor, timeframeList } from "./timeframes.js";
import { PriceTypes as PT } from "./pricetypes.js";

const REPO = "https://github.com/ralphsplace/intraday-charts";

// builds the header and chart area of a Panel (mixed into Panel)
export class PanelHeader {
  buildDom() {
    const root = this.root = el("section", "panel");
    root.addEventListener("mousedown", () => setActive(this));
    const head = el("div", "phead");
    this.symIn = el("input", "sym"); this.symIn.setAttribute("aria-label", "Symbol");
    Object.assign(this.symIn, { type: "text", spellcheck: false, autocomplete: "off", maxLength: 10,
                                title: "Type any stock or ETF symbol and press Enter. Bars not cached yet are fetched from TWS." });
    this.symIn.setAttribute("list", "symList");
    this.symIn.addEventListener("focus", () => this.symIn.select());
    this.symIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this.symIn.blur(); }
      if (e.key === "Escape") { this.symIn.value = this.symbol; this.symIn.blur(); }
    });
    this.symIn.addEventListener("change", () => this.setSymbol(this.symIn.value));
    // candle duration, and the range shown (days for intraday candles, months or years for daily and longer)
    this.tfSel = el("select", "tf"); this.tfSel.setAttribute("aria-label", "Candle duration");
    this.tfSel.title = "Candle duration: minutes, or daily (1d), weekly (1w) and monthly (1M) candles";
    for (const t of timeframeList()) { const o = el("option", null, t.label); o.value = String(t.id); this.tfSel.appendChild(o); }
    this.tfSel.value = String(this.tf);
    this.tfSel.onchange = () => { this.tf = parseTf(this.tfSel.value); this.fitted = false; this.fillRanges(); save(); this.refresh(); };
    this.daysSel = el("select", "days"); this.daysSel.setAttribute("aria-label", "Range shown");
    this.fillRanges();
    this.daysSel.onchange = () => { this.setRange(+this.daysSel.value); this.fitted = false; save(); this.refresh(); };
    this.priceSel = el("select", "pstyle"); this.priceSel.setAttribute("aria-label", "Price type");
    this.priceSel.title = "How the price is drawn";
    for (const t of PT.list()) { const o = el("option", null, t.name); o.value = t.id; this.priceSel.appendChild(o); }
    this.priceSel.value = this.price.type;
    this.priceSel.onchange = () => this.setPrice(PT.normalize({ type: this.priceSel.value }));
    const priceBtn = btn("\u2699", () => { setActive(this); openPriceSettings(this); }, "Price type settings", "pricebtn");
    priceBtn.title = "Colors, fill, thickness and other settings for how the price is drawn";
    const priceGrp = el("span", "pricegrp"); priceGrp.append(this.priceSel, priceBtn);
    const fx = btn("", () => { setActive(this); openStudies(); }, "Studies", "fxbtn");
    fx.innerHTML = '<span class="fx">f(x)</span>';
    this.title = el("span", "ptitle");
    this.hint = el("span", "phint");
    this.maxBtn = btn("\u2922", () => toggleMaximize(this), "Maximize this chart", "maxbtn");
    this.maxBtn.title = "Maximize this chart (or double-click the header). Click again to restore the grid.";
    const viewsBtn = btn("\u2261", (e) => { setActive(this); openSavedMenu(e.currentTarget, "views", this); }, "Saved chart views", "viewsbtn");
    viewsBtn.title = "Save this chart's view or load a saved one; add a chart or watch list next to it, or remove it";
    head.append(this.symIn, linkControl(this), viewsBtn, this.tfSel, this.daysSel, priceGrp, fx, this.hint, this.title, this.maxBtn);
    head.addEventListener("dblclick", (e) => { if (e.target === head || e.target === this.title) toggleMaximize(this); });

    const wrap = el("div", "pchart");
    this.chartEl = el("div", "chart"); this.overlay = el("div", "overlay"); this.legends = el("div", "legends");
    this.msg = el("div", "pmsg"); this.msg.hidden = true;
    const brand = el("a", "brand", "RP");                 // the project's repository, in a new tab
    Object.assign(brand, { href: REPO, target: "_blank", rel: "noopener", title: "intraday-charts on GitHub" });
    wrap.append(this.chartEl, this.overlay, this.legends, this.msg, brand);
    root.append(head, wrap);
  }

  // the range menu's choices for the current duration
  fillRanges() {
    this.daysSel.innerHTML = "";
    for (const [v, t] of rangesFor(this.tf)) { const o = el("option", null, t); o.value = v; this.daysSel.appendChild(o); }
    this.daysSel.value = this.range();
  }

}
