"""Recency filter + sort + cap helpers, shared by all source modules.

An "item" here is a plain dict with at least:
  url, title, published_at (timezone-aware datetime or None), score (int|None)
Sources produce these; main.py normalizes them to the DB schema.
"""
from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def within_window(item, window_hours):
    """Keep items published within the last `window_hours`.

    Items with an unknown published_at are KEPT (better to show than silently
    drop) but will sort last when ranking by recency.
    """
    pub = item.get("published_at")
    if pub is None:
        return True
    cutoff = now_utc() - timedelta(hours=window_hours)
    return pub >= cutoff


def filter_window(items, window_hours):
    # window_hours None => no recency filter (e.g. daily.dev's anonymous feed
    # returns frozen/stale createdAt values, so a window would empty it).
    if window_hours is None:
        return list(items)
    return [it for it in items if within_window(it, window_hours)]


def _published_key(item):
    pub = item.get("published_at")
    # None sorts oldest (smallest)
    return pub or datetime.min.replace(tzinfo=timezone.utc)


def rank_items(items, *, rank, tiebreak=None):
    """Sort items per the source config.

    rank == 'latest'  -> newest first by published_at
    rank == 'top'      -> highest score first; tiebreak 'published_desc' breaks
                          ties by newest. Items without a score sort last.
    """
    if rank == "latest":
        return sorted(items, key=_published_key, reverse=True)

    # rank == 'top'
    def top_key(it):
        score = it.get("score")
        score = score if isinstance(score, int) else -1
        return (score, _published_key(it))

    if tiebreak == "published_desc":
        return sorted(items, key=top_key, reverse=True)
    # default tiebreak: just score, stable for equal scores
    return sorted(items, key=lambda it: it.get("score") or -1, reverse=True)


def process(items, *, rank, window_hours, max_items, tiebreak=None):
    """Filter to window, rank, cap, and stamp rank_position (1-based)."""
    kept = filter_window(items, window_hours)
    ordered = rank_items(kept, rank=rank, tiebreak=tiebreak)
    capped = ordered[:max_items]
    for i, it in enumerate(capped, start=1):
        it["rank_position"] = i
    return capped
