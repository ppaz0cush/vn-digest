"""tinhte — weekly top N by comments.

Every run reads https://tinhte.vn/rss (it covers roughly the last day of
articles) and records each article with its comment count (<slash:comments>).
At publish the candidates are the articles published since the last weekly
list. An article only stays in the feed for about a day, so the top
`refresh_top` candidates get their current count re-read from the article page
(the "commentCount" in its JSON-LD) before the top N are picked.

The feed's date is when an article reached the front page (hours to days after
it was written), and the feed sometimes re-features an article that's months
old, with a fresh date and all its old comments. So at publish the article
page's own "datePublished" is checked too: one first published more than
OLD_DAYS before the week started is skipped.
"""
import json
import re
from datetime import timedelta

from ..http import get
from ..util import parse_date, to_iso
from ..weekly import comment_row, published_between
from ._rss import entry_published, fetch_feed

LD_JSON_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)
OLD_DAYS = 7


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


def page_info(html):
    """(commentCount, datePublished) from the article's JSON-LD (a WebPage object)."""
    for block in LD_JSON_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        objs = data if isinstance(data, list) else data.get("@graph", [data])
        for obj in objs:
            if isinstance(obj, dict) and isinstance(obj.get("commentCount"), int):
                return obj["commentCount"], parse_date(obj.get("datePublished"))
    return None, None


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
    oldest = week_start - timedelta(days=OLD_DAYS)
    kept, refreshed = [], 0
    for url, it in cands:
        if refreshed < cfg.get("refresh_top", 10):
            try:
                resp = get(url, timeout=30, browser=True)
                resp.raise_for_status()
                count, written = page_info(resp.text)
                if written is not None and written < oldest:
                    print(f"[tinhte] skipped (written {written:%Y-%m-%d}, re-featured by the feed): {url}")
                    continue
                if count is not None:
                    it["comments"] = max(count, it.get("comments") or 0)
            except Exception as exc:  # keep the count from the feed
                print(f"[tinhte] couldn't refresh {url}: {exc}")
            refreshed += 1
        kept.append((url, it))
    kept.sort(key=lambda c: (c[1].get("comments") or 0, c[1].get("published_at") or ""),
              reverse=True)
    return [comment_row("tinhte", url, it, i, now)
            for i, (url, it) in enumerate(kept[: cfg.get("top", 2)], start=1)]


def after_publish(src, now, week_start):
    """Nothing to reset: candidates are picked by publish date."""
