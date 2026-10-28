/* Drawing tools: the buttons in each chart's header (Alert, Line, Trend). Each tool is one module in this
   folder, and every module has the same shape:

     type                      stored with each drawing, e.g. "hline"
     button, tip               the header button's text and tooltip
     hints                     what to do for each click, e.g. ["Click the first point", "Click the second point"]
     needsTime                 true when a click must land on the time axis (between bars is fine)
     create(panel, points)     the new drawing's fields, once it has as many points as hints
     placed()                  optional: after a drawing is placed (e.g. ask for notification permission)
     label(d)                  its name in the legend and on the price axis
     settings(d)               { title, desc, params } for the settings dialog (params as in params.js)
     applied(d)                optional: after its settings are changed
     attach(panel)             optional: once per chart, create what the tool draws with
     render(panel, list, pending)  draw this tool's drawings on the chart; pending is a drawing being placed
     check(panel, d, view)     optional: a message when the drawing's alert condition is met, else null
     actions(panel, d)         optional: extra legend buttons for the drawing

   To add a tool: add a module here and list it below. The header, legend, settings and alerts pick it up. */
import alert from "./alert.js";
import hline from "./hline.js";
import trend from "./trend.js";

export const TOOLS = [alert, hline, trend];
export const toolFor = (type) => TOOLS.find((t) => t.type === type);
