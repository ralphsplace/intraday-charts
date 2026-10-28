#!/bin/sh
# Builds the image and checks the container's protections: run from the project folder (CI runs it on each push).
#   sh tests/docker_smoke.sh
set -eu
P=intraday-smoke
D=$(mktemp -d)
mkdir -p "$D/data/user" && echo '{}' > "$D/data/user/views.json" && chmod -R 777 "$D/data"   # like data from an old root-run version
cleanup() { docker compose -p $P down -t 1 >/dev/null 2>&1 || true; rm -rf "$D" 2>/dev/null || true; }
trap cleanup EXIT
export CHART_PORT=18050
cp docker-compose.yml "$D/" && sed -i "s#\./data#$D/data#; s#\./config.json#$PWD/config.json#; s#build: \.#build: $PWD#" "$D/docker-compose.yml"
C="docker compose -p $P -f $D/docker-compose.yml"
fail() { echo "FAIL: $*"; $C logs chart | tail -20; exit 1; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

$C up -d --build >/dev/null 2>&1 || fail "container didn't start"
for i in $(seq 1 30); do [ "$(code http://127.0.0.1:$CHART_PORT/api/meta)" = 200 ] && break; sleep 1; done
[ "$(code http://127.0.0.1:$CHART_PORT/QQQs)" = 200 ] || fail "page not served"
[ "$(code -H 'Host: evil.example.com' http://127.0.0.1:$CHART_PORT/api/meta)" = 403 ] || fail "foreign host name accepted"
[ "$(code -X POST -H 'Content-Type: application/json' -H 'Sec-Fetch-Site: cross-site' -d '{"name":"X","type":"charts"}' \
     http://127.0.0.1:$CHART_PORT/api/dashboards)" = 403 ] || fail "cross-site change accepted"
[ "$($C exec -T chart sh -c 'grep -c "^Uid:[[:space:]]*0[[:space:]]" /proc/1/status' || true)" = 0 ] || fail "server runs as root"
[ "$($C exec -T chart sh -c 'grep CapEff /proc/1/status')" = "$(printf 'CapEff:\t0000000000000000')" ] || fail "server has capabilities"
$C exec -T chart sh -c 'echo x > /app/x' 2>/dev/null && fail "system files writable"
[ "$(stat -c %u "$D/data/user/views.json")" = 1000 ] || fail "data not handed to the app user"
case "$(stat -c %a "$D/data/user/views.json")" in *[2367]) fail "data writable by everyone";; esac
[ "$(code -H 'Host: host.docker.internal:8050' http://127.0.0.1:$CHART_PORT/api/meta)" = 200 ] || fail "host.docker.internal refused"
[ "$($C exec -T chart sh -c 'echo $IB_HOST')" = host.docker.internal ] || fail "IB_HOST isn't host.docker.internal by default"
$C exec -T chart python -c "import socket; socket.gethostbyname('host.docker.internal')" \
  || fail "host.docker.internal doesn't resolve in the container"
$C restart chart >/dev/null 2>&1
for i in $(seq 1 30); do [ "$(code http://127.0.0.1:$CHART_PORT/api/meta)" = 200 ] && break; sleep 1; done
[ "$(code http://127.0.0.1:$CHART_PORT/api/meta)" = 200 ] || fail "didn't come back after a restart"
$C run --rm -T -e IB_HOST=8.8.8.8 chart python tools/fetch_ibkr.py --symbols QQQ --days 1 2>&1 | grep -q "Refusing to connect" \
  || fail "public TWS address accepted"
echo "docker smoke test: all checks passed"
