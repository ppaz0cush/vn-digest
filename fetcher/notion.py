"""Notion writer — an alternative sink to db.py (Supabase).

Same interface as db.py so main.py can target either (or both):
    fetch_prev_scores() -> {url: {"score": int|None, "last_score_at": str|None}}
    upsert_items(items)

Each item becomes a Notion page (row) with TYPED properties, so all of Notion's
filtering/sorting/views work natively:
    Title(title) URL(url) Source(select) Label(select) Status(select)
    Score(number) "Δ today"(number) "Prev score"(number) Rank(number)
    Published(date) Fetched(date) Detail(rich_text)

Env:
    NOTION_TOKEN  — internal integration secret (shared with the database)
    NOTION_DB_ID  — the database id (from setup/notion_init.py)

Dedup is on the URL property: we load the whole DB once (the index), then
create new rows or update existing ones. On UPDATE we deliberately DO NOT touch
Status, so your triage (Read/Saved/Skipped) is preserved across runs.
"""
import os
import time
from datetime import datetime, timezone, timedelta
import requests

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
STATUS_OPTIONS = [
    {"name": "New", "color": "yellow"},
    {"name": "Read", "color": "gray"},
    {"name": "Saved", "color": "green"},
    {"name": "Skipped", "color": "red"},
]

_index = None  # cache: {url: {"page_id","score","last_score_at"}} as of run start


def _config():
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DB_ID")
    if not token or not db_id:
        raise SystemExit("NOTION_TOKEN and NOTION_DB_ID must be set for the Notion target.")
    return token, db_id


def _headers():
    token, _ = _config()
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _throttle():
    time.sleep(0.34)  # Notion allows ~3 requests/second


def _num(prop):
    return prop.get("number") if prop else None


def _date_start(prop):
    d = prop.get("date") if prop else None
    return d.get("start") if d else None


def _load_index():
    """Scan the whole database once -> {url: {page_id, score, last_score_at}}."""
    global _index
    if _index is not None:
        return _index
    _index = {}
    db_id = _config()[1]
    payload = {"page_size": 100}
    while True:
        r = requests.post(f"{API}/databases/{db_id}/query", headers=_headers(),
                          json=payload, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"[notion] query failed {r.status_code}: {r.text[:300]}")
        data = r.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            url = (props.get("URL") or {}).get("url")
            if not url:
                continue
            _index[url] = {
                "page_id": page["id"],
                "score": _num(props.get("Score")),
                "last_score_at": _date_start(props.get("Fetched")),
            }
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
        _throttle()
    return _index


def fetch_prev_scores():
    # No creds (e.g. a --dry-run without a token) -> no deltas, but fetch runs.
    if not (os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DB_ID")):
        return {}
    try:
        idx = _load_index()
    except Exception as exc:
        print(f"[notion] could not read previous scores ({exc}); deltas start fresh")
        return {}
    return {url: {"score": v["score"], "last_score_at": v["last_score_at"]}
            for url, v in idx.items()}


def _title(title, url):
    """Title as a clickable link to the article (so clicking it opens the URL)."""
    t = {"type": "text", "text": {"content": (title or "(untitled)")[:2000]}}
    if url:
        t["text"]["link"] = {"url": url}
    return [t]


def _iso(v):
    """Notion date 'start' must be an ISO string — coerce datetimes."""
    if isinstance(v, datetime):
        return v.isoformat()
    return v  # already a string or None


def _properties(item, *, creating):
    """Build the Notion properties payload for an item. On update we omit Status
    so the user's triage is never overwritten."""
    # Source as multi-select: [source, sub-forum] e.g. ["voz", "diem bao"].
    src_tags = []
    if item.get("source"):
        src_tags.append(item["source"])
    if item.get("subsource"):
        src_tags.append(item["subsource"])

    props = {
        "Title": {"title": _title(item.get("title"), item.get("url"))},
        "URL": {"url": item.get("url")},
        "Source": {"multi_select": [{"name": t} for t in src_tags]},
        "Label": {"select": {"name": item["rank_label"]}} if item.get("rank_label") else {"select": None},
        "Score": {"number": item.get("score")},
        "Δ today": {"number": item.get("score_delta")},
        "Prev score": {"number": item.get("prev_score")},
        "Rank": {"number": item.get("rank_position")},
        "Published": {"date": {"start": _iso(item["published_at"])} if item.get("published_at") else None},
        "Fetched": {"date": {"start": _iso(item["last_score_at"])} if item.get("last_score_at") else None},
    }
    if creating:
        props["Status"] = {"select": {"name": "New"}}
    return props


def upsert_items(items):
    if not items:
        print("[notion] nothing to upsert")
        return
    db_id = _config()[1]
    index = _load_index()
    created = updated = failed = 0

    for item in items:
        url = item.get("url")
        existing = index.get(url)
        try:
            if existing:
                r = requests.patch(
                    f"{API}/pages/{existing['page_id']}", headers=_headers(),
                    json={"properties": _properties(item, creating=False)}, timeout=30)
                if r.status_code < 300:
                    updated += 1
                else:
                    failed += 1
                    print(f"[notion] update failed {r.status_code}: {r.text[:200]}")
            else:
                r = requests.post(
                    f"{API}/pages", headers=_headers(),
                    json={"parent": {"database_id": db_id},
                          "properties": _properties(item, creating=True)}, timeout=30)
                if r.status_code < 300:
                    created += 1
                else:
                    failed += 1
                    print(f"[notion] create failed {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            failed += 1
            print(f"[notion] error on {url}: {exc}")
        _throttle()

    print(f"[notion] created {created}, updated {updated}, failed {failed}")


def prune(days):
    """Archive ALL rows whose Fetched date is older than `days` (no exceptions —
    Saved rows are deleted too; save anything you want to keep elsewhere).
    Archived pages go to Notion's trash (auto-deleted after 30 days). Run on
    demand (see fetcher/prune.py), NOT during a normal fetch. The database
    itself / its views are preserved."""
    db_id = _config()[1]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    payload = {
        "page_size": 100,
        "filter": {"property": "Fetched", "date": {"before": cutoff}},
    }
    archived = 0
    while True:
        r = requests.post(f"{API}/databases/{db_id}/query", headers=_headers(),
                          json=payload, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"prune query {r.status_code}: {r.text[:200]}")
        data = r.json()
        for page in data.get("results", []):
            pr = requests.patch(f"{API}/pages/{page['id']}", headers=_headers(),
                               json={"archived": True}, timeout=30)
            if pr.status_code < 300:
                archived += 1
            _throttle()
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    print(f"[notion] pruned {archived} rows older than {days}d")
