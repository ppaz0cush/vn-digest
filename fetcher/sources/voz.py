"""voz — rank a sub-forum by views/replies.

voz fronts its SORTED HTML listing with a Cloudflare JS "managed challenge"
that a plain HTTP client cannot solve (curl/requests get the "Just a moment"
interstitial, never the threads). To get the ranked listing we drive a real
headless browser (Playwright/Chromium), which executes the challenge JS, then
parse the resulting HTML for view/reply counts. This is the only free way to
get "Top by views/comments" for voz.

Fallback chain per forum:
  1. browser-rendered sorted listing  -> ranked 'Top' (views or replies)
  2. per-forum RSS (not challenged)    -> chronological 'Latest'
  3. nothing                            -> skip (run continues)

Enable the browser path with `use_browser: true` in sources.yaml (default for
voz). Requires `playwright` + `python -m playwright install chromium`. If
Playwright is unavailable or the challenge isn't solved, it degrades to RSS.
"""
import re
import feedparser
from bs4 import BeautifulSoup

from ..http import get
from ..util import parse_date, struct_time_to_utc

# Default forum listing = most-recently-active threads first. We deliberately do
# NOT use ?order=view_count: that returns all-time top threads, which are mostly
# stale and get stripped by the recency window. Instead we take the recently
# active threads and rank THOSE by views/replies client-side (rank.py) — i.e.
# "most-viewed among threads active in the window", which is what 'Top' means here.
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _split_forum(forum):
    """A forum entry is '<slug>.<id>' (a normal /f/ forum) or '<type>/<slug>.<id>'
    for other node types, e.g. 's/review-san-pham.103' (voz's /s/ nodes)."""
    f = forum.strip().strip("/")
    if "/" in f:
        node_type, slug = f.split("/", 1)
    else:
        node_type, slug = "f", f
    return node_type, slug


def _listing_url(forum):
    t, s = _split_forum(forum)
    return f"https://voz.vn/{t}/{s}/"


def _rss_url(forum):
    t, s = _split_forum(forum)
    return f"https://voz.vn/{t}/{s}/index.rss"


def _forum_label(forum):
    """'diem-bao.33' -> 'diem bao'; 's/review-san-pham.103' -> 'review san pham'."""
    _, slug = _split_forum(forum)
    return re.sub(r"\.\d+$", "", slug).replace("-", " ")


def _unread(thread_url):
    """Rewrite a thread URL to its /unread form, which (when logged in) jumps to
    the reader's first unread post. e.g. /t/slug.123/ -> /t/slug.123/unread"""
    m = re.match(r"(https?://voz\.vn/t/[^/]+\.\d+)", thread_url or "")
    base = m.group(1) if m else (thread_url or "").rstrip("/")
    return f"{base}/unread" if base else thread_url


def _count(text):
    """Parse a XenForo engagement badge: '19K'->19000, '3M'->3000000,
    '1.2K'->1200, '821'->821, else None. (The dd has no title attr.)"""
    m = re.match(r"^\s*([\d.,]+)\s*([kmb])?\s*$", str(text or ""), re.IGNORECASE)
    if not m:
        return None
    num_s, suf = m.group(1), (m.group(2) or "").lower()
    if suf:  # abbreviated -> the number part may carry a decimal (',' or '.')
        try:
            num = float(num_s.replace(",", "."))
        except ValueError:
            return None
        return int(num * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suf])
    digits = re.sub(r"[^\d]", "", num_s)   # plain integer, drop thousands seps
    return int(digits) if digits else None


def _parse(html, forum, rank_by="views", skip_sticky=True):
    soup = BeautifulSoup(html, "lxml")
    items = []
    for row in soup.select("div.structItem--thread"):
        # Pinned/sticky threads (rules, megathreads) have huge all-time view
        # counts and would always top a view ranking — skip them so "Top by
        # views" reflects actual news. Set skip_sticky: false to keep them.
        if skip_sticky and row.select_one(".structItem-status--sticky"):
            continue

        title_a = row.select_one(".structItem-title a[href*='/t/']") \
            or row.select_one(".structItem-title a")
        if not title_a:
            continue
        href = title_a.get("href", "")
        title = title_a.get_text(strip=True)
        if not href or not title:
            continue
        url = href if href.startswith("http") else f"https://voz.vn{href}"

        views = replies = None
        for dl in row.select(".structItem-cell--meta dl"):
            dt, dd = dl.select_one("dt"), dl.select_one("dd")
            if not dt or not dd:
                continue
            label = dt.get_text(strip=True).lower()
            num = _count(dd.get("title") or dd.get_text(strip=True))
            if "view" in label or "lượt xem" in label:
                views = num
            elif "repl" in label or "trả lời" in label:
                replies = num

        # last-activity time = the dedicated .structItem-latestDate (NOT the
        # first <time>, which is the thread's start date).
        time_el = row.select_one(".structItem-latestDate")
        if not time_el:
            times = row.select("time")
            time_el = times[-1] if times else None
        published = None
        if time_el:
            published = parse_date(time_el.get("datetime") or time_el.get("title")
                                   or time_el.get_text(strip=True))

        # Score on the configured engagement metric (so rank.py sorts by it).
        if rank_by == "replies":
            score, stype = replies, "replies"
        else:
            score, stype = views, "views"
        items.append({
            "url": _unread(url),                 # deep-link to first unread post
            "title": title,
            "source_detail": f"voz · {forum}",
            "subsource": _forum_label(forum),    # e.g. "diem bao" (multi-select tag)
            "published_at": published,
            "score": score,
            "score_type": stype,
            "metadata": {"views": views, "replies": replies},
        })
    return items


def _fetch_html_browser(forum, attempts=2):
    """Render the Cloudflare-challenged listing with headless Chromium."""
    from playwright.sync_api import sync_playwright  # lazy: optional dependency

    url = _listing_url(forum)
    last_err = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for attempt in range(1, attempts + 1):
                ctx = browser.new_context(locale="vi-VN", user_agent=BROWSER_UA)
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    # Cloudflare auto-solves the managed challenge, then the
                    # thread rows appear. Wait for them.
                    page.wait_for_selector("div.structItem--thread", timeout=30000)
                    return page.content()
                except Exception as exc:
                    last_err = exc
                    if attempt < attempts:
                        page.wait_for_timeout(4000)  # let the challenge settle, retry
                finally:
                    ctx.close()
        finally:
            browser.close()
    raise RuntimeError(f"challenge not solved after {attempts} tries: {last_err}")


def _from_rss(forum):
    """Fallback: per-forum RSS is NOT challenged, but chronological (no counts)."""
    resp = get(_rss_url(forum), timeout=25, browser=True)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        items.append({
            "url": _unread(link),
            "title": title,
            "source_detail": f"voz · {feed.feed.get('title') or forum}",
            "subsource": _forum_label(forum),
            "published_at": struct_time_to_utc(e.get("published_parsed"))
                            or parse_date(e.get("published")),
            "score": None,
            "score_type": None,
        })
    return items


def fetch(cfg):
    rank_by = cfg.get("rank_by", "views")
    use_browser = cfg.get("use_browser", True)
    # Keep the N MOST-RECENTLY-ACTIVE threads per forum (the listing is already
    # in last-activity order). Capturing active threads — not just the highest
    # all-time-view ones — means rising topics get a stored baseline early, so
    # we don't lose them (they may surface a day or two later). Also stops one
    # busy forum from crowding out the others.
    per_forum = cfg.get("per_forum_items")
    all_items, ranked_items = [], 0

    for forum in cfg.get("forums", []):
        if "REPLACE_WITH" in forum:
            print(f"[voz] skipping placeholder forum {forum!r}; set a real slug.id")
            continue

        # 1) ranked HTML via headless browser (Top by views/replies)
        if use_browser:
            try:
                parsed = _parse(_fetch_html_browser(forum), forum,
                                rank_by=rank_by,
                                skip_sticky=cfg.get("skip_sticky", True))
                if parsed:
                    if per_forum:
                        parsed = parsed[:per_forum]   # most-recently-active (listing order)
                    print(f"[voz] {forum}: {len(parsed)} most-active threads (browser)")
                    all_items.extend(parsed)
                    ranked_items += len(parsed)
                    continue
                print(f"[voz] {forum}: browser listing empty; trying RSS")
            except ImportError:
                print("[voz] Playwright not installed; falling back to RSS. "
                      "Enable ranked voz: pip install playwright && python -m playwright install chromium")
            except Exception as exc:
                print(f"[voz] {forum}: browser path failed ({exc}); falling back to RSS")

        # 2) RSS fallback (chronological 'Latest')
        try:
            rss = _from_rss(forum)
            if per_forum:
                rss = rss[:per_forum]
            print(f"[voz] {forum}: {len(rss)} threads from RSS (chronological)")
            all_items.extend(rss)
        except Exception as exc:
            print(f"[voz] {forum}: RSS also failed: {exc}")

    # If we never got ranked data, the items are chronological -> relabel honestly.
    if all_items and ranked_items == 0:
        cfg["rank"] = "latest"
        cfg["label"] = "Latest"
    return all_items
