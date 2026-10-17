"""Small shared helpers for source modules."""
from datetime import datetime, timezone
from dateutil import parser as dateparser


def to_utc(dt):
    """Make a datetime timezone-aware in UTC (assume UTC if naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a date string (RSS pubDate, ISO, etc.) into a UTC datetime or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    try:
        return to_utc(dateparser.parse(value))
    except (ValueError, OverflowError, TypeError):
        return None


def to_iso(dt):
    """UTC ISO-8601 string for a datetime (None stays None)."""
    return to_utc(dt).isoformat() if dt else None


def from_iso(value):
    """Inverse of to_iso: ISO-8601 string -> UTC datetime (None stays None)."""
    if not value:
        return None
    return to_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def struct_time_to_utc(st):
    """Convert a feedparser time.struct_time (UTC) to a UTC datetime."""
    if not st:
        return None
    try:
        # feedparser yields *_parsed in UTC
        from calendar import timegm
        return datetime.fromtimestamp(timegm(st), tz=timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return None
