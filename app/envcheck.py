"""Checks that the dashboard runs in a secure local environment. Run when the server starts (a failed check
stops it) and shown on the Dashboards page.

    ok    as it should be
    warn  works, but worth fixing
    fail  the server refuses to start
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import stat
from pathlib import Path

from . import control, security, store

ROOT = Path(__file__).resolve().parent.parent
# names of TWS API calls that place, change or cancel orders; none may appear in this project's code
ORDER_CALLS = re.compile(r"\b(placeOrder|cancelOrder|reqGlobalCancel|whatIfOrder|bracketOrder|oneCancelsAll|"
                         r"MarketOrder|LimitOrder|StopOrder|StopLimitOrder|exerciseOptions)\b")


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def order_calls(paths=None) -> list[str]:
    """file:line for every order call in the app and tools code (should be none)."""
    hits = []
    for p in paths or [*sorted((ROOT / "app").glob("*.py")), *sorted((ROOT / "tools").glob("*.py"))]:
        for i, line in enumerate(Path(p).read_text().splitlines(), 1):
            if ORDER_CALLS.search(line) and Path(p).name != "envcheck.py":
                hits.append(f"{Path(p).relative_to(ROOT)}:{i}")
    return hits


def tws_host_status(host: str) -> tuple[str, str]:
    """Is the TWS address on this machine or the home network? ("ok"/"warn"/"fail", explanation)."""
    host = (host or "").strip().lower().rstrip(".")
    if host == "localhost":
        return "ok", "localhost (this machine)"
    if host.endswith(security.DOCKER_SUFFIX):
        return "ok", f"{host} (Docker's name for the machine running Docker)"
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = sorted({ipaddress.ip_address(a[4][0].split("%")[0]) for a in socket.getaddrinfo(host, None)})
        except OSError:
            return "warn", f"{host} doesn't resolve to an address yet"
    public = [str(ip) for ip in ips if not (ip.is_loopback or ip.is_private or ip.is_link_local)]
    if public:
        return "fail", f"{host} is a public internet address ({', '.join(public)}); TWS must be on your home network"
    return "ok", f"{host} ({', '.join(map(str, ips))}) is on this machine or your home network"


def require_local_tws(host: str) -> None:
    """For the tools that connect to TWS: refuse a public address."""
    status, detail = tws_host_status(host)
    if status == "fail":
        raise SystemExit(f"Refusing to connect: {detail}.")


def run(settings: security.Settings | None = None) -> list[dict]:
    out = []
    try:
        s = settings or security.Settings()
        public = security.public_networks(s.networks)
        nets = ", ".join(str(n) for n in s.networks)
        if public:
            out.append(_check("Who can connect", "fail", "ALLOWED_NETWORKS includes internet addresses: "
                              + ", ".join(map(str, public)) + ". Use home-network ranges only."))
        else:
            out.append(_check("Who can connect", "ok", f"Only devices on your home network: {nets}."))
        names = ", ".join(sorted(s.hosts)) or "none"
        out.append(_check("Addresses accepted", "ok", "IP addresses in those networks, localhost, machine names "
                          f"(e.g. nas), Docker's *.docker.internal names, .local/.lan/.home names; extra names: {names}."))
    except security.ConfigError as e:
        out.append(_check("Who can connect", "fail", str(e)))

    if hasattr(os, "geteuid"):
        root = os.geteuid() == 0
        out.append(_check("Runs as a normal user", "warn" if root else "ok",
                          "The server is running as root; start it with start.sh or as a normal user." if root
                          else f"User id {os.geteuid()}, not root."))

    d = store.DATA_DIR
    try:
        mode = d.stat().st_mode
        if mode & stat.S_IWOTH:
            out.append(_check("Data folder", "warn", f"{d} can be changed by every user on the machine (chmod o-w)."))
        elif not os.access(d, os.W_OK):
            out.append(_check("Data folder", "warn", f"The server can't write to {d}."))
        else:
            out.append(_check("Data folder", "ok", f"{d}: writable by the dashboard, not by everyone."))
    except OSError:
        out.append(_check("Data folder", "warn", f"{d} doesn't exist yet."))

    hits = order_calls()
    out.append(_check("Read-only trading data", "fail" if hits else "ok",
                      "Order calls found in the code: " + ", ".join(hits) if hits else
                      "No code that places, changes or cancels orders; every TWS connection is opened read-only."))

    col = control.read_status()
    host = col.get("host")
    if not host:
        out.append(_check("TWS connection", "warn", "The collector hasn't reported yet."))
    else:
        status, detail = tws_host_status(host)
        ro = col.get("read_only")
        if ro is False:
            status, detail = "fail", "The collector reports a connection that isn't read-only."
        out.append(_check("TWS connection", status, detail + (", read-only." if ro else ".")))

    sec = "The TWS collector looks up earnings dates on SEC EDGAR (sec.gov, public filings, read-only)." \
        if os.environ.get("SEC_CONTACT", "").strip() else "Earnings-date lookups on SEC EDGAR are off (no SEC_CONTACT)."
    fv = (" The TWS collector fetches FinViz watch lists (finviz.com, with your FinViz Elite token, read-only)."
          if os.environ.get("FINVIZ", "").strip() else " FinViz watch lists are off (no FINVIZ_TOKEN).")
    out.append(_check("Internet access", "ok", "The dashboard makes no internet requests. " + sec + fv + " The market-events "
                      "tool goes online only when you run it with --gdelt."))
    return out


def failures(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["status"] == "fail" and c["name"] != "TWS connection"]
