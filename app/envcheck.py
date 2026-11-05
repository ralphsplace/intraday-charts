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

from . import control, live_orders, positions, security, store

ROOT = Path(__file__).resolve().parent.parent
# names of TWS API calls and objects that place, change or cancel orders; only the trader may use them
ORDER_FILES = {"tools/trader.py"}            # the one place orders are placed (#84): the IBKR paper account, when on
ORDER_CALLS = re.compile(r"\b(placeOrder|cancelOrder|reqGlobalCancel|whatIfOrder|bracketOrder|oneCancelsAll|"
                         r"MarketOrder|LimitOrder|StopOrder|StopLimitOrder|exerciseOptions)\b")


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def order_calls(paths=None) -> list[str]:
    """file:line for every order call in the app and tools code outside the trader (should be none)."""
    hits = []
    for p in paths or [*sorted((ROOT / "app").rglob("*.py")), *sorted((ROOT / "tools").glob("*.py"))]:
        rel = Path(p).relative_to(ROOT).as_posix()
        if Path(p).name == "envcheck.py" or rel in ORDER_FILES:
            continue
        for i, line in enumerate(Path(p).read_text().splitlines(), 1):
            if ORDER_CALLS.search(line):
                hits.append(f"{rel}:{i}")
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


def orders_check() -> dict:
    """Where orders can come from: nowhere, or (LIVE_ORDERS=paper) only the trader, only to an IBKR paper account."""
    hits = order_calls()
    holdings = ("The collector reads the account's positions for the Holdings list (HOLDINGS=on)." if positions.turned_on()
                else "The live account's positions, orders and executions are never read (Holdings list off).")
    if hits:
        return _check("Orders", "fail", "Order calls outside tools/trader.py: " + ", ".join(hits))
    if not live_orders.turned_on():
        return _check("Orders", "ok", "Orders are off: every TWS connection is opened read-only, and nothing places, "
                      "changes or cancels an order. " + holdings)
    t = live_orders.read_status()
    where = (f"TWS at {t.get('host')}:{t.get('port')}, account {t.get('account')}" if t.get("account") else "the paper TWS")
    if t.get("refused"):
        return _check("Orders", "warn", f"Orders to the IBKR paper account are on (LIVE_ORDERS=paper), and refused: "
                      f"{t['refused']}")
    return _check("Orders", "ok", "Orders to the IBKR paper account are on (LIVE_ORDERS=paper): only the collector's "
                  f"trader places them, on its own connection to {where}, and only while TWS reports a paper account "
                  f"(DU…); at most {live_orders.max_shares():,} shares an order. The market data connection stays "
                  "read-only. " + holdings)


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

    out.append(orders_check())

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
