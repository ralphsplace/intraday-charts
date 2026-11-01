"""JavaScript coverage from Chromium's V8 block coverage (the Chrome DevTools Protocol), merged across pages.

A line counts if it holds code (not blank, not only a comment or a closing bracket); it is covered when any of
that code ran. Our own scripts only: the bundled chart library is left out.
"""
from __future__ import annotations

import re

OWN = ("/static/dash.js",)
OWN_DIRS = ("/static/js/",)     # the chart page's modules
INLINE_PAGES = ()     # pages whose own <script> is measured (none now: every page loads modules)


class Coverage:
    def __init__(self):
        self.files: dict[str, tuple[str, bytearray]] = {}     # name -> (source, covered flag per character)

    def start(self, cdp):
        cdp.send("Profiler.enable")
        cdp.send("Debugger.enable")
        cdp.send("Profiler.startPreciseCoverage", {"callCount": False, "detailed": True})

    @staticmethod
    def _name(url: str) -> str | None:
        path = re.sub(r"^https?://[^/]+", "", url or "").split("?")[0]
        path = re.sub(r"^/static/_v[0-9a-f]+/", "/static/", path)          # pages ask for versioned addresses
        if path in OWN or path.startswith(OWN_DIRS):
            return path.lstrip("/").replace("static/", "app/static/")
        if path in INLINE_PAGES:
            return f"app/static{path}.html (script)"
        return None

    def collect(self, cdp):
        try:
            result = cdp.send("Profiler.takePreciseCoverage")["result"]
        except Exception:  # noqa: BLE001  (page already gone)
            return
        for script in result:
            name = self._name(script["url"])
            if not name:
                continue
            try:
                src = cdp.send("Debugger.getScriptSource", {"scriptId": script["scriptId"]})["scriptSource"]
            except Exception:  # noqa: BLE001
                continue
            if len(src) < 500:          # the one-line window.DASHBOARD = {...} blocks
                continue
            mask = bytearray(len(src))
            ranges = [r for f in script["functions"] for r in f["ranges"]]
            ranges.sort(key=lambda r: (r["startOffset"], -(r["endOffset"] - r["startOffset"])))
            for r in ranges:            # outer ranges first; nested ones override them
                mask[r["startOffset"]:r["endOffset"]] = (b"\x01" if r["count"] > 0 else b"\x00") * (r["endOffset"] - r["startOffset"])
            old = self.files.get(name)
            if old and old[0] == src:
                merged = bytearray(a | b for a, b in zip(old[1], mask, strict=True))
                self.files[name] = (src, merged)
            else:
                self.files[name] = (src, mask)

    def summary(self) -> list[tuple[str, int, int, float]]:
        rows = []
        for name in sorted(self.files):
            src, mask = self.files[name]
            lines = hit = 0
            pos = 0
            for line in src.split("\n"):
                code = line.strip()
                if code and not code.startswith(("//", "/*", "*")) and code not in ("}", "});", "})", "};", ")", "]", "});"):
                    lines += 1
                    span = range(pos, pos + len(line))
                    if any(mask[i] for i in span if not line[i - pos].isspace()):
                        hit += 1
                pos += len(line) + 1
            rows.append((name, lines, hit, 100.0 * hit / lines if lines else 100.0))
        if rows:
            tl, th = sum(r[1] for r in rows), sum(r[2] for r in rows)
            rows.append(("TOTAL", tl, th, 100.0 * th / tl))
        return rows
