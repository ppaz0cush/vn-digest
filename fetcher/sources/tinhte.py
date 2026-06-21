"""tinhte — RSS feed (https://tinhte.vn/rss) whose items carry a comment count.

The count is in each item as <slash:comments> (namespace
http://purl.org/rss/1.0/modules/slash/), so no extra request is needed.
Ranked by comments (trending = comments gained since last run).
"""
from ._rss import fetch_feed, entry_published


def _comment_count(entry):
    # feedparser exposes <slash:comments> as entry['slash_comments'] when the
    # namespace is declared; fall back to a couple of common keys.
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
    feed = fetch_feed(cfg["url"])
    items = []
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        count = _comment_count(e)
        items.append({
            "url": link,
            "title": title,
            "source_detail": "Tinhte",
            "published_at": entry_published(e),
            "score": count,
            "score_type": "comments" if count is not None else None,
        })
    return items
