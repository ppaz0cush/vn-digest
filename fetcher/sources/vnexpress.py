"""vnexpress — weekly top N by comments (the Khoa học công nghệ section).

Every run records the articles in the RSS feed (it covers ~4-5 days). The feed
has no comment counts, so at publish each candidate (articles published since
the last weekly list) gets its count from vnexpress's public comment API
(data.totalitem), and the top N go to Notion.
"""
import re

import feedparser

from ..http import get
from ..util import parse_date, struct_time_to_utc, to_iso
from ..weekly import comment_row, published_between

COMMENT_API = (
    "https://usi-saas.vnexpress.net/index/get"
    "?objectid={id}&objecttype=1&siteid=1000000&offset=0&limit=1"
)
ID_RE = re.compile(r"(\d+)\.html")


def _article_id(url):
    m = ID_RE.search(url or "")
    return m.group(1) if m else None


def _comment_count(article_id):
    try:
        resp = get(COMMENT_API.format(id=article_id), timeout=20)
        resp.raise_for_status()
        return int(resp.json().get("data", {}).get("totalitem", 0))
    except Exception as exc:  # one bad article must not abort the source
        print(f"[vnexpress] comment count failed for {article_id}: {exc}")
        return None


def collect(cfg, src, now, week_start):
    resp = get(cfg["url"], timeout=25)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items, n = src["items"], 0
    for e in feed.entries:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = struct_time_to_utc(e.get("published_parsed")) or parse_date(e.get("published"))
        items.setdefault(link, {}).update({"title": title, "published_at": to_iso(published),
                                           "last_seen_at": to_iso(now)})
        n += 1
    if not n:
        raise RuntimeError("the feed returned no articles")
    return f"{n} articles in the feed, {len(items)} tracked"


def publish(cfg, src, now, week_start):
    cands = published_between(src["items"], week_start, now)
    for url, it in cands:
        aid = _article_id(url)
        count = _comment_count(aid) if aid else None
        if count is not None:
            it["comments"] = count
    cands.sort(key=lambda c: (c[1].get("comments") or 0, c[1].get("published_at") or ""),
               reverse=True)
    return [comment_row("vnexpress", url, it, i, now)
            for i, (url, it) in enumerate(cands[: cfg.get("top", 2)], start=1)]


def after_publish(src, now, week_start):
    """Nothing to reset: candidates are picked by publish date."""
