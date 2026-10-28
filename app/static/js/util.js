/* Small shared helpers: the chart library, DOM building, server calls, browser storage. */
export const LWC = window.LightweightCharts;
export const $ = (id) => document.getElementById(id);

export const fmtMin = (m) => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");

// stocks and ETFs; breadth indexes; series recorded from live quotes (ADD, VOLD); -VIX (VIX upside down)
export const SYMBOL_RE = /^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$|^(TICK|TRIN|AD|VOL)-(NYSE|NASD|NDX)$|^(ADD|VOLD)-NYSE$|^-VIX$/;

export async function api(path, body, method) {
  const opts = body != null ? { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
                            : method ? { method } : undefined;
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

export const uid = () => Math.random().toString(36).slice(2, 9);

export const clone = (x) => JSON.parse(JSON.stringify(x));
export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
export function btn(text, fn, aria, cls) {
  const b = el("button", cls, text);
  b.type = "button"; b.onclick = fn;
  if (aria) b.setAttribute("aria-label", aria);
  return b;
}
export function store(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* unavailable */ } }
export function load(key) { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { return null; } }

// large values (e.g. NYSE up - down volume) as 25.04M / 1.20B; anything else with 2 decimals
export function fmtValue(v) {
  const a = Math.abs(v);
  return a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v.toFixed(2);
}

export const cleanSymbol = (s) => { s = (s || "").trim().toUpperCase(); return SYMBOL_RE.test(s) ? s : null; };

const SVG = "http://www.w3.org/2000/svg";
export function svgEl(tag, attrs) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, val] of Object.entries(attrs)) e.setAttribute(k, val);
  return e;
}
