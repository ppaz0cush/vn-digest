"""Tracking state for the weekly digest: one small JSON file.

Notion only shows the results. Everything needed to compute them (view and
comment counts seen during the week, which posts were already written, when the
last weekly list went out) lives here. In CI the file is kept on the repo's
`state` branch: the workflow copies it to .state/state.json before a run and
pushes it back afterwards. Locally it's just that file (gitignored).

Layout (times are UTC ISO-8601 strings):
    {
      "version": 1,
      "tracking_since": "...",   # first run; the first weekly list is partial
      "last_publish": "...",     # when the last weekly list was written (or null)
      "weekly_db_id": "...",     # the Notion database the digest writes to
      "sources": {
        "<name>": {
          "failures": 0,         # consecutive failed runs (alerting)
          "items": {...},        # weekly sources: threads/articles seen
          "created": {url: ts}   # 'all' sources: posts already written to Notion
        }
      }
    }
"""
import json
import os
from datetime import timedelta
from pathlib import Path

from .util import from_iso, to_iso

VERSION = 1
DEFAULT_PATH = os.environ.get("VN_DIGEST_STATE", ".state/state.json")
KEEP_ITEMS_DAYS = 14   # forget weekly items not seen for this long


class State:
    def __init__(self, data=None, path=DEFAULT_PATH):
        self.path = Path(path)
        self.data = data or {}
        self.data.setdefault("version", VERSION)
        self.data.setdefault("tracking_since", None)
        self.data.setdefault("last_publish", None)
        self.data.setdefault("weekly_db_id", None)
        self.data.setdefault("sources", {})

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return cls(json.load(f), p)
        return cls(None, p)

    def save(self):
        """Write atomically, so a crash never leaves a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, self.path)

    def source(self, name):
        src = self.data["sources"].setdefault(name, {})
        src.setdefault("failures", 0)
        src.setdefault("items", {})
        src.setdefault("created", {})
        return src

    @property
    def tracking_since(self):
        return from_iso(self.data["tracking_since"])

    def start_tracking(self, now):
        if not self.data["tracking_since"]:
            self.data["tracking_since"] = to_iso(now)

    @property
    def last_publish(self):
        return from_iso(self.data["last_publish"])

    def mark_published(self, now):
        self.data["last_publish"] = to_iso(now)

    @property
    def weekly_db_id(self):
        return self.data.get("weekly_db_id")

    @weekly_db_id.setter
    def weekly_db_id(self, value):
        self.data["weekly_db_id"] = value

    def record_result(self, name, ok):
        """Track consecutive failures per source; returns the current streak."""
        src = self.source(name)
        src["failures"] = 0 if ok else src["failures"] + 1
        return src["failures"]

    def prune(self, now, keep_days=KEEP_ITEMS_DAYS):
        """Forget weekly items not seen for keep_days. ('created' markers are
        kept: they stop posts you pruned from Notion from coming back.)"""
        cutoff = now - timedelta(days=keep_days)
        for src in self.data["sources"].values():
            items = src.get("items", {})
            stale = [k for k, it in items.items()
                     if (from_iso(it.get("last_seen_at")) or now) < cutoff]
            for key in stale:
                del items[key]
