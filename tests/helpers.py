"""Offline tests (no network). Run: python -m pytest -q"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def vn(y, m, d, h=0, mi=0):
    """A Vietnam-local wall-clock time (UTC+7), as an aware UTC datetime."""
    return datetime(y, m, d, h, mi, tzinfo=UTC) - timedelta(hours=7)
