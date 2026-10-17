"""Weekly publish timing, plus small helpers shared by the sources.

The weekly list is published by the first run after the boundary set in
sources.yaml (`publish:` -> Monday 03:00 Asia/Ho_Chi_Minh), so a late or skipped
GitHub run only delays the list; it can't skip a week.
"""
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from .util import from_iso

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DEFAULTS = {"weekday": "monday", "hour": 3, "timezone": "Asia/Ho_Chi_Minh"}


def _settings(cfg):
    s = {**DEFAULTS, **(cfg or {})}
    return WEEKDAYS.index(str(s["weekday"]).lower()), int(s["hour"]), ZoneInfo(s["timezone"])


def boundary(now, cfg=None):
    """The most recent publish boundary at or before `now` (as UTC)."""
    weekday, hour, zone = _settings(cfg)
    local = now.astimezone(zone)
    day = local - timedelta(days=(local.weekday() - weekday) % 7)
    b = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    if b > local:
        b -= timedelta(days=7)
    return b.astimezone(timezone.utc)


def next_boundary(now, cfg=None):
    return boundary(now, cfg) + timedelta(days=7)


def publish_due(state, now, cfg=None):
    """True once a boundary has passed since the last publish. A brand-new
    install counts from when tracking started, so it waits for the next one."""
    since = state.last_publish or state.tracking_since
    return since is not None and since < boundary(now, cfg)


def week_start(state, now):
    """Start of the week being collected/published: the last publish, or (before
    the very first list) 7 days before now."""
    return state.last_publish or (now - timedelta(days=7))


def within_days(items, days, now):
    """Keep items published in the last `days` (None = no limit; undated kept)."""
    if days is None:
        return list(items)
    cutoff = now - timedelta(days=days)
    return [it for it in items if it.get("published_at") is None or it["published_at"] >= cutoff]


def published_between(items, start, end):
    """(key, item) pairs from a source's tracked items published in [start, end]."""
    out = []
    for key, it in items.items():
        pub = from_iso(it.get("published_at"))
        if pub is not None and start <= pub <= end:
            out.append((key, it))
    return out


def comment_row(source, url, it, rank, now):
    """Notion row for a weekly 'most comments' winner (tinhte, vnexpress)."""
    return {
        "url": url, "title": it["title"], "source": source, "subsource": None,
        "label": "Top", "score": it.get("comments"), "prev_score": None, "delta": None,
        "rank": rank, "published_at": from_iso(it.get("published_at")), "fetched_at": now,
    }


def post_row(source, it, now):
    """Notion row for an 'all' source post (anonyviet, engineerpro)."""
    return {
        "url": it["url"], "title": it["title"], "source": source, "subsource": None,
        "label": "Latest", "score": None, "prev_score": None, "delta": None,
        "rank": None, "published_at": it.get("published_at"), "fetched_at": now,
    }
