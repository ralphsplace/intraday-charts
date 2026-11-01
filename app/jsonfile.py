"""JSON files the user owns (the application config, saved views and layouts): read them, and change them safely.

One job, in one place: several server worker processes may change the same file, so a change holds a lock and
replaces the file atomically. A file that doesn't parse (a typo made by hand) is never written over: the change is
refused with a BrokenFile error naming the file, and reads treat it as empty until it's fixed.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)


class BrokenFile(Exception):
    """A user file that exists but isn't a JSON object. Not a ValueError: it isn't bad input from the request, so
    the routes that turn bad input into a 400 let it through to the server's 409 that names the file."""


def _load(p: Path) -> dict:
    try:
        text = p.read_text()
    except FileNotFoundError:
        return {}
    try:
        d = json.loads(text)
    except ValueError as e:
        raise BrokenFile(f"{p.name} isn't valid JSON ({e}); fix or remove it, nothing was changed") from e
    if not isinstance(d, dict):
        raise BrokenFile(f"{p.name} should hold a JSON object; fix or remove it, nothing was changed")
    return d


def read(p: Path) -> dict:
    """The file's contents, or {} if it's missing or broken (logged, so the cause can be found)."""
    try:
        return _load(p)
    except BrokenFile as e:
        log.warning("%s", e)
        return {}
    except OSError as e:
        log.warning("can't read %s: %s", p, e)
        return {}


@contextmanager
def editing(p: Path):
    """The file's contents to change in place, written back atomically when the block ends without an error.
    Raises BrokenFile, writing nothing, if the file exists but doesn't parse."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            d = _load(p)
            yield d
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
            os.replace(tmp, p)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
