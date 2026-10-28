/* Fill between two lines (moving average cloud): one drawing per chart, holding every study's cloud. */
import { ChartPrimitives as PR } from "../primitives.js";

export default {
  key: "cloud",
  attach(panel) { panel.out.cloud = new PR.Cloud(); panel.candles.attachPrimitive(panel.out.cloud); },
  gather: (c) => [c],
  flush(panel, items) { panel.out.cloud.set(items); },
};
