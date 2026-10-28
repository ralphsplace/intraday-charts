#!/bin/sh
# Starts the chart server, or the command given (e.g. python tools/fetch_ibkr.py ...), as a normal user.
#
# Started as root (the default in Docker), it first gives the data folder to the app user (APP_UID/APP_GID,
# default 1000), then drops root for good. A new install starts with an empty cache: load data from the page
# (Load data...) or let the TWS collector fill it.
set -e
APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  # only files not already the app user's (data written by earlier versions, which ran as root)
  find "$DATA_DIR" \( ! -user "$APP_UID" -o ! -group "$APP_GID" \) -exec chown "$APP_UID:$APP_GID" {} + \
    || echo "start.sh: some files in $DATA_DIR couldn't be given to user $APP_UID; the environment check will say if that matters"
  exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups --inh-caps=-all -- "$0" "$@"
fi

umask 027
# nothing in the data folder may be writable by other users of the machine
find "$DATA_DIR" -perm -o+w -exec chmod o-w {} +
mkdir -p "$DATA_DIR/bars" "$DATA_DIR/control/requests" "$DATA_DIR/user"
[ -f "$DATA_DIR/events.json" ] || echo "[]" > "$DATA_DIR/events.json"

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec uvicorn app.server:app --host 0.0.0.0 --port 8050 --workers "${WEB_WORKERS:-2}"
