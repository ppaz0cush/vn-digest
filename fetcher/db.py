"""Supabase upsert via the PostgREST REST API using the service_role key.

We use plain REST (no extra SDK) so the only dependency is `requests`. The
service_role key bypasses RLS, which is required to write `items`.
"""
import os
import json

from .http import post, USER_AGENT
import requests


# Columns that exist in the Supabase `items` table (migrations 0001 + 0002).
_COLUMNS = {
    "url", "source", "title", "source_detail", "published_at", "score",
    "score_type", "rank_label", "rank_position", "metadata",
    "prev_score", "score_delta", "last_score_at", "prev_score_at",
}


def _config():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment."
        )
    return url.rstrip("/"), key


def fetch_prev_scores():
    """Return {url: {"score": int|None, "last_score_at": str|None}} for every
    item that currently has a score. Used to compute the per-run delta. Returns
    {} (and logs) if the DB is unreachable, so a fetch can still proceed."""
    try:
        url, key = _config()
    except SystemExit:
        return {}
    endpoint = f"{url}/rest/v1/items"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    params = {"select": "url,score,last_score_at", "score": "not.is.null", "limit": "50000"}
    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        return {row["url"]: {"score": row.get("score"),
                             "last_score_at": row.get("last_score_at")}
                for row in resp.json()}
    except Exception as exc:
        print(f"[db] could not read previous scores ({exc}); deltas start fresh")
        return {}


def upsert_items(items):
    """Upsert a list of normalized item dicts into the `items` table.

    On conflict (url) we refresh title/score/etc. but PRESERVE the original
    fetched_at by simply not sending it (the column keeps its stored value on
    update; default now() applies only on first insert).
    """
    if not items:
        print("[db] nothing to upsert")
        return

    # Only send columns that exist in the Supabase `items` table; drop any
    # sink-specific extras (e.g. Notion's `subsource`).
    items = [{k: v for k, v in it.items() if k in _COLUMNS} for it in items]

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
