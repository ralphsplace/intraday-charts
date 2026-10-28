"""Home-network-only access, cross-site protection, the startup environment check, and read-only trading."""
import ast
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fetch_ibkr
import market_events as me
from app import control, envcheck, security, server, store

ROOT = Path(__file__).resolve().parent.parent
HOME = ("192.168.1.20", 50000)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def client(addr=HOME, **kw):
    return TestClient(server.app, client=addr, **kw)


# ---------------------------------------------------------------- who can connect
@pytest.mark.parametrize("addr,ok", [("127.0.0.1", True), ("::1", True), ("192.168.1.20", True), ("10.0.0.5", True),
                                     ("172.20.0.1", True), ("8.8.8.8", False), ("2001:4860::1", False),
                                     ("testclient", False), (None, False)])
def test_only_home_network_clients(data, addr, ok):
    r = client((addr, 1) if addr else None).get("/api/meta")
    assert (r.status_code == 200) is ok
    if not ok:
        assert "home network" in r.text


def test_static_files_and_pages_are_protected_too(data):
    outside = client(("203.0.113.9", 1))
    for path in ("/", "/dashboards", "/static/js/main.js", "/api/dashboards"):
        assert outside.get(path).status_code == 403, path


@pytest.mark.parametrize("host,ok", [("192.168.1.10:8050", True), ("localhost:8050", True), ("nas:8050", True),
                                     ("nas.local", True), ("[::1]:8050", True), ("synology.home.arpa", True),
                                     ("host.docker.internal:8050", True), ("gateway.docker.internal", True),
                                     ("HOST.DOCKER.INTERNAL.", True), ("docker.internal.evil.com", False),
                                     ("evil.example.com", False), ("8.8.8.8:8050", False), ("", False)])
def test_host_header_blocks_dns_rebinding(data, host, ok):
    r = client(headers={"host": host}).get("/api/meta")
    assert (r.status_code == 200) is ok, host


def test_extra_host_names_and_narrow_networks():
    s = security.Settings(networks="192.168.1.0/24", hosts="charts.myhouse.net")
    assert security.host_allowed("charts.myhouse.net:8050", s.networks, s.hosts)
    assert security.client_allowed("192.168.1.7", s.networks)
    assert not security.client_allowed("192.168.2.7", s.networks)
    assert not security.client_allowed("127.0.0.1", s.networks)
    assert security.client_allowed("::ffff:192.168.1.7", s.networks)       # IPv4 seen through IPv6
    with pytest.raises(security.ConfigError):
        security.Settings(networks="192.168.1.0/24, not-a-network")


# ---------------------------------------------------------------- changes only from the dashboard's own pages
@pytest.mark.parametrize("headers,ok", [
    ({}, True),                                                               # scripts, curl: no browser headers
    ({"sec-fetch-site": "same-origin"}, True),
    ({"sec-fetch-site": "none"}, True),                                       # typed in the address bar
    ({"sec-fetch-site": "cross-site"}, False),                                # another website
    ({"sec-fetch-site": "same-site"}, False),                                 # another app on the NAS
    ({"origin": "http://testserver"}, True),
    ({"origin": "http://evil.example.com"}, False),
    ({"origin": "null"}, False),                                              # sandboxed pages, file://
])
def test_changes_refused_from_other_sites(data, headers, ok):
    r = client().post("/api/dashboards", json={"name": "Probe", "type": "charts"}, headers=headers)
    assert (r.status_code == 200) is ok, headers
    if not ok:
        assert r.status_code == 403 and "own pages" in r.text


def test_reading_is_allowed_from_any_page_on_the_network(data):
    assert client().get("/api/meta", headers={"sec-fetch-site": "cross-site"}).status_code == 200


def test_no_cross_site_headers(data):
    r = client().get("/api/meta", headers={"origin": "http://evil.example.com"})
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]


# ---------------------------------------------------------------- the startup check
def test_environment_endpoint_and_checks(data):
    checks = {c["name"]: c for c in client().get("/api/environment").json()["checks"]}
    assert checks["Who can connect"]["status"] == "ok"
    assert checks["Read-only trading data"]["status"] == "ok"
    assert checks["TWS connection"]["status"] == "warn"                     # no collector yet
    assert checks["Internet access"]["status"] == "ok"
    control.write_status({"host": "192.168.1.50", "port": 7496, "read_only": True})
    tws = {c["name"]: c for c in envcheck.run()}["TWS connection"]
    assert tws["status"] == "ok" and "read-only" in tws["detail"]


def test_server_refuses_to_start_on_internet_networks(data, monkeypatch):
    monkeypatch.setenv("ALLOWED_NETWORKS", "0.0.0.0/0")
    with pytest.raises(RuntimeError, match="internet addresses"), TestClient(server.app, client=HOME):
        pass
    monkeypatch.setenv("ALLOWED_NETWORKS", "192.168.1.0/24")
    with TestClient(server.app, client=HOME) as c:                            # starts fine
        assert c.get("/api/meta").status_code == 200


def test_world_writable_data_folder_is_flagged(data):
    os.chmod(data, 0o777)
    folder = {c["name"]: c for c in envcheck.run()}["Data folder"]
    assert folder["status"] == "warn" and "every user" in folder["detail"]
    os.chmod(data, 0o755)


@pytest.mark.parametrize("host,status", [("127.0.0.1", "ok"), ("localhost", "ok"), ("host.docker.internal", "ok"),
                                         ("gateway.docker.internal", "ok"), ("Host.Docker.Internal", "ok"),
                                         ("docker.internal.evil.com", "warn"),
                                         ("192.168.1.50", "ok"), ("8.8.8.8", "fail"), ("no-such-host.invalid", "warn")])
def test_tws_address_must_be_local(host, status):
    assert envcheck.tws_host_status(host)[0] == status


def test_tools_refuse_a_public_tws_address(data):
    with pytest.raises(SystemExit, match="public internet address"):
        fetch_ibkr.main(["--host", "8.8.8.8", "--symbols", "QQQ", "--days", "1"])
    with pytest.raises(SystemExit, match="public internet address"):
        me.connect_tws(type("A", (), {"host": "8.8.8.8", "port": 7496, "client_id": 20})())


# ---------------------------------------------------------------- read-only, enforced
def test_no_order_calls_anywhere():
    assert envcheck.order_calls() == []
    planted = ROOT / "tools" / "_planted_for_test.py"
    try:
        planted.write_text("ib.placeOrder(contract, order)\n")
        assert envcheck.order_calls() == ["tools/_planted_for_test.py:1"]
    finally:
        planted.unlink()


def test_every_tws_connection_is_read_only():
    calls = 0
    for path in [*ROOT.glob("app/*.py"), *ROOT.glob("tools/*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("connect", "connectAsync"):
                kw = {k.arg: k.value for k in node.keywords}
                if "clientId" in kw:                                          # an IB connection
                    calls += 1
                    assert isinstance(kw.get("readonly"), ast.Constant) and kw["readonly"].value is True, path
    assert calls >= 3


def test_tws_address_defaults_to_host_docker_internal(monkeypatch):
    monkeypatch.delenv("IB_HOST", raising=False)
    assert fetch_ibkr.parse_args(["--symbols", "QQQ"]).host == "host.docker.internal"
    text = (ROOT / ".env.example").read_text()
    assert "\nIB_HOST=host.docker.internal\n" in text
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "IB_HOST: ${IB_HOST:-host.docker.internal}" in compose
    assert '"host.docker.internal:host-gateway"' in compose
    for tool in ("market_events.py", "probe_ibkr.py"):
        assert 'os.environ.get("IB_HOST", "host.docker.internal")' in (ROOT / "tools" / tool).read_text()
