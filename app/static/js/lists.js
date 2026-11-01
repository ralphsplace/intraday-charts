/* Named watch lists, shared by the whole app (app/watchlists.py, /api/watchlists): this browser's copy in
   app.saved.watchlists, and the calls that change them. A name is unique; each list also has an id that never
   changes, so a tab still finds its list after it's renamed in another browser. */
import { app } from "./state.js";
import { api } from "./util.js";

// a stored list as {id, source, symbols?, feed?}, with every field present
export function normal(v) {
  return { id: v?.id || null, source: v?.source || "symbols", symbols: v?.symbols || [], feed: v?.feed || null };
}

export const symbolsOf = (v) => normal(v).symbols || [];
export const names = () => Object.keys(app.saved.watchlists || {}).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

// a tab's list: by its id first (it may have been renamed), else by name; [name, list] or [null, null]
export function find(id, name) {
  const all = app.saved.watchlists || {};
  if (id) for (const [n, v] of Object.entries(all)) if (normal(v).id === id) return [n, normal(v)];
  return name && all[name] ? [name, normal(all[name])] : [null, null];
}

const take = (r) => { app.saved.watchlists = r.lists; return r; };

// a new list ("Watch list N" unless named); returns {name, item}
export const create = (source, data = {}, name) => api("/api/watchlists", { source, ...data, ...(name ? { name } : {}) }).then(take);
export const update = (name, source, data = {}) => api(`/api/watchlists/${encodeURIComponent(name)}`, { source, ...data }, "PUT").then(take);
export const rename = (name, to) => api(`/api/watchlists/${encodeURIComponent(name)}/rename`, { to }).then(take);
export const remove = (name) => api(`/api/watchlists/${encodeURIComponent(name)}`, null, "DELETE").then(take);
export const refresh = () => api("/api/watchlists").then((all) => { app.saved.watchlists = all; return all; });
