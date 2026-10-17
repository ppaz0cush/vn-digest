"""Notion writer for the weekly digest.

The digest writes ONLY to its own database, "VN Digest Weekly". The original
database (env NOTION_DB_ID) is never written to. It's read once, just to find
the page it lives on so the weekly database can be created next to it, and
every write path refuses its id.

Which database is the weekly one (first match wins):
  1. env NOTION_WEEKLY_DB_ID
  2. the id remembered in the tracking state
  3. a database the integration can see titled exactly "VN Digest Weekly"
  4. otherwise it's created (normal runs only; dry runs and prune never create)

Rows are keyed by the URL property. Creating a row sets Status=New; updating a
row never touches Status, so your triage (Read/Saved/Skipped) is preserved.

Env: NOTION_TOKEN (integration secret), NOTION_DB_ID (original database, read
only), optional NOTION_WEEKLY_DB_ID, optional NOTION_PARENT_PAGE_ID (where to
create the weekly database instead of next to the original).
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
WEEKLY_DB_TITLE = "VN Digest Weekly"

STATUS_OPTIONS = [
    {"name": "New", "color": "yellow"},
    {"name": "Read", "color": "gray"},
    {"name": "Saved", "color": "green"},
    {"name": "Skipped", "color": "red"},
]
SCHEMA = {
    "Title": {"title": {}},
    "URL": {"url": {}},
    "Source": {"multi_select": {}},   # [source, sub-forum], e.g. ["voz", "diem bao"]
    "Label": {"select": {}},          # Top (weekly ranking) / Latest (every post)
    "Status": {"select": {"options": STATUS_OPTIONS}},
    "Score": {"number": {}},          # total views (voz) or comments (tinhte/vnexpress)
    "Δ week": {"number": {}},         # voz: views gained this week
    "Prev score": {"number": {}},     # voz: views at the start of the week
    "Rank": {"number": {}},           # position in this week's list
    "Published": {"date": {}},        # article date / voz thread start
    "Fetched": {"date": {}},          # when the row was written or updated (prune uses it)
}


class NotionError(RuntimeError):
    pass


def _norm(db_id):
    return (db_id or "").replace("-", "").lower()


def _iso(v):
    """Notion date 'start' must be an ISO string — coerce datetimes."""
    return v.isoformat() if isinstance(v, datetime) else v


def properties(row, *, creating):
    """Notion properties for a row. Status is only set when creating, so your
    triage is never overwritten."""
    tags = [t for t in (row.get("source"), row.get("subsource")) if t]
    text = {"content": (row.get("title") or "(untitled)")[:2000]}
    if row.get("url"):
        text["link"] = {"url": row["url"]}     # clicking the title opens the post
    props = {
        "Title": {"title": [{"type": "text", "text": text}]},
        "URL": {"url": row.get("url")},
        "Source": {"multi_select": [{"name": t} for t in tags]},
        "Label": {"select": {"name": row["label"]} if row.get("label") else None},
        "Score": {"number": row.get("score")},
        "Δ week": {"number": row.get("delta")},
        "Prev score": {"number": row.get("prev_score")},
        "Rank": {"number": row.get("rank")},
        "Published": {"date": {"start": _iso(row["published_at"])} if row.get("published_at") else None},
        "Fetched": {"date": {"start": _iso(row["fetched_at"])} if row.get("fetched_at") else None},
    }
    if creating:
        props["Status"] = {"select": {"name": "New"}}
    return props


class Notion:
    def __init__(self, token=None, original_db_id=None):
        self.token = token or os.environ.get("NOTION_TOKEN")
        if not self.token:
            raise NotionError("NOTION_TOKEN must be set")
        self.original_db_id = (os.environ.get("NOTION_DB_ID")
                               if original_db_id is None else original_db_id)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })

    def _call(self, method, path, payload=None, attempts=4):
        for attempt in range(1, attempts + 1):
            r = self.session.request(method, f"{API}{path}", json=payload, timeout=30)
            time.sleep(0.34)  # Notion allows ~3 requests/second
            if r.status_code < 300:
                return r.json()
            retryable = r.status_code in (409, 429) or r.status_code >= 500
            if not retryable or attempt == attempts:
                raise NotionError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            time.sleep(float(r.headers.get("Retry-After") or 2 ** attempt))

    def _guard(self, db_id):
        if self.original_db_id and _norm(db_id) == _norm(self.original_db_id):
            raise NotionError("refusing to touch the original database (NOTION_DB_ID); "
                              "the weekly digest only writes to its own database")

    # --- finding / creating the weekly database ---------------------------------

    def _exists(self, db_id):
        try:
            db = self._call("GET", f"/databases/{db_id}")
        except NotionError as exc:
            if " -> 404" in str(exc) or " -> 400" in str(exc):
                return False
            raise
        return not (db.get("archived") or db.get("in_trash"))

    def find_database(self, title=WEEKLY_DB_TITLE):
        payload = {"query": title, "filter": {"value": "database", "property": "object"},
                   "page_size": 100}
        while True:
            data = self._call("POST", "/search", payload)
            for db in data.get("results", []):
                name = "".join(t.get("plain_text", "") for t in db.get("title", []))
                if name == title and not (db.get("archived") or db.get("in_trash")):
                    return db["id"]
            if not data.get("has_more"):
                return None
            payload["start_cursor"] = data["next_cursor"]

    def create_database(self, parent_page_id, title=WEEKLY_DB_TITLE):
        db = self._call("POST", "/databases", {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": SCHEMA,
        })
        print(f"[notion] created the '{title}' database: {db.get('url')}")
        return db["id"]

    def _parent_page(self):
        explicit = os.environ.get("NOTION_PARENT_PAGE_ID")
        if explicit:
            return explicit
        if not self.original_db_id:
            raise NotionError("set NOTION_DB_ID or NOTION_PARENT_PAGE_ID so the weekly "
                              "database can be created")
        parent = self._call("GET", f"/databases/{self.original_db_id}").get("parent", {})
        if parent.get("type") != "page_id":
            raise NotionError("the original database isn't inside a page; set NOTION_PARENT_PAGE_ID")
        return parent["page_id"]

    def weekly_database(self, state=None, create=True):
        """The weekly database id (remembered in `state`); None if it doesn't
        exist yet and create is False."""
        db_id = os.environ.get("NOTION_WEEKLY_DB_ID")
        if not db_id:
            db_id = state.weekly_db_id if state is not None else None
            if db_id and not self._exists(db_id):
                print(f"[notion] remembered database {db_id} is gone; looking it up again")
                db_id = None
            db_id = db_id or self.find_database()
            if not db_id:
                if not create:
                    return None
                db_id = self.create_database(self._parent_page())
        self._guard(db_id)
        if state is not None:
            state.weekly_db_id = db_id
        return db_id

    # --- rows -------------------------------------------------------------------

    def index(self, db_id):
        """{url: page_id} for every row in the database."""
        self._guard(db_id)
        out, payload = {}, {"page_size": 100}
        while True:
            data = self._call("POST", f"/databases/{db_id}/query", payload)
            for page in data.get("results", []):
                url = (page.get("properties", {}).get("URL") or {}).get("url")
                if url:
                    out[url] = page["id"]
            if not data.get("has_more"):
                return out
            payload["start_cursor"] = data["next_cursor"]

    def write(self, db_id, rows, index, *, update_existing=True):
        """Create rows whose URL isn't in `index` yet; update the others (or leave
        them alone if update_existing is False). Returns (created, updated, failed_urls)."""
        self._guard(db_id)
        created = updated = 0
        failed = []
        for row in rows:
            try:
                page_id = index.get(row["url"])
                if page_id is None:
                    page = self._call("POST", "/pages", {"parent": {"database_id": db_id},
                                                         "properties": properties(row, creating=True)})
                    index[row["url"]] = page["id"]
                    created += 1
                elif update_existing:
                    self._call("PATCH", f"/pages/{page_id}",
                               {"properties": properties(row, creating=False)})
                    updated += 1
            except NotionError as exc:
                failed.append(row["url"])
                print(f"[notion] {exc}")
        return created, updated, failed

    def archive_older_than(self, db_id, days):
        """Archive (move to Notion's trash) every row last fetched more than
        `days` ago. Returns how many were archived."""
        self._guard(db_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        payload = {"page_size": 100, "filter": {"property": "Fetched", "date": {"before": cutoff}}}
        ids = []
        while True:
            data = self._call("POST", f"/databases/{db_id}/query", payload)
            ids += [page["id"] for page in data.get("results", [])]
            if not data.get("has_more"):
                break
            payload["start_cursor"] = data["next_cursor"]
        for page_id in ids:
            self._call("PATCH", f"/pages/{page_id}", {"archived": True})
        return len(ids)
