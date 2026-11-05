/* A running backtest's days at a glance (report.js): one cell a day, waiting, going (worked on now, in one of the
   backtest worker's processes, app/backtesting/days.py), worked out (waiting for the days before it: each day starts with
   the cash the days before it left) or done, with its P/L. Several are going at once: as many as Config,
   Backtests, Workers says, shared by every run. The run: its "days" ({all, running, done: {day: P/L}, workers}). */
import { dollars } from "../format.js";
import { el } from "../util.js";

export function dayGrid(run) {
  const g = run.days;
  if (!g?.all?.length) return null;
  const going = new Set(g.running || []), worked = new Set(g.worked || []), done = g.done || {};
  const n = Object.keys(done).length;
  const wrap = el("div", "pp-days");
  wrap.appendChild(el("p", "muted small", `${n} of ${g.all.length} days done · ${going.size} going now · ` +
                                         `${g.workers} at a time across all runs (Config, Backtests, Workers)`));
  const cells = el("div", "pp-daycells");
  for (const d of g.all) {
    const pnl = done[d];
    const state = d in done ? (pnl > 0 ? "up" : pnl < 0 ? "down" : "flat") : going.has(d) ? "going" : worked.has(d) ? "worked" : "waiting";
    const c = el("span", `pp-day ${state}`, d.slice(5));
    c.dataset.day = d;
    c.title = d in done ? `${d}: ${dollars(pnl, { d: 2 })}`
      : `${d}: ${{ going: "being worked on", worked: "worked out, waiting for the days before it", waiting: "waiting" }[state]}`;
    cells.appendChild(c);
  }
  wrap.appendChild(cells);
  return wrap;
}
