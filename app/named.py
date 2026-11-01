"""App-wide named things kept in a section of the application config (app/app_config.py): watch lists, paper
accounts, and any later kind. One set for the whole app, so every dashboard, browser and device sees the same.

One job, the rules every kind shares: a name is unique (it's the key); a new one without a name is called
"<Default> N", N one more than the highest in use; each item has an id that never changes, so whatever refers to
it still finds it after a rename; a rename is a move, never a copy. What an item holds is its kind's business.
"""
from __future__ import annotations

import re
import uuid

from . import app_config, saved


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Named:
    def __init__(self, section: str, default: str, what: str):
        self.section, self.default, self.what = section, default, what      # e.g. "watchlists", "Watch list", "watch list"
        self._n = re.compile(rf"^{re.escape(default)} (\d+)$")

    def items(self) -> dict:
        """{name: item} as stored (the kind checks the contents)."""
        return {n: v for n, v in app_config.section(self.section).items() if isinstance(v, dict)}

    def next_name(self, names) -> str:
        used = [int(m.group(1)) for m in (self._n.match(n) for n in names) if m]
        return f"{self.default} {max(used, default=0) + 1}"

    def check_name(self, name: str) -> str:
        name = (name or "").strip()
        if not saved.valid_name(name):
            raise ValueError(f"Names are 1 to {saved.NAME_MAX} characters, without / or \\")
        return name

    def create(self, item: dict, name: str | None = None) -> tuple[str, dict]:
        """A new item, under `name` or the next default name; ValueError if the name is taken or invalid."""
        item = {"id": new_id(), **item}
        with app_config.editing() as d:
            sec = d.setdefault(self.section, {})
            name = self.check_name(name) if name else self.next_name(sec)
            if name in sec:
                raise ValueError(f'There is already a {self.what} called "{name}"')
            sec[name] = item
        return name, item

    def replace(self, name: str, item: dict) -> dict:
        """New contents under the same name and id; KeyError when there's no such item."""
        with app_config.editing() as d:
            sec = d.setdefault(self.section, {})
            if name not in sec:
                raise KeyError(f'No {self.what} called "{name}"')
            item = {**item, "id": sec[name].get("id") or new_id()}
            sec[name] = item
        return item

    def rename(self, old: str, new: str) -> dict:
        """The item under a new name, the same id and contents: a move, never a copy."""
        new = self.check_name(new)
        with app_config.editing() as d:
            sec = d.setdefault(self.section, {})
            if old not in sec:
                raise KeyError(f'No {self.what} called "{old}"')
            if new != old and new in sec:
                raise ValueError(f'There is already a {self.what} called "{new}"')
            item = sec.pop(old)
            sec[new] = item
        return item

    def delete(self, name: str) -> dict | None:
        """The item removed (None when there was none)."""
        with app_config.editing() as d:
            return d.setdefault(self.section, {}).pop(name, None)

    def find(self, id_or_name: str) -> tuple[str, dict] | tuple[None, None]:
        """By id first (it may have been renamed), else by name."""
        items = self.items()
        for n, v in items.items():
            if v.get("id") == id_or_name:
                return n, v
        return (id_or_name, items[id_or_name]) if id_or_name in items else (None, None)
