/* Canvas drawings attached to chart series (Lightweight Charts "primitives").
   Each primitive recomputes pixel positions in updateAllViews() and draws in its renderer. */
import { dash, rgba } from "./styles.js";


class Base {
  constructor(zOrder) {
    const self = this;
    this._z = zOrder;
    this._paneViews = [{
      zOrder: () => self._z,
      renderer: () => ({
        draw: (target) => target.useMediaCoordinateSpace(({ context, mediaSize }) => self.draw(context, mediaSize)),
      }),
    }];
  }
  attached({ chart, series, requestUpdate }) { this.chart = chart; this.series = series; this.requestUpdate = requestUpdate; }
  detached() { this.chart = this.series = this.requestUpdate = null; }
  paneViews() { return this._paneViews; }
  update() { if (this.requestUpdate) this.requestUpdate(); }
  draw() {}
}

/* Extended-hours shading, day separators and the empty "future" area. */
class Background extends Base {
  constructor() { super("bottom"); this.opts = { bars: [], future: [], shade: true, color: "#3a4150", separators: true }; }
  set(opts) { Object.assign(this.opts, opts); this.update(); }
  updateAllViews() {
    const o = this.opts, ts = this.chart && this.chart.timeScale();
    this.runs = []; this.seps = []; this.futureX = null;
    if (!ts || !o.bars.length) return;
    const half = (ts.options().barSpacing || 6) / 2;
    let start = null, prev = null, prevDay = null;
    for (const b of o.bars) {
      const x = ts.timeToCoordinate(b.time);
      if (x == null) { prev = null; continue; }
      if (b.session !== "rth") { if (start == null) start = x - half; prev = x + half; }
      else if (start != null) { this.runs.push([start, x - half]); start = null; }
      if (prevDay && b.day !== prevDay) this.seps.push(x - half);
      prevDay = b.day;
    }
    if (start != null && prev != null) this.runs.push([start, prev]);
    if (o.future.length) {
      const x = ts.timeToCoordinate(o.future[0]);
      if (x != null) this.futureX = x - half;
    }
  }
  draw(ctx, size) {
    const o = this.opts;
    if (o.shade) {
      ctx.fillStyle = rgba(o.color, 0.35);
      for (const [a, b] of this.runs || []) ctx.fillRect(a, 0, Math.max(b - a, 1), size.height);
    }
    if (this.futureX != null && this.futureX < size.width) {
      ctx.fillStyle = "rgba(255,255,255,0.025)";
      ctx.fillRect(this.futureX, 0, size.width - this.futureX, size.height);
    }
    if (o.separators) {
      ctx.strokeStyle = "rgba(160,170,185,0.35)"; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
      for (const x of this.seps || []) { ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, 0); ctx.lineTo(Math.round(x) + 0.5, size.height); ctx.stroke(); }
      ctx.setLineDash([]);
    }
  }
}

/* Horizontal volume-at-price histogram along the left or right edge. */
class Profile extends Base {
  constructor() { super("bottom"); this.profiles = []; }
  set(profiles) { this.profiles = profiles || []; this.update(); }
  updateAllViews() {
    this.rects = [];
    if (!this.series) return;
    for (const p of this.profiles) {
      const max = Math.max(...p.bins.map((b) => b.vol), 1);
      for (const b of p.bins) {
        const y0 = this.series.priceToCoordinate(b.hi), y1 = this.series.priceToCoordinate(b.lo);
        if (y0 == null || y1 == null) continue;
        this.rects.push({ p, y: Math.min(y0, y1), h: Math.max(Math.abs(y1 - y0) - 1, 1), f: b.vol / max, va: b.va });
      }
    }
  }
  draw(ctx, size) {
    for (const r of this.rects || []) {
      const len = r.f * size.width * r.p.width_pct / 100;
      ctx.fillStyle = rgba(r.va ? r.p.va_color : r.p.out_color, r.p.opacity);
      const x = r.p.side === "right" ? size.width - len : 0;
      ctx.fillRect(x, r.y, len, r.h);
    }
  }
}

/* Shaded horizontal zones in a study pane, e.g. VZO +40..+60. */
class Bands extends Base {
  constructor() { super("bottom"); this.bands = []; }
  set(bands) { this.bands = bands || []; this.update(); }
  updateAllViews() {
    this.px = [];
    if (!this.series) return;
    for (const b of this.bands) {
      const y0 = this.series.priceToCoordinate(b.to), y1 = this.series.priceToCoordinate(b.from);
      if (y0 != null && y1 != null) this.px.push({ y: Math.min(y0, y1), h: Math.abs(y1 - y0), color: b.color });
    }
  }
  draw(ctx, size) {
    for (const b of this.px || []) { ctx.fillStyle = rgba(b.color, 0.16); ctx.fillRect(0, b.y, size.width, b.h); }
  }
}

/* Fill between two lines, coloured by which one is on top; crossings are split exactly. */
class Cloud extends Base {
  constructor() { super("bottom"); this.clouds = []; }
  set(clouds) { this.clouds = clouds || []; this.update(); }
  updateAllViews() {
    this.px = [];
    if (!this.series || !this.chart) return;
    const ts = this.chart.timeScale();
    for (const c of this.clouds) {
      const pts = [];
      for (const p of c.points) {
        const x = ts.timeToCoordinate(p.time);
        const ya = this.series.priceToCoordinate(p.a), yb = this.series.priceToCoordinate(p.b);
        if (x == null || ya == null || yb == null) continue;
        pts.push({ x, ya, yb, d: p.a - p.b });
      }
      this.px.push({ pts, up: c.up, down: c.down, lineA: c.line_a, lineB: c.line_b });
    }
  }
  draw(ctx) {
    const quad = (pts, color) => {
      ctx.fillStyle = color; ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
      for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
      ctx.closePath(); ctx.fill();
    };
    const stroke = (pts, key, ln) => {
      if (!ln || pts.length < 2) return;
      ctx.save();
      ctx.strokeStyle = ln.color; ctx.lineWidth = ln.width || 1; ctx.setLineDash(dash(ln.style, ln.width || 1));
      ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0][key]);
      for (const p of pts.slice(1)) ctx.lineTo(p.x, p[key]);
      ctx.stroke(); ctx.restore();
    };
    for (const c of this.px || []) {
      stroke(c.pts, "ya", c.lineA); stroke(c.pts, "yb", c.lineB);
      const col = (d) => (d >= 0 ? c.up : c.down);
      for (let i = 0; i < c.pts.length - 1; i++) {
        const p0 = c.pts[i], p1 = c.pts[i + 1];
        if (p0.d === 0 && p1.d === 0) continue;
        if (p0.d * p1.d >= 0) {
          quad([[p0.x, p0.ya], [p1.x, p1.ya], [p1.x, p1.yb], [p0.x, p0.yb]], col(p0.d + p1.d));
        } else {
          const t = p0.d / (p0.d - p1.d);
          const xm = p0.x + t * (p1.x - p0.x), ym = p0.ya + t * (p1.ya - p0.ya);
          quad([[p0.x, p0.ya], [xm, ym], [p0.x, p0.yb]], col(p0.d));
          quad([[xm, ym], [p1.x, p1.ya], [p1.x, p1.yb]], col(p1.d));
        }
      }
    }
  }
}


/* User-drawn trend lines. xAt(time) maps any time (also between bars) to an x coordinate. */
class TrendLines extends Base {
  constructor(xAt) { super("normal"); this.xAt = xAt; this.lines = []; this.pending = null; }
  set(lines, pending) { this.lines = lines || []; this.pending = pending || null; this.update(); }
  updateAllViews() {
    this.segs = [];
    if (!this.series) return;
    const all = [...this.lines];
    if (this.pending) all.push({ ...this.pending, p2: this.pending.p2 || this.pending.p1, color: "#ffffff", width: 1,
                                 style: "dotted", dot: true });
    for (const l of all) {
      const x1 = this.xAt(l.p1.time), x2 = this.xAt(l.p2.time);
      const y1 = this.series.priceToCoordinate(l.p1.price), y2 = this.series.priceToCoordinate(l.p2.price);
      if ([x1, x2, y1, y2].some((v) => v == null)) continue;
      this.segs.push({ x1, y1, x2, y2, l });
    }
  }
  draw(ctx, size) {
    for (const s of this.segs || []) {
      const l = s.l;
      ctx.strokeStyle = l.color || "#e3e6ea"; ctx.lineWidth = l.width || 1; ctx.setLineDash(dash(l.style, l.width || 1));
      let { x1, y1, x2, y2 } = s;
      if (l.extend && x2 !== x1) {
        const k = (y2 - y1) / (x2 - x1);
        const xe = x2 > x1 ? size.width : 0;
        y2 = y2 + k * (xe - x2); x2 = xe;
      }
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = l.color || "#e3e6ea";
      for (const [x, y] of [[s.x1, s.y1], [s.x2, s.y2]]) { ctx.beginPath(); ctx.arc(x, y, l.dot ? 3 : 2, 0, Math.PI * 2); ctx.fill(); }
    }
  }
}

export const ChartPrimitives = { Background, Profile, Bands, Cloud, TrendLines };
