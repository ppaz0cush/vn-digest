"""engineerpro — every post of EngineerPro VN's Substack (mode: all).

Substack's archive API lists the whole history (the RSS feed only has the latest
20). Each page is {"posts": [...], "nextCursor": "..."} with at most 25 posts
(a bigger `limit`, or the old `offset` paging, is a 400 error since Nov 2026);
it's paged with `cursor=<nextCursor>` until nextCursor is null. Substack
answers GitHub Actions runners with 403 (a known Substack block since Jan 2024;
home networks are fine), so each archive page is fetched by the first method
that works, starting with the one that worked for the previous page:
  1. direct request (works locally);
  2. headless Chromium (gets through if the block is a Cloudflare JS challenge);
  3. Jina Reader (https://r.jina.ai/<url>), a free public service that fetches
     the public URL from its own servers and returns the JSON as text.
`last_via` records which one worked (shown in the run summary).
"""
import json
from urllib.parse import urlencode

from ..http import BROWSER_UA, get
from ..util import parse_date
from ._rss import latest

PAGE_SIZE = 25     # the API's maximum
MAX_POSTS = 5000   # safety stop for the paging loop
JINA = "https://r.jina.ai/"

last_via = None


def _json_page(text):
    """(posts, next cursor) from an archive response body. Jina/browsers may add
    text around the JSON, and Jina relays Substack's errors ({"errors": [...]})
    with a 200, so anything without a "posts" list is rejected."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in the response: {text[:120]!r}")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict) or not isinstance(data.get("posts"), list):
        raise ValueError(f"unexpected archive response: {text[start:start + 160]!r}")
    return data["posts"], data.get("nextCursor")


def _direct(url):
    resp = get(url, timeout=25)
    resp.raise_for_status()
    return _json_page(resp.text)


def _browser(url):
    from playwright.sync_api import sync_playwright  # lazy: heavy dependency
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context(user_agent=BROWSER_UA).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            # A Cloudflare challenge page reloads itself once solved; wait for the JSON.
            page.wait_for_function(
                "() => document.body && document.body.innerText.trim().startsWith('{')",
                timeout=20000)
            return _json_page(page.inner_text("body"))
        finally:
            browser.close()


def _jina(url):
    resp = get(JINA + url, timeout=60, headers={"X-Return-Format": "text"})
    resp.raise_for_status()
    return _json_page(resp.text)


METHODS = [("direct", _direct), ("browser", _browser), ("r.jina.ai", _jina)]


def _archive_page(url):
    global last_via
    errors = []
    # Start with the method that worked for the previous page (stable sort).
    for name, method in sorted(METHODS, key=lambda m: m[0] != last_via):
        try:
            page = method(url)
            last_via = name
            return page
        except Exception as exc:
            errors.append(f"{name}: {str(exc)[:120]}")
    raise RuntimeError("archive unreachable (" + "; ".join(errors) + ")")


def _archive(cfg):
    posts, seen, cursor = [], set(), None
    while len(seen) < MAX_POSTS:
        query = {"sort": "new", "limit": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
        page, cursor = _archive_page(f"{cfg['archive_url']}?{urlencode(query)}")
        fresh = [p for p in page if p.get("canonical_url") and p["canonical_url"] not in seen]
        for p in fresh:
            url, title = p["canonical_url"], (p.get("title") or "").strip()
            seen.add(url)
            if title:
                posts.append({"url": url, "title": title,
                              "published_at": parse_date(p.get("post_date"))})
        # The last page has no cursor; a page with nothing new means the cursor is stuck.
        if not cursor or not fresh:
            break
    if not posts:
        raise RuntimeError("the archive listed no posts")
    return posts


def fetch(cfg):
    global last_via
    last_via = archive_error = None
    if cfg.get("archive_url"):
        try:
            return _archive(cfg)
        except Exception as exc:
            archive_error = exc
            print(f"[engineerpro] {exc}; trying the RSS feed")
    last_via = "rss"
    try:
        return latest(cfg)
    except Exception as exc:
        if archive_error is None:
            raise
        # Keep the archive's error too: it's what goes into the tracking file.
        raise RuntimeError(f"{archive_error}; RSS feed: {exc}") from exc
