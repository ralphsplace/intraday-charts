/* Volume profile: one horizontal histogram drawing per chart, holding every study's profile. */
import { ChartPrimitives as PR } from "../primitives.js";

export default {
  key: "profile",
  attach(panel) { panel.out.profile = new PR.Profile(); panel.candles.attachPrimitive(panel.out.profile); },
  gather: (p) => [p],
  flush(panel, items) { panel.out.profile.set(items); },
};
