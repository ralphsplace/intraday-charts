/* Small shared helpers: the chart library, DOM building, server calls, browser storage. */
export const LWC = window.LightweightCharts;
export const $ = (id) => document.getElementById(id);

// stocks and ETFs; breadth indexes; series recorded from live quotes (ADD, VOLD); -VIX (VIX upside down)
export const SYMBOL_RE = /^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$|^(TICK|TRIN|AD|VOL)-(NYSE|NASD|NDX)$|^(ADD|VOLD)-NYSE$|^-VIX$/;

export async function api(path, body, method) {
  const opts = body != null ? { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
                            : method ? { method } : undefined;
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// ---------------------------------------------------------------- requests the page can do without
// A request whose failure the page survives, carrying on with `fallback` (a value, or a function of the error), but
// that the user should know failed: a note in the corner of any page, one per kind of request (`what`), gone once
// that request works again. For polls, an unreachable server shows one note, not one per tick.
const problems = new Map();
function showProblems() {
  let box = $("problems");
  if (!box && !problems.size) return;
  if (!box) { box = el("div"); box.id = "problems"; box.setAttribute("role", "status"); document.body.appendChild(box); }
  box.replaceChildren(...[...problems].map(([what, why]) => el("div", "problem", `${what}: ${why}`)));
  box.hidden = !problems.size;
}
export function orElse(promise, fallback, what) {
  return promise.then(
    (v) => { if (problems.delete(what)) showProblems(); return v; },
    (e) => {
      console.warn(`${what}:`, e);
      if (problems.get(what) !== e.message) { problems.set(what, e.message); showProblems(); }
      return typeof fallback === "function" ? fallback(e) : fallback;
    });
}

// a class built from parts, each a class whose methods serve one job (e.g. a panel's legends): their methods are
// copied onto the target's prototype, in order
export function mixParts(Target, ...parts) {
  for (const part of parts) {
    for (const k of Object.getOwnPropertyNames(part.prototype)) if (k !== "constructor") Target.prototype[k] = part.prototype[k];
  }
}

// ---------------------------------------------------------------- redrawing without replacing what's on screen
// Bring a live element's children in line with freshly built ones (the same code that drew it, run again into
// `fresh`): an element of the same tag (and data-key, when it has one) is kept and updated in place, so a click,
// drag, double-click or hover on it survives a refresh; others are added, moved or removed. Attributes, text and
// on* handlers are copied, so handlers must find their element through the event (e.currentTarget), never by a
// variable from when they were built. A box being typed in (inUse) is left as it is.
const HANDLERS = ["onclick", "ondblclick", "onchange", "oninput", "onkeydown", "ondragstart", "ondragover", "ondragleave", "ondrop"];
const PROPS = ["value", "checked", "disabled", "draggable", "colSpan", "hidden"];
// the same control: same tag and key; a button without a key is also known by its label (a different label is a
// different control, so it doesn't inherit the focus of the one it replaces)
const sameKind = (a, b) => a.nodeName === b.nodeName && (a.dataset?.key ?? null) === (b.dataset?.key ?? null) &&
  (a.nodeName !== "BUTTON" || a.dataset.key != null || a.textContent === b.textContent);
function syncNode(a, b) {
  if (a.nodeType !== 1) { if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue; return; }
  if (a.matches("input, textarea, select") && inUse(a)) return;     // being typed in or picked from
  for (const { name } of [...a.attributes]) if (!b.hasAttribute(name)) a.removeAttribute(name);
  for (const { name, value } of b.attributes) if (a.getAttribute(name) !== value) a.setAttribute(name, value);
  for (const h of HANDLERS) if (a[h] !== b[h]) a[h] = b[h];
  for (const p of PROPS) if (p in b && a[p] !== b[p]) a[p] = b[p];
  syncChildren(a, b);
}
function syncChildren(a, b) {
  const want = [...b.childNodes];
  want.forEach((w, i) => {
    const key = w.dataset?.key;
    let cur = a.childNodes[i];
    if (key != null && !(cur && sameKind(cur, w))) {                 // a keyed element moved: bring it here
      const found = [...a.children].find((c) => c.dataset.key === key && c.nodeName === w.nodeName);
      if (found) { a.insertBefore(found, cur || null); cur = found; }
    }
    if (cur && sameKind(cur, w)) syncNode(cur, w);
    else a.insertBefore(w, cur || null);
  });
  while (a.childNodes.length > want.length) a.lastChild.remove();
}
export function morph(live, fresh) { syncChildren(live, fresh); }

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

export const cleanSymbol = (s) => { s = (s || "").trim().toUpperCase(); return SYMBOL_RE.test(s) ? s : null; };

const SVG = "http://www.w3.org/2000/svg";
export function svgEl(tag, attrs) {
  const e = document.createElementNS(SVG, tag);
  for (const [k, val] of Object.entries(attrs)) e.setAttribute(k, val);
  return e;
}

// ---------------------------------------------------------------- what someone is typing or picking
// A refresh never writes over a box someone is typing in, or has typed in and not yet submitted (Enter or the form's
// button), and never rebuilds a menu that has the focus. The text stays until it's submitted, or Escape puts back
// what the page shows.
export const inUse = (e) => !!e && (document.activeElement === e || e.dataset.edited === "1");
export function setValue(e, value) { if (!inUse(e)) e.value = value; }
export function trackEdits(e, current) {
  e.addEventListener("input", () => { e.dataset.edited = "1"; });
  e.addEventListener("keydown", (k) => {
    if (k.key === "Escape" && e.dataset.edited) { delete e.dataset.edited; e.value = current(); }
  });
}
export const submitted = (e) => { delete e.dataset.edited; };

/* Redraw without moving the page. Parts emptied and refilled in a redraw (innerHTML = "", then rebuilt) make the
   page shorter for a moment; if anything measures the layout meanwhile, a page scrolled to the bottom is pulled up
   and stays there. Keeps the scroller's position across fn() (synchronous). */
export function keepScroll(scroller, fn) {
  const el = scroller || document.scrollingElement;
  const top = el ? el.scrollTop : 0;
  try { return fn(); } finally { if (el && el.scrollTop !== top) el.scrollTop = top; }
}
