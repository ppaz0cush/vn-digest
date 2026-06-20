"""dailydev — unofficial GraphQL popularity feed, with an RSS fallback.

Primary: POST to https://api.daily.dev/graphql (anonymousFeed, ranking POPULARITY).
Field is `numUpvotes` (not `upvotes`). The anonymous feed may include older
items, so window-filtering (in main.py) + sort-by-upvotes is essential.
Fallback: official RSS https://api.daily.dev/rss as a chronological 'Latest'.
"""
import feedparser

from ..http import post, get
from ..util import parse_date, struct_time_to_utc

GRAPHQL_URL = "https://api.daily.dev/graphql"
RSS_URL = "https://api.daily.dev/rss"

QUERY = """
query {
  anonymousFeed(first: 20, ranking: POPULARITY) {
    edges { node {
      title permalink numUpvotes numComments createdAt readTime source { name }
    } }
  }
}
"""


def _from_graphql(cfg):
    resp = post(
        GRAPHQL_URL,
        json={"query": QUERY},
        headers={"Content-Type": "application/json"},
        timeout=25,
    )
    resp.raise_for_status()
    payload = resp.json()
    edges = (payload.get("data") or {}).get("anonymousFeed", {}).get("edges", [])
    if not edges:
        raise RuntimeError("dailydev GraphQL returned no edges")

    items = []
    for edge in edges:
        node = edge.get("node") or {}
        link = node.get("permalink")
        title = (node.get("title") or "").strip()
        if not link or not title:
            continue
        upvotes = node.get("numUpvotes")
        src = (node.get("source") or {}).get("name")
        items.append({
            "url": link,
            "title": title,
            "source_detail": f"daily.dev · {src}" if src else "daily.dev",
            "published_at": parse_date(node.get("createdAt")),
            "score": int(upvotes) if isinstance(upvotes, (int, float)) else None,
            "score_type": "upvotes" if upvotes is not None else None,
        })
    return items


def _from_rss(cfg):
    resp = get(RSS_URL, timeout=25)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = struct_time_to_utc(e.get("published_parsed")) \
            or parse_date(e.get("published"))
        items.append({
            "url": link,
            "title": title,
            "source_detail": "daily.dev",
            "published_at": published,
            "score": None,
            "score_type": None,
        })
    return items


def fetch(cfg):
    try:
        return _from_graphql(cfg)
    except Exception as exc:
        print(f"[dailydev] GraphQL failed ({exc}); falling back to RSS")
        # When falling back we lose the score; treat as chronological 'Latest'.
        cfg["rank"] = "latest"
        cfg["label"] = "Latest"
        return _from_rss(cfg)
