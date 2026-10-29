/* The toolbar: layout, day, display options, replay (step, play, cursor) and Live mode.
   Replay at first; once Live, it stays Live (across dashboards and pages, in this tab) until switched back by
   hand or until TWS can't be reached. */
import { fillDays, refreshAll, requestData } from "./data.js";
import { buildGrid, placeSplitters } from "./grid.js";
import { MODE_KEY } from "./keys.js";
import { toast } from "./notify.js";
import { LIVE_REFRESH_MS, app, save } from "./state.js";
import { $, api, fmtMin } from "./util.js";

export function stopPlay() { app.playing = false; $("play").textContent = "Play"; }
export function maxMinute() { return Math.max(...app.panels.map((p) => p.view?.last_minute || 0), 241); }
// minutes per replay step: the shortest intraday candle on screen (5 when every chart shows daily or longer)
export function stepSize() {
  const mins = app.panels.filter((p) => !p.isPeriod()).map((p) => p.tf);
  return mins.length ? Math.min(...mins) : 5;
}
export async function step(dir) {
  const max = maxMinute();
  app.cursor = Math.max(241, Math.min((app.cursor ?? max) + dir * stepSize(), max));
  showCursor();
  await refreshAll();
}
export function showCursor() { $("cursor").value = app.cursor ?? maxMinute(); $("cursorLabel").textContent = fmtMin(app.cursor ?? maxMinute()); }

const LIVE_MISSES = 2;           // collector polls in a row without TWS before Live gives up (about 10 s)

function remember(live) {
  try { if (live) sessionStorage.setItem(MODE_KEY, "live"); else sessionStorage.removeItem(MODE_KEY); }
  catch (e) { /* storage unavailable: every page starts in Replay */ }
}
function remembered() {
  try { return sessionStorage.getItem(MODE_KEY) === "live"; } catch (e) { return false; }
}

// why Live can't run from the collector's last report, or "" when it can
export function liveProblem(st) {
  if (!st || !st.running) return "the TWS collector isn't running";
  if (!st.connected) return "the collector can't reach TWS" + (st.message ? ` (${st.message})` : "");
  return "";
}

function dropLive(why) {
  setMode(false);
  toast(`Live stopped: ${why}. Showing Replay; press Live to go back once it's fixed.`);
}

// at start-up: back to Live if this tab was in Live before (another dashboard or page), and TWS is reachable
export async function restoreMode() {
  if (!remembered()) return;
  const why = liveProblem(app.collector);
  if (why) dropLive(why); else await setMode(true);
}

let liveTimer = null;
export async function setMode(live) {
  app.live = live; stopPlay(); remember(live);
  $("modeLive").classList.toggle("active", live);
  $("modeReplay").classList.toggle("active", !live);
  $("replayBar").hidden = live;                         // Live has no replay: the controls go away
  requestAnimationFrame(placeSplitters);                 // the charts just grew or shrank
  $("day").disabled = live;
  clearInterval(liveTimer);
  if (live) {
    app.meta = await api("/api/meta");
    const prev = app.day;
    fillDays(); app.cursor = null;
    if (app.day !== prev) app.panels.forEach((p) => { p.fitted = false; });
    requestData([...new Set(app.panels.map((p) => p.symbol))]);   // stream every symbol on screen
    await refreshAll(); showCursor();
    let ticks = 0, misses = 0;
    liveTimer = setInterval(async () => {
      app.collector = await api("/api/collector").catch(() => app.collector);
      const why = liveProblem(app.collector);
      misses = why ? misses + 1 : 0;
      if (misses >= LIVE_MISSES) return dropLive(why);
      if (++ticks % 12 === 0) {           // about once a minute, pick up a new trading day
        app.meta = await api("/api/meta").catch(() => app.meta);
        const latest = app.day; fillDays();
        if (app.day !== latest) app.panels.forEach((p) => { p.fitted = false; });
      }
      await refreshAll(); showCursor();
    }, LIVE_REFRESH_MS);
  } else {
    fillDays();
  }
}

export function init() {
  $("layout").onchange = (e) => { save(); app.layout = e.target.value; buildGrid(); save(); refreshAll(); };
  $("day").onchange = async (e) => {
    app.day = e.target.value; app.cursor = null; stopPlay();
    app.panels.forEach((p) => { p.fitted = false; p.lastCursor = null; });
    await refreshAll(); showCursor();
  };
  for (const [id, key] of [["fitLevels", "fitLevels"], ["extShade", "extShade"], ["syncCrosshair", "sync"]]) {
    $(id).onchange = () => {
      app.prefs[key] = $(id).checked; save();
      if (key === "fitLevels") app.panels.forEach((p) => p.chart.priceScale("right").applyOptions({ autoScale: true }));
      if (key !== "sync") app.panels.forEach((p) => p.view && p.render(p.view));
    };
  }

  $("cursor").oninput = (e) => { stopPlay(); app.cursor = +e.target.value; $("cursorLabel").textContent = fmtMin(app.cursor); };
  $("cursor").onchange = () => refreshAll();
  $("stepBack").onclick = () => { stopPlay(); step(-1); };
  $("stepFwd").onclick = () => { stopPlay(); step(1); };
  $("play").onclick = async () => {
    if (app.playing) return stopPlay();
    if (app.cursor == null || app.cursor >= maxMinute()) app.cursor = 9 * 60 + 30 - stepSize();
    app.playing = true; $("play").textContent = "Pause";
    while (app.playing) {
      const t0 = performance.now();
      await step(1);   // waits for every chart, so a big grid slows playback instead of piling up requests
      if (app.cursor >= maxMinute()) { stopPlay(); break; }
      await new Promise((r) => setTimeout(r, Math.max(0, 1000 / +$("speed").value - (performance.now() - t0))));
    }
  };

  $("modeLive").onclick = () => setMode(true);
  $("modeReplay").onclick = () => setMode(false);

}
