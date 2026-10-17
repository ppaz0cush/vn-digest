"""engineerpro — every post of EngineerPro VN's Substack (mode: all).

The RSS feed only lists the latest 20 posts, so the full history comes from
Substack's public archive API (paged, newest first). If that API ever fails,
the RSS feed (`url`) is used instead; its links are the same canonical URLs,
so nothing gets duplicated.
"""
from ..http import get
from ..util import parse_date
from ._rss import latest

PAGE_SIZE = 50
MAX_POSTS = 5000   # safety stop for the paging loop


def _archive(cfg):
    posts, offset = [], 0
    while offset < MAX_POSTS:
        resp = get(cfg["archive_url"], timeout=25,
                   params={"sort": "new", "search": "", "offset": offset, "limit": PAGE_SIZE})
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list):
            raise ValueError("unexpected archive response")
        for p in page:
            url, title = p.get("canonical_url"), (p.get("title") or "").strip()
            if url and title:
                posts.append({"url": url, "title": title,
                              "published_at": parse_date(p.get("post_date"))})
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
    return posts


def fetch(cfg):
    if cfg.get("archive_url"):
        try:
            return _archive(cfg)
        except Exception as exc:
            print(f"[engineerpro] archive API failed ({exc}); using the RSS feed")
    return latest(cfg)
