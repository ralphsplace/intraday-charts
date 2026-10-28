/* Settings parameters, in the same shape the server uses for study settings, so one settings dialog serves
   studies, price types and drawing tools:  { key, label, type, default, section, ...extra }
   type: "int" | "float" | "bool" | "choice" | "color" | "text";  extra: min, max, step, options, labels, row */
import { LINE_STYLES, LINE_STYLE_LABELS } from "./styles.js";

export const param = (key, label, type, def, extra = {}) => ({ key, label, type, default: def, section: "Inputs", ...extra });

// colour, line type and thickness on one row (the settings dialog puts captions over the columns)
export function lineParams(row, color, style, width, keys = { color: "color", style: "style", width: "width" }) {
  return [param(keys.color, "Color", "color", color, { section: "Style", row }),
          param(keys.style, "Line type", "choice", style, { section: "Style", row, options: LINE_STYLES, labels: LINE_STYLE_LABELS }),
          param(keys.width, "Thickness", "int", width, { section: "Style", row, min: 1, max: 4 })];
}

export const defaultsOf = (params) => Object.fromEntries(params.map((p) => [p.key, p.default]));
