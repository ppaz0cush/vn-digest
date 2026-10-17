"""voz — weekly "most views gained" across the configured forums.

voz serves its thread lists behind Cloudflare, which blocks plain HTTP, so a
headless Chromium (Playwright) renders them. Every run reads each forum's own
list "updated in the last 7 days, sorted by views":

    https://voz.vn/f/<slug>.<id>/page-<n>?last_days=7&order=view_count&direction=desc

and records every (non-pinned) thread's view count in the tracking state.
Pages are read until the lowest total on a page is below the weekly gain a
thread currently needs to make the list: a thread can't gain more views in a
week than it has in total, so nothing further down is skipped (max_pages caps
the work).

At publish, gain = views now - views at the last publish. Threads started
during the week count all their views; threads first seen mid-week count from
when they were first seen. With `split: even` the `top` places are shared
evenly across the forums (20 -> 7/7/6), so news in Điểm báo can't crowd out
the other forums; places a forum can't fill go to the best of the rest. voz
rounds view counts ("41K", "3M"), so threads above max_views (shown in whole
millions) are left out: their weekly gain can't be measured.
"""
import re
import time
from collections import Counter
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..util import from_iso, parse_date, to_iso

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
LIST_QUERY = "last_days=7&order=view_count&direction=desc"


def _split_forum(forum):
    """A forum entry is '<slug>.<id>' (a normal /f/ forum) or '<type>/<slug>.<id>'
    for other node types, e.g. 's/example-slug.103' (voz's /s/ nodes)."""
    f = forum.strip().strip("/")
    if "/" in f:
        node_type, slug = f.split("/", 1)
    else:
        node_type, slug = "f", f
    return node_type, slug


def listing_url(forum, page=1):
    t, s = _split_forum(forum)
    return f"https://voz.vn/{t}/{s}/{'' if page == 1 else f'page-{page}'}?{LIST_QUERY}"


def _forum_label(forum):
    """'diem-bao.33' -> 'diem bao'; 's/example-slug.103' -> 'example slug'."""
    _, slug = _split_forum(forum)
    return re.sub(r"\.\d+$", "", slug).replace("-", " ")


def _unread(thread_url):
    """Rewrite a thread URL to its /unread form, which (when logged in) jumps to
    the reader's first unread post. e.g. /t/slug.123/ -> /t/slug.123/unread"""
    m = re.match(r"(https?://voz\.vn/t/[^/]+\.\d+)", thread_url or "")
    base = m.group(1) if m else (thread_url or "").rstrip("/")
    return f"{base}/unread" if base else thread_url


def _thread_id(url):
    m = re.search(r"/t/[^/?#]*\.(\d+)", url or "")
    return m.group(1) if m else None


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


def _time(el):
    """A XenForo <time>: exact unix data-timestamp when present, else parse."""
    if el is None:
        return None
    ts = el.get("data-timestamp")
    if ts and str(ts).isdigit():
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return parse_date(el.get("datetime") or el.get("title") or el.get_text(strip=True))


def parse_listing(html, forum):
    """Thread rows of a forum list page -> list of dicts (pinned ones flagged)."""
    soup = BeautifulSoup(html, "lxml")
    threads = []
    for row in soup.select("div.structItem--thread"):
        title_a = row.select_one(".structItem-title a[href*='/t/']")
        if not title_a:
            continue
        href = title_a.get("href", "")
        title = title_a.get_text(strip=True)
        url = href if href.startswith("http") else f"https://voz.vn{href}"
        tid = _thread_id(url)
        if not tid or not title:
            continue
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
        threads.append({
            "id": tid,
            "url": _unread(url),                  # deep-link to first unread post
            "title": title,
            "forum": forum,
            "subsource": _forum_label(forum),     # e.g. "diem bao" (Notion tag)
            "views": views,
            "replies": replies,
            "started_at": _time(row.select_one(".structItem-startDate time")),
            "last_post_at": _time(row.select_one(".structItem-latestDate")),
            "sticky": row.select_one(".structItem-status--sticky") is not None,
        })
    return threads


class Browser:
    """Headless Chromium. Each page gets a fresh browser context: voz's
    Cloudflare challenges a second navigation in the same session, but lets a
    fresh one straight through."""

    def __init__(self, pause=2.0):
        self.pause = pause

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # lazy: heavy dependency
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=True)
        except Exception:
            self._pw.stop()
            raise
        return self

    def get(self, url, attempts=3):
        last = None
        for attempt in range(1, attempts + 1):
            time.sleep(self.pause if attempt == 1 else 5 * attempt)
            ctx = self._browser.new_context(locale="vi-VN", user_agent=BROWSER_UA)
            try:
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_selector("div.structItem--thread", timeout=20000)
                return page.content()
            except Exception as exc:
                last = exc
            finally:
                ctx.close()
        raise RuntimeError(f"could not load {url} ({attempts} tries): {str(last)[:150]}")

    def __exit__(self, *exc):
        for close in (self._browser.close, self._pw.stop):
            try:
                close()
            except Exception:
                pass


def _gain(it, week_start):
    """(views gained this week, baseline used) for a tracked thread."""
    views = it.get("views")
    if views is None:
        return None, None
    if it.get("base_views") is not None:          # known at the last publish
        base = it["base_views"]
    else:
        started = from_iso(it.get("started_at"))
        if started is not None and started >= week_start:
            base = 0                              # started this week: all its views
        elif it.get("first_seen_views") is not None:
            base = it["first_seen_views"]         # first seen mid-week
        else:
            base = views
    return max(views - base, 0), base


def ranked(items, week_start, max_views=None):
    """Threads seen this week, best weekly gain first: [(gain, views, item, base)]."""
    out = []
    for it in items.values():
        seen = from_iso(it.get("last_seen_at"))
        if seen is None or seen < week_start:
            continue
        if max_views is not None and (it.get("views") or 0) > max_views:
            continue
        gain, base = _gain(it, week_start)
        if gain:
            out.append((gain, it.get("views") or 0, it, base))
    out.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return out


def _quotas(cfg):
    """Places per forum: `top` shared evenly (split: even, e.g. 20 -> 7/7/6),
    or None for one overall ranking (split: overall)."""
    forums, top = cfg.get("forums", []), cfg.get("top", 20)
    if cfg.get("split", "even") != "even" or len(forums) < 2:
        return None
    base, extra = divmod(top, len(forums))
    return {f: base + (1 if i < extra else 0) for i, f in enumerate(forums)}


def select(items, week_start, cfg):
    """This week's list, best gain first. With split: even every forum gets its
    share of `top`; places a forum can't fill go to the best of the rest."""
    best = ranked(items, week_start, cfg.get("max_views"))
    top = cfg.get("top", 20)
    quotas = _quotas(cfg)
    if quotas is None:
        return best[:top]
    picked, taken = [], Counter()
    for r in best:
        forum = r[2].get("forum")
        if taken[forum] < quotas.get(forum, 0):
            picked.append(r)
            taken[forum] += 1
    chosen = {id(r[2]) for r in picked}
    picked += [r for r in best if id(r[2]) not in chosen][: top - len(picked)]
    picked.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return picked


def _cutoffs(items, week_start, cfg):
    """Per forum, the weekly gain a thread currently needs to make the list:
    its forum's quota-th best gain, or the overall top-th best (the bar for the
    places a forum can't fill), whichever is lower; 0 while there are too few."""
    best = ranked(items, week_start, cfg.get("max_views"))
    top = cfg.get("top", 20)
    overall = best[top - 1][0] if len(best) >= top else 0
    quotas = _quotas(cfg)
    if quotas is None:
        return {f: overall for f in cfg.get("forums", [])}
    out = {}
    for forum, quota in quotas.items():
        gains = [g for g, _v, it, _b in best if it.get("forum") == forum]
        out[forum] = min(gains[quota - 1], overall) if quota and len(gains) >= quota else 0
    return out


def _record(items, t, now):
    it = items.get(t["id"])
    if it is None:
        it = items[t["id"]] = {"first_seen_at": to_iso(now), "first_seen_views": t["views"],
                               "base_views": None}
    elif it.get("first_seen_views") is None:
        it["first_seen_views"] = t["views"]
    it.update({
        "url": t["url"], "title": t["title"], "forum": t["forum"], "subsource": t["subsource"],
        "views": t["views"], "replies": t["replies"],
        "started_at": to_iso(t["started_at"]) or it.get("started_at"),
        "last_post_at": to_iso(t["last_post_at"]),
        "last_seen_at": to_iso(now),
    })


def collect(cfg, src, now, week_start, browser=Browser):
    """Record the view counts of every thread that could make this week's list."""
    items = src["items"]
    max_pages = cfg.get("max_pages", 8)
    skip_sticky = cfg.get("skip_sticky", True)
    cutoffs = _cutoffs(items, week_start, cfg)

    seen_ids, failed, total_pages = set(), [], 0
    with browser() as br:
        for forum in cfg.get("forums", []):
            cutoff = cutoffs.get(forum, 0)
            got = pages = 0
            for n in range(1, max_pages + 1):
                try:
                    html = br.get(listing_url(forum, n))
                except Exception as exc:
                    print(f"[voz] {forum} page {n}: {exc}")
                    if n == 1:
                        failed.append(forum)
                    break
                pages += 1
                threads = [t for t in parse_listing(html, forum)
                           if not (skip_sticky and t["sticky"]) and t["id"] not in seen_ids]
                if not threads:          # past the last page voz repeats the last one
                    break
                for t in threads:
                    seen_ids.add(t["id"])
                    _record(items, t, now)
                got += len(threads)
                lowest = min((t["views"] for t in threads if t["views"] is not None), default=None)
                if lowest is None or lowest < cutoff:
                    break
            print(f"[voz] {forum}: {got} threads from {pages} page(s) (cutoff {cutoff:,} views)")
            total_pages += pages
    if failed:
        raise RuntimeError(f"couldn't load {', '.join(failed)}")
    return f"{len(seen_ids)} threads from {total_pages} pages"


def publish(cfg, src, now, week_start):
    """This week's list (see select), as Notion rows."""
    best = select(src["items"], week_start, cfg)
    return [{
        "url": it["url"], "title": it["title"], "source": "voz", "subsource": it.get("subsource"),
        "label": "Top", "score": it.get("views"), "prev_score": base, "delta": gain,
        "rank": i, "published_at": from_iso(it.get("started_at")), "fetched_at": now,
    } for i, (gain, _views, it, base) in enumerate(best, start=1)]


def after_publish(src, now, week_start):
    """Start the next week: today's counts become the baselines. Threads not
    seen all week are forgotten, so a later comeback starts a fresh baseline."""
    items = src["items"]
    for key in [k for k, it in items.items()
                if (from_iso(it.get("last_seen_at")) or now) < week_start]:
        del items[key]
    for it in items.values():
        it["base_views"] = it.get("views")
