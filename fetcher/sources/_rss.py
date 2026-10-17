"""Shared RSS helpers (not a source itself — note the leading underscore).

Used by the plain-feed sources (anonyviet, engineerpro) and as the feed
fetch/parse primitive for tinhte. Keeps RSS plumbing in one place so each
source file stays small and focused.
"""
import feedparser

from ..http import get
from ..util import parse_date, struct_time_to_utc


def fetch_feed(url):
    """GET the feed with our User-Agent, then hand the bytes to feedparser."""
    resp = get(url, timeout=25)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def entry_published(e):
    """Best-effort published datetime (UTC) for a feed entry."""
    return (struct_time_to_utc(e.get("published_parsed"))
            or struct_time_to_utc(e.get("updated_parsed"))
            or parse_date(e.get("published") or e.get("updated")))


def latest(cfg):
    """Plain chronological feed -> items with no engagement score.
    main.py applies the source's look-back window."""
    feed = fetch_feed(cfg["url"])
    items = []
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        items.append({
            "url": link,
            "title": title,
            "source_detail": feed.feed.get("title") or cfg["name"],
            "published_at": entry_published(e),
            "score": None,
            "score_type": None,
        })
    return items
