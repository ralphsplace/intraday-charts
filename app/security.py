"""Who may use the dashboard: devices on your home network only. No logins; the network is the boundary.

Three checks on every request (ASGI middleware):
  1. Client address: must be in ALLOWED_NETWORKS (default: loopback and the private home-network ranges).
  2. Host header: the address typed in the browser must be an IP in those networks, "localhost", a single-word
     machine name (e.g. "nas"), Docker's names (*.docker.internal, e.g. host.docker.internal), a home-network
     name (.local, .lan, .home, .home.arpa, .internal), or one listed in ALLOWED_HOSTS. This blocks "DNS rebinding", where a website's own domain is pointed at your NAS.
  3. Changes (POST, PUT, PATCH, DELETE) must come from the dashboard's own pages: a request a browser marks as
     sent from another site is refused, so a web page you visit can't queue fetches or edit dashboards.

    ALLOWED_NETWORKS=192.168.1.0/24,127.0.0.1/32     # narrow it to your subnet or devices
    ALLOWED_HOSTS=mynas.example.home                  # extra names you use to reach the NAS
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

DEFAULT_NETWORKS = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
# Docker's own names (host.docker.internal, gateway.docker.internal, ...) are always accepted
DOCKER_SUFFIX = ".docker.internal"
HOME_SUFFIXES = (DOCKER_SUFFIX, ".local", ".lan", ".home", ".home.arpa", ".internal")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ConfigError(ValueError):
    pass


def parse_networks(text: str | None = None) -> list:
    text = DEFAULT_NETWORKS if text is None or not text.strip() else text
    nets = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ConfigError(f"ALLOWED_NETWORKS: '{part}' is not an address or network (e.g. 192.168.1.0/24)") from None
    if not nets:
        raise ConfigError("ALLOWED_NETWORKS is empty")
    return nets


def is_home_network(net) -> bool:
    """Loopback, private (RFC 1918 / unique-local) or link-local: never reachable from the internet."""
    return net.is_loopback or net.is_private or net.is_link_local


def public_networks(nets) -> list:
    return [n for n in nets if not is_home_network(n)]


def _ip(text: str):
    try:
        return ipaddress.ip_address(text.split("%")[0])
    except ValueError:
        return None


def client_allowed(host: str | None, nets) -> bool:
    ip = _ip(host or "")
    if ip is None:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return any(ip in n for n in nets)


def host_name(header: str) -> str:
    """The name or address part of a Host header ("nas:8050" -> "nas", "[::1]:8050" -> "::1")."""
    h = header.strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h[1:]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def host_allowed(header: str | None, nets, extra: set[str]) -> bool:
    if not header:
        return False
    name = host_name(header)
    ip = _ip(name)
    if ip is not None:
        return any(ip in n for n in nets)
    name = name.rstrip(".")
    return (name == "localhost" or name in extra or "." not in name
            or any(name.endswith(s) for s in HOME_SUFFIXES))


def cross_site(headers: dict[str, str]) -> bool:
    """True when a browser says the request came from another site."""
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site not in ("same-origin", "none")
    origin = headers.get("origin")
    if origin and origin != "null":
        return urlsplit(origin).netloc.lower() != headers.get("host", "").lower()
    return origin == "null"


class Settings:
    def __init__(self, networks: str | None = None, hosts: str | None = None):
        self.networks = parse_networks(networks if networks is not None else os.environ.get("ALLOWED_NETWORKS"))
        raw = hosts if hosts is not None else os.environ.get("ALLOWED_HOSTS", "")
        self.hosts = {h.strip().lower().rstrip(".") for h in raw.replace(";", ",").split(",") if h.strip()}


class LocalOnly:
    """ASGI middleware applying the three checks above."""

    def __init__(self, app, settings: Settings | None = None):
        self.app = app
        self.settings = settings or Settings()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client = (scope.get("client") or (None, None))[0]
        s = self.settings
        if not client_allowed(client, s.networks):
            return await _refuse(send, f"This dashboard only answers devices on your home network (not {client}).")
        if not host_allowed(headers.get("host"), s.networks, s.hosts):
            return await _refuse(send, "Unknown address for this dashboard. Use its IP address or machine name, "
                                       "or add the name to ALLOWED_HOSTS.")
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS and cross_site(headers):
            return await _refuse(send, "Changes are only accepted from the dashboard's own pages.")
        return await self.app(scope, receive, send)


async def _refuse(send, message: str):
    body = message.encode()
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
