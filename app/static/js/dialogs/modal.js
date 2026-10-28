/* Opening and closing dialogs; Escape closes dialogs, menus, drawing tools and a maximized chart. */
import { toggleMaximize } from "../grid.js";
import { closeMenu } from "../saved.js";
import { app } from "../state.js";
import { $ } from "../util.js";

export function openModal(id) { $(id).hidden = false; }
export function closeModal(id) { $(id).hidden = true; }

export function init() {
  document.querySelectorAll(".modal").forEach((m) => {
    m.addEventListener("click", (e) => { if (e.target === m || e.target.closest("[data-close]")) m.hidden = true; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const modalOpen = [...document.querySelectorAll(".modal")].some((m) => !m.hidden);
    const drawing = app.panels.some((p) => p.tool);
    document.querySelectorAll(".modal").forEach((m) => (m.hidden = true));
    closeMenu();
    app.panels.forEach((p) => p.tool && p.setTool(null));
    if (!modalOpen && !drawing && app.maximized) toggleMaximize(app.maximized);
  });

}
