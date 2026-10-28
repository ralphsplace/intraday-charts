/* VWAP: click a bar to start an anchored VWAP there. It adds an Anchored VWAP study to this chart (not a
   drawing), so its anchor, bands and colours are changed in the study's settings like any other study. */

// a chart time (US/Eastern wall clock as a UTC epoch) as "YYYY-MM-DD HH:MM"
const fmtAt = (t) => new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ");

export default {
  type: "avwap",
  button: "VWAP",
  tip: "Anchored VWAP: click the bar to start it from (adds an Anchored VWAP study; its settings offer other anchors)",
  hints: ["Click the bar to anchor a VWAP at"],
  needsTime: true,
  place(panel, points) { panel.addStudy("anchored_vwap", { anchor: "Chosen time", at: fmtAt(points[0].time) }); },
  render() {},
};
