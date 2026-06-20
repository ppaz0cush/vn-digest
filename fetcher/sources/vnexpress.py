"""vnexpress — RSS for items + a public comment-count API for the score.

RSS has no comment counts, so:
  1. parse the RSS feed,
  2. filter to window_hours FIRST (to limit API calls),
  3. for each remaining article extract the numeric ID (digits before .html)
     and call the comment-count API, reading data.totalitem.
main.py then sorts by score desc, tiebreak pubDate desc, caps at max_items.
"""
import re
import feedparser

from ..http import get
from ..util import struct_time_to_utc, parse_date
from ..rank import filter_window

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
        data = resp.json()
        return int(data.get("data", {}).get("totalitem", 0))
    except Exception as exc:  # one bad article must not abort the source
        print(f"[vnexpress] comment count failed for {article_id}: {exc}")
        return None


def fetch(cfg):
    resp = get(cfg["url"], timeout=25)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    raw = []
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        if not link or not title:
            continue
        published = struct_time_to_utc(e.get("published_parsed")) \
            or parse_date(e.get("published"))
        raw.append({
            "url": link,
            "title": title,
            "source_detail": "VnExpress Số hóa",
            "published_at": published,
            "score": None,
            "score_type": None,
        })

    # Filter to window FIRST to limit comment-API calls.
    in_window = filter_window(raw, cfg.get("window_hours", 48))

    for it in in_window:
        aid = _article_id(it["url"])
        if not aid:
            continue
        count = _comment_count(aid)
        if count is not None:
            it["score"] = count
            it["score_type"] = "comments"
    return in_window
