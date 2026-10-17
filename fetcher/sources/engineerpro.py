"""engineerpro — every post of EngineerPro VN's Substack (mode: all).

Substack's archive API lists the whole history (the RSS feed only has the latest
20); it's paged until an empty page, as the first page stops at 23 posts
whatever the limit. Substack answers GitHub Actions runners with 403 (a known
Substack block since Jan 2024; home networks are fine), so each archive page is
fetched by the first method that works, starting with the one that worked for
the previous page:
  1. direct request (works locally);
  2. headless Chromium (gets through if the block is a Cloudflare JS challenge);
  3. Jina Reader (https://r.jina.ai/<url>), a free public service that fetches
     the public URL from its own servers and returns the JSON as text.
`last_via` records which one worked (shown in the run summary).
"""
import json

from ..http import BROWSER_UA, get
from ..util import parse_date
from ._rss import latest

PAGE_SIZE = 50
MAX_POSTS = 5000   # safety stop for the paging loop
JINA = "https://r.jina.ai/"

last_via = None


def _json_list(text):
    """The JSON array in a response body (Jina/browsers may add text around it)."""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError(f"no JSON list in the response: {text[:120]!r}")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("unexpected archive response")
    return data


def _direct(url):
    resp = get(url, timeout=25)
    resp.raise_for_status()
    return _json_list(resp.text)


def _browser(url):
    from playwright.sync_api import sync_playwright  # lazy: heavy dependency
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context(user_agent=BROWSER_UA).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            # A Cloudflare challenge page reloads itself once solved; wait for the JSON.
            page.wait_for_function(
                "() => document.body && document.body.innerText.trim().startsWith('[')",
                timeout=20000)
            return _json_list(page.inner_text("body"))
        finally:
            browser.close()


def _jina(url):
    resp = get(JINA + url, timeout=60, headers={"X-Return-Format": "text"})
    resp.raise_for_status()
    return _json_list(resp.text)


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
    posts, seen, offset = [], set(), 0
    while offset < MAX_POSTS:
        page = _archive_page(f"{cfg['archive_url']}?sort=new&search=&offset={offset}&limit={PAGE_SIZE}")
        # A short page isn't the end: Substack caps the first page (23 posts,
        # whatever the limit). Only an empty page, or one with nothing new, is.
        fresh = [p for p in page if p.get("canonical_url") and p["canonical_url"] not in seen]
        if not fresh:
            break
        for p in fresh:
            url, title = p["canonical_url"], (p.get("title") or "").strip()
            seen.add(url)
            if title:
                posts.append({"url": url, "title": title,
                              "published_at": parse_date(p.get("post_date"))})
        offset += len(page)
    return posts


def fetch(cfg):
    global last_via
    last_via = None
    if cfg.get("archive_url"):
        try:
            return _archive(cfg)
        except Exception as exc:
            print(f"[engineerpro] {exc}; trying the RSS feed")
    last_via = "rss"
    return latest(cfg)
