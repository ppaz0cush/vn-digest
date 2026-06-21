"""Create the VN Tech Digest database in Notion with the correct TYPED schema.

Run ONCE after you've created the integration and a parent page:

    NOTION_TOKEN=ntn_xxx \
    NOTION_PARENT_PAGE_ID=<page id the integration can access> \
    python setup/notion_init.py

It prints the new database id — set that as NOTION_DB_ID for the fetcher.
The parent page id is the 32-char id in the page URL (with or without dashes).
"""
import os
import requests

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

token = os.environ["NOTION_TOKEN"]
parent = os.environ["NOTION_PARENT_PAGE_ID"].replace("-", "")

headers = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

schema = {
    "parent": {"type": "page_id", "page_id": parent},
    "title": [{"type": "text", "text": {"content": "VN Tech Digest"}}],
    "properties": {
        # The Title property is required and must be of type 'title'.
        "Title": {"title": {}},
        "URL": {"url": {}},
        # multi_select so a row can carry both the source and its sub-forum,
        # e.g. ["voz", "diem bao"] -> filter by either.
        "Source": {"multi_select": {}},
        "Label": {"select": {}},
        "Status": {"select": {"options": [
            {"name": "New", "color": "yellow"},
            {"name": "Read", "color": "gray"},
            {"name": "Saved", "color": "green"},
            {"name": "Skipped", "color": "red"},
        ]}},
        "Score": {"number": {}},
        "Δ today": {"number": {}},
        "Prev score": {"number": {}},
        "Rank": {"number": {}},
        "Published": {"date": {}},
        "Fetched": {"date": {}},
    },
}

r = requests.post(f"{API}/databases", headers=headers, json=schema, timeout=30)
if r.status_code >= 300:
    raise SystemExit(f"Failed to create database {r.status_code}: {r.text}")

db = r.json()
print("Created database:", db["url"])
print("\nNOTION_DB_ID =", db["id"])
print("\nNext: set NOTION_TOKEN + NOTION_DB_ID, then run:")
print("  TARGET=notion python -m fetcher.main        # Notion only")
print("  TARGET=both   python -m fetcher.main        # Notion + Supabase (keep backup hot)")
