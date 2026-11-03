/* What a backtest does about trading days without cached bars (app/paper/backtest.py MISSING): the choices of the
   Paper page's Run form and of Config's Backtests defaults. */
import { el } from "../util.js";

export const MISSING = [["fetch", "Fetch them from TWS"], ["skip", "Skip them"], ["stop", "Stop the run"]];

// fill a <select> with the choices once
export function missingSelect(select) {
  if (select.options.length) return select;
  for (const [v, t] of MISSING) { const o = el("option", null, t); o.value = v; select.appendChild(o); }
  return select;
}
