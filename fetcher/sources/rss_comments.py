"""rss_comments — Tinhte. Comment count lives in the RSS as <slash:comments>.

Rank by comment count desc, tiebreak by pubDate desc (handled by main.py).
score_type = 'comments'.
"""
import feedparser

from ..http import get
from ..util import struct_time_to_utc, parse_date

SLASH_NS = "http://purl.org/rss/1.0/modules/slash/"


def _comment_count(entry):
    # feedparser exposes <slash:comments> as entry['slash_comments'] when the
    # namespace is declared. Fall back to a couple of common keys.
    for key in ("slash_comments", "comments", "slash:comments"):
        val = entry.get(key)
        if val is None:
            continue
        try:
            return int(str(val).strip())
        except (ValueError, TypeError):
            continue
    return None


def fetch(cfg):
    resp = get(cfg["url"], timeout=25)
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
        count = _comment_count(e)
        items.append({
            "url": link,
            "title": title,
            "source_detail": "Tinhte",
            "published_at": published,
            "score": count,
            "score_type": "comments" if count is not None else None,
        })
    return items
