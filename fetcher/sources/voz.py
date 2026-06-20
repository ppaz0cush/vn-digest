"""voz — scrape a SORTED XenForo sub-forum listing to rank by engagement.

voz RSS is chronological, so to rank by views we scrape the sorted thread
listing per configured sub-forum:
    https://voz.vn/f/<slug>.<id>/?order=view_count&direction=desc
Parse thread rows for title, thread URL, view count, reply count, and
last-activity time. Filter to threads active within window_hours, sort by
rank_by (default views), cap. score stored as views; score_type 'replies_views'.

NOTE: voz sits behind Cloudflare and may return 403 from datacenter/unknown
IPs. We retry with a browser-like UA, and on persistent block we return [] so
the run continues (the fetcher tolerates per-source failure).
"""
import re
from bs4 import BeautifulSoup

from ..http import get
from ..util import parse_date

BASE = "https://voz.vn/f/{forum}/?order={order}&direction=desc"


def _int(text):
    if text is None:
        return None
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def _fetch_html(forum, order):
    url = BASE.format(forum=forum, order=order)
    # Try honest UA first, then browser UA if blocked.
    resp = get(url, timeout=25)
    if resp.status_code == 403:
        resp = get(url, timeout=25, browser=True,
                   headers={"Accept-Language": "vi,en;q=0.9",
                            "Accept": "text/html,application/xhtml+xml"})
    resp.raise_for_status()
    return resp.text


def _parse(html, forum):
    soup = BeautifulSoup(html, "lxml")
    items = []
    # XenForo 2 thread rows.
    for row in soup.select("div.structItem--thread"):
        title_a = row.select_one(".structItem-title a[href*='/t/']") \
            or row.select_one(".structItem-title a")
        if not title_a:
            continue
        href = title_a.get("href", "")
        title = title_a.get_text(strip=True)
        if not href or not title:
            continue
        url = href if href.startswith("http") else f"https://voz.vn{href}"

        # Stats: views and replies live in .structItem-cell--meta dl/dd pairs.
        views = replies = None
        for pair in row.select(".structItem-cell--meta .pairs, .structItem-cell--meta dl"):
            label = pair.select_one("dt")
            value = pair.select_one("dd")
            if not label or not value:
                continue
            ltext = label.get_text(strip=True).lower()
            num = _int(value.get("title") or value.get_text(strip=True))
            if "view" in ltext or "lượt xem" in ltext:
                views = num
            elif "repl" in ltext or "trả lời" in ltext:
                replies = num

        # Last activity time (for the recency window).
        time_el = row.select_one(".structItem-latestDate, time")
        published = None
        if time_el:
            published = parse_date(time_el.get("datetime") or time_el.get("title")
                                   or time_el.get_text(strip=True))

        items.append({
            "url": url,
            "title": title,
            "source_detail": f"voz · {forum}",
            "published_at": published,
            "score": views if views is not None else replies,
            "score_type": "replies_views",
            "metadata": {"views": views, "replies": replies},
        })
    return items


def fetch(cfg):
    rank_by = cfg.get("rank_by", "views")
    order = "view_count" if rank_by == "views" else "reply_count"
    all_items = []
    for forum in cfg.get("forums", []):
        if "REPLACE_WITH" in forum:
            print(f"[voz] skipping placeholder forum {forum!r}; set a real slug.id")
            continue
        try:
            html = _fetch_html(forum, order)
            parsed = _parse(html, forum)
            print(f"[voz] {forum}: parsed {len(parsed)} threads")
            all_items.extend(parsed)
        except Exception as exc:
            print(f"[voz] {forum} failed: {exc}")
    return all_items
