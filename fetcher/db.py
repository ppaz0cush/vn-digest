"""Supabase upsert via the PostgREST REST API using the service_role key.

We use plain REST (no extra SDK) so the only dependency is `requests`. The
service_role key bypasses RLS, which is required to write `items`.
"""
import os
import json

from .http import post, USER_AGENT
import requests


def _config():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment."
        )
    return url.rstrip("/"), key


def upsert_items(items):
    """Upsert a list of normalized item dicts into the `items` table.

    On conflict (url) we refresh title/score/etc. but PRESERVE the original
    fetched_at by simply not sending it (the column keeps its stored value on
    update; default now() applies only on first insert).
    """
    if not items:
        print("[db] nothing to upsert")
        return

    url, key = _config()
    endpoint = f"{url}/rest/v1/items"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        # merge-duplicates => UPSERT on the primary key (url)
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    # Send in one batch; PostgREST handles arrays.
    resp = requests.post(
        endpoint,
        headers=headers,
        data=json.dumps(items, default=str),
        timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"[db] upsert failed {resp.status_code}: {resp.text[:500]}"
        )
    print(f"[db] upserted {len(items)} items")
