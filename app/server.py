"""Web server: builds the app from the API modules in app/api/ (one per area of the app) and serves the pages.

The app starts only when the environment check passes, answers devices on the home network only, and refuses
changes to a user file that doesn't parse instead of writing over it.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import envcheck, jsonfile, security, upgrade
from .api import charts, config, dashboards, earnings, expected_move, options, pages, saved, watch
from .api.common import ROOT
from .api.pages import STATIC_VERSION, Revalidated  # noqa: F401  (STATIC_VERSION: read by the tests)

log = logging.getLogger("intraday-charts")


@asynccontextmanager
async def lifespan(_app):
    """Check the environment before serving (a failed check stops the server; app/envcheck.py), then bring what
    older versions saved up to date (app/upgrade.py)."""
    checks = envcheck.run()
    for c in checks:
        log.warning("environment check: %-24s %-4s %s", c["name"], c["status"], c["detail"])
    bad = envcheck.failures(checks)
    if bad:
        raise RuntimeError("Not starting: " + " ".join(f"{c['name']}: {c['detail']}" for c in bad))
    upgrade.run()                                               # what older versions saved, to today's shapes
    yield


def _settings() -> security.Settings:
    try:
        return security.Settings()
    except security.ConfigError:
        return security.Settings(networks="127.0.0.1/32")      # the startup check reports the error and stops


app = FastAPI(title="Intraday charts", lifespan=lifespan)
app.add_middleware(security.LocalOnly, settings=_settings())    # home network only; see app/security.py


@app.exception_handler(jsonfile.BrokenFile)
def broken_file(_request, e: jsonfile.BrokenFile):
    """A hand-edited user file that doesn't parse: say which, and change nothing (it's never written over)."""
    return JSONResponse({"detail": str(e)}, status_code=409)


for area in (charts, watch, saved, config, dashboards, earnings, expected_move, options):
    app.include_router(area.router)
app.mount("/static", Revalidated(directory=ROOT / "static"), name="static")
app.include_router(pages.router)                                # last: it ends with /{name}
