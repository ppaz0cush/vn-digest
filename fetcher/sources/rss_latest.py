"""rss_latest — plain chronological RSS feeds (anonyviet, engineerpro).

Parse the feed, capture title/url/published_at, no engagement score.
main.py applies the window/sort/cap. label is always 'Latest'.
"""
import feedparser

from ..http import get
from ..util import parse_date, struct_time_to_utc


def fetch(cfg):
    url = cfg["url"]
    # Fetch bytes ourselves so we use our User-Agent, then hand to feedparser.
    resp = get(url, timeout=25)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    items = []
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = struct_time_to_utc(e.get("published_parsed")) \
            or struct_time_to_utc(e.get("updated_parsed")) \
            or parse_date(e.get("published") or e.get("updated"))
        items.append({
            "url": link,
            "title": title,
            "source_detail": feed.feed.get("title") or cfg["name"],
            "published_at": published,
            "score": None,
            "score_type": None,
        })
    return items
