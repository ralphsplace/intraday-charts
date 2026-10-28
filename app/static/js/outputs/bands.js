/* Shaded zones in a study's own pane (VZO +40..+60); the pane's scale always includes them. */
import { ChartPrimitives as PR } from "../primitives.js";

export default {
  key: "bands",
  shape: () => "b",
  build(layer, bs) {
    const host = layer.host();
    if (!host) return;
    layer.refPrices.push(...bs.flatMap((b) => [b.from, b.to]));
    layer.bands = new PR.Bands(); host.attachPrimitive(layer.bands);
  },
  update(layer, bs) { layer.bands?.set(bs || []); },
  clear(layer) { if (layer.bands) layer.host()?.detachPrimitive(layer.bands); },
};
