"""tinhte — weekly top N by comments.

Every run reads https://tinhte.vn/rss (it covers roughly the last day of
articles) and records each article with its comment count (<slash:comments>).
At publish the candidates are the articles published since the last weekly
list. An article only stays in the feed for about a day, so the top
`refresh_top` candidates get their current count re-read from the article page
(the "commentCount" in its JSON-LD) before the top N are picked.
"""
import json
import re

from ..http import get
from ..util import to_iso
from ..weekly import comment_row, published_between
from ._rss import entry_published, fetch_feed

LD_JSON_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)


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


def page_comment_count(html):
    """The article's comment count from its JSON-LD (a WebPage object)."""
    for block in LD_JSON_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        objs = data if isinstance(data, list) else data.get("@graph", [data])
        for obj in objs:
            if isinstance(obj, dict) and isinstance(obj.get("commentCount"), int):
                return obj["commentCount"]
    return None


def collect(cfg, src, now, week_start):
    feed = fetch_feed(cfg["url"])
    items, n = src["items"], 0
    for e in feed.entries:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        it = items.setdefault(link, {})
        it.update({"title": title, "published_at": to_iso(entry_published(e)),
                   "last_seen_at": to_iso(now)})
        count = _comment_count(e)
        if count is not None:
            it["comments"] = max(count, it.get("comments") or 0)
        n += 1
    if not n:
        raise RuntimeError("the feed returned no articles")
    return f"{n} articles in the feed, {len(items)} tracked"


def publish(cfg, src, now, week_start):
    cands = published_between(src["items"], week_start, now)
    cands.sort(key=lambda c: c[1].get("comments") or 0, reverse=True)
    for url, it in cands[: cfg.get("refresh_top", 10)]:
        try:
            resp = get(url, timeout=30, browser=True)
            resp.raise_for_status()
            count = page_comment_count(resp.text)
            if count is not None:
                it["comments"] = max(count, it.get("comments") or 0)
        except Exception as exc:  # keep the count from the feed
            print(f"[tinhte] couldn't refresh {url}: {exc}")
    cands.sort(key=lambda c: (c[1].get("comments") or 0, c[1].get("published_at") or ""),
               reverse=True)
    return [comment_row("tinhte", url, it, i, now)
            for i, (url, it) in enumerate(cands[: cfg.get("top", 2)], start=1)]


def after_publish(src, now, week_start):
    """Nothing to reset: candidates are picked by publish date."""
