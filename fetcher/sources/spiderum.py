"""spiderum — category listing (Next.js app).

Strategy: fetch the configured category_url, then extract posts from the
embedded __NEXT_DATA__ JSON (preferred, has dates + engagement), falling back
to scraping rendered <a> links that match the post_url_pattern. Build each post
URL from post_url_pattern + slug. label = 'Latest'.
"""
import json
import re
from bs4 import BeautifulSoup

from ..http import get
from ..util import parse_date


def _walk_posts(obj):
    """Yield dicts that look like spiderum post objects (have a slug + title)."""
    if isinstance(obj, dict):
        slug = obj.get("slug")
        title = obj.get("title") or obj.get("og_title")
        if isinstance(slug, str) and slug and title:
            yield obj
        for v in obj.values():
            yield from _walk_posts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_posts(v)


def _from_next_data(html, cfg):
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return []
    data = json.loads(tag.string)

    seen = set()
    items = []
    for post in _walk_posts(data):
        slug = post["slug"]
        if slug in seen:
            continue
        seen.add(slug)
        title = (post.get("title") or post.get("og_title") or "").strip()
        url = cfg["post_url_pattern"].format(slug=slug)
        published = parse_date(
            post.get("createdAt") or post.get("created_at")
            or post.get("publishedAt") or post.get("published_at")
        )
        # engagement, if present
        score = None
        score_type = None
        for key, st in (("views_count", "views"), ("point", "points"),
                        ("comment_count", "comments")):
            val = post.get(key)
            if isinstance(val, (int, float)):
                score, score_type = int(val), st
                break
        items.append({
            "url": url,
            "title": title,
            "source_detail": "Spiderum · Quan điểm - Tranh luận",
            "published_at": published,
            "score": score,
            "score_type": score_type,
        })
    return items


_SLUG_RE = re.compile(r"/bai-dang/([A-Za-z0-9-]+)")
_NUM_RE = re.compile(r"^([\d.,]+)\s*([km])?$", re.IGNORECASE)


def _parse_count(text):
    """'2.2k' -> 2200, '1.3m' -> 1300000, '345' -> 345, else None."""
    m = _NUM_RE.match((text or "").strip())
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"k": 1_000, "m": 1_000_000}.get((m.group(2) or "").lower(), 1)
    return int(num * mult)


def _from_links(html, cfg):
    """Each post renders as several <a> with the same /bai-dang/{slug} href:
    one image link (no text), the title link (text), a views link ('2.2k'),
    and a '#comments' link. Group by slug, preserving DOM order (newest first),
    and pick the title + view count.
    """
    soup = BeautifulSoup(html, "lxml")
    posts = {}        # slug -> dict
    order = []        # slug order as first seen
    for a in soup.select("a[href*='/bai-dang/']"):
        href = a.get("href", "")
        m = _SLUG_RE.search(href)
        if not m:
            continue
        slug = m.group(1)
        if slug not in posts:
            posts[slug] = {"title": None, "views": None}
            order.append(slug)
        text = a.get_text(strip=True)
        if not text:
            continue
        if "#comments" in href:
            continue
        count = _parse_count(text)
        if count is not None:
            # numeric-only anchor => the views badge
            posts[slug]["views"] = posts[slug]["views"] or count
        elif len(text) > (len(posts[slug]["title"] or "")):
            # longest textual anchor is the title
            posts[slug]["title"] = text

    items = []
    for slug in order:
        p = posts[slug]
        if not p["title"]:
            continue
        items.append({
            "url": cfg["post_url_pattern"].format(slug=slug),
            "title": p["title"],
            "source_detail": "Spiderum · Quan điểm - Tranh luận",
            "published_at": None,  # not exposed in the listing DOM
            "score": p["views"],
            "score_type": "views" if p["views"] is not None else None,
        })
    return items


def fetch(cfg):
    resp = get(cfg["category_url"], timeout=25, browser=True)
    resp.raise_for_status()
    html = resp.text
    items = _from_next_data(html, cfg)
    if not items:
        print("[spiderum] __NEXT_DATA__ yielded nothing; falling back to link scrape")
        items = _from_links(html, cfg)
    return items
