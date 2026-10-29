"""Browser tests: the real server, started on a temporary data folder of SYNTHETIC bars, driven with Playwright
(Chromium). JavaScript coverage is collected from Chromium (V8) and summarised at the end of the run.

    pytest tests/ui                 # just these
    pytest -m "not ui"              # everything else (when no browser is installed)

Needs: pip install playwright && playwright install chromium   (skipped when Playwright isn't installed)
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
playwright_api = pytest.importorskip("playwright.sync_api")

from jscov import Coverage  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COVERAGE = Coverage()


def pytest_collection_modifyitems(items):
    for it in items:
        if "tests/ui" in str(it.fspath).replace(os.sep, "/"):
            it.add_marker(pytest.mark.ui)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def ui_data(tmp_path_factory):
    """Synthetic bars, also saved as QQQ and SPY so the default charts have data. Invented prices, a temp folder."""
    import synthetic
    from app import store
    d = tmp_path_factory.mktemp("ui-data")
    old = store.DATA_DIR
    synthetic.generate(d)
    store.DATA_DIR = old
    for demo, real in (("QQQ-DEMO", "QQQ"), ("SPY-DEMO", "SPY")):
        shutil.copytree(d / "bars" / demo, d / "bars" / real)
    synthetic.generate_earnings(d, "ACME-DEMO")               # the earnings page's synthetic stock
    synthetic.generate_options(d, "ACME-DEMO")                # and the expected-move page's
    synthetic.generate_chain(d, "ACME-DEMO")                  # and the option-chain page's
    store.DATA_DIR = old
    return d


@pytest.fixture(scope="session")
def server(ui_data):
    port = _free_port()
    env = {**os.environ, "DATA_DIR": str(ui_data), "PYTHONPATH": str(ROOT)}
    env.pop("SEC_CONTACT", None)                               # earnings lookups off: the page says so
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.server:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/api/meta", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("chart server didn't start: " + proc.stdout.read().decode(errors="replace"))
    yield base
    proc.terminate()
    proc.wait(10)


@pytest.fixture
def data(ui_data):
    """Each test starts with no dashboards file, saved items or fetch requests."""
    for sub in ("user", "control"):
        shutil.rmtree(ui_data / sub, ignore_errors=True)
    return ui_data


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Page:
    """A browser tab with JavaScript errors recorded and coverage collected across page loads."""

    def __init__(self, browser, base, width=1500, height=850):
        self.base = base
        self.ctx = browser.new_context(viewport={"width": width, "height": height})
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.cdp = self.ctx.new_cdp_session(self.page)
        COVERAGE.start(self.cdp)

    def goto(self, path: str, wait_ms: int = 1500):
        COVERAGE.collect(self.cdp)
        self.page.goto(self.base + path)
        self.page.wait_for_timeout(wait_ms)
        return self.page

    def close(self):
        COVERAGE.collect(self.cdp)
        self.ctx.close()


@pytest.fixture
def tab(browser, server, data):
    t = Page(browser, server)
    yield t
    t.close()
    assert not t.errors, "JavaScript errors: " + "; ".join(t.errors)


def pytest_terminal_summary(terminalreporter):
    rows = COVERAGE.summary()
    if not rows:
        return
    terminalreporter.section("JavaScript coverage (browser tests)")
    for name, lines, hit, pct in rows:
        terminalreporter.write_line(f"{name:<34} {hit:>5} of {lines:>5} lines   {pct:5.1f}%")
