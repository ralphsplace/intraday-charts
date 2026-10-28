/* Alerts: a message on screen, a beep, and a desktop notification when the page is in the background. */
import { $, el } from "./util.js";

// ---------------------------------------------------------------- alerts: toast, sound, notification
export function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + 0.25);
  } catch (e) { /* audio unavailable */ }
}
export function toast(text, quiet) {
  const t = el("div", "toast", text);
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 8000);
  if (quiet) return;
  beep();
  try {
    if (window.Notification && Notification.permission === "granted" && document.hidden) new Notification(text);
  } catch (e) { /* ignore */ }
}
