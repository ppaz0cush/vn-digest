import json
import types
from datetime import datetime, timedelta, timezone

from fetcher.sources import tinhte
from fetcher.util import to_iso

WEEK = datetime(2026, 10, 12, 20, tzinfo=timezone.utc)   # week start (last publish)
NOW = WEEK + timedelta(days=7)
FEED_DATE = to_iso(WEEK + timedelta(days=3))             # when the feed showed the article


def page(comments, written):
    ld = {"@context": "https://schema.org", "@type": "WebPage", "commentCount": comments,
          "datePublished": written.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    return f'<html><script type="application/ld+json">{json.dumps(ld)}</script></html>'


def serve(monkeypatch, pages):
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        if isinstance(pages[url], Exception):
            raise pages[url]
        return types.SimpleNamespace(text=pages[url], raise_for_status=lambda: None)

    monkeypatch.setattr(tinhte, "get", fake_get)
    return requested


def test_page_info_reads_the_webpage_json_ld():
    written = datetime(2025, 4, 8, 16, 25, 34, tzinfo=timezone.utc)
    html = '<script type="application/ld+json">{"@type": "Organization"}</script>' + page(148, written)
    assert tinhte.page_info(html) == (148, written)
    assert tinhte.page_info("<html></html>") == (None, None)


def test_publish_skips_old_articles_the_feed_re_featured(monkeypatch):
    items = {url: {"title": url[-3:], "published_at": FEED_DATE, "comments": n}
             for url, n in (("https://t/old", 148), ("https://t/aaa", 30),
                            ("https://t/bbb", 20), ("https://t/ccc", 10))}
    requested = serve(monkeypatch, {
        "https://t/old": page(150, datetime(2025, 4, 8, tzinfo=timezone.utc)),   # 18 months old
        "https://t/aaa": page(31, WEEK + timedelta(days=2)),
        "https://t/bbb": page(45, WEEK - timedelta(days=1)),   # written just before the week: kept
    })
    rows = tinhte.publish({"top": 2, "refresh_top": 2}, {"items": items}, NOW, WEEK)
    assert [(r["title"], r["score"], r["rank"]) for r in rows] == [("bbb", 45, 1), ("aaa", 31, 2)]
    # the skipped article doesn't use up a refresh: ccc (outside refresh_top) isn't fetched
    assert requested == ["https://t/old", "https://t/aaa", "https://t/bbb"]


def test_publish_keeps_the_feed_count_when_a_page_fails(monkeypatch):
    items = {"https://t/aaa": {"title": "aaa", "published_at": FEED_DATE, "comments": 7}}
    serve(monkeypatch, {"https://t/aaa": RuntimeError("timeout")})
    rows = tinhte.publish({"top": 2}, {"items": items}, NOW, WEEK)
    assert [(r["title"], r["score"]) for r in rows] == [("aaa", 7)]
