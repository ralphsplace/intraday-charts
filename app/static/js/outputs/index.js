/* Study outputs: how each kind of study result is drawn.

   A study returns a result with one or more outputs (lines, levels, a volume profile, ...). Each kind is drawn by
   one module in this folder, and every module has the same shape. All hooks are optional:

     key                       the field of the study result it draws, e.g. "lines"
     shape(value)              a short text that changes when the study's series must be rebuilt (e.g. other line ids)
     build(layer, value)       when a study is (re)built: create its series, price lines or primitives
     update(layer, value)      on every render, also with value undefined: give them the latest data
     clear(layer)              remove what build and update created
     attach(panel)             once per chart: create what all studies share (e.g. one volume-profile drawing)
     gather(value)             on every render: the items this study adds to the chart-wide drawing
     flush(panel, items)       after all studies: draw everything gathered
     overlay(panel, value, add) on scroll and resize: HTML drawn over the chart (opening-range box, event lines)
     legend(panel, items)      the price pane's legend: an element for everything gathered from all studies, or null
     color(value)              the colour for the study's legend swatch

   A "layer" is one study on one chart: { panel, chart, res, uid, pane, scale, series: [], refPrices: [], host() }.
   host() is its first series, which reference lines and shaded bands attach to; refPrices are prices its pane's
   scale must always include.

   To draw a new kind of output: add a module here and list it below. Nothing else changes. */
import histograms from "./histograms.js";
import lines from "./lines.js";
import hlines from "./hlines.js";
import bands from "./bands.js";
import levels from "./levels.js";
import profile from "./profile.js";
import cloud from "./cloud.js";
import box from "./box.js";
import verticals from "./verticals.js";
import labels from "./labels.js";

// order matters only where one output uses another's series: histograms and lines first (they make the host)
export const OUTPUTS = [histograms, lines, hlines, bands, levels, profile, cloud, box, verticals, labels];
