"""anonyviet — plain chronological RSS feed (https://anonyviet.com/feed/).

Low-volume tutorial blog; no engagement metric, so label is 'Latest'.
Config: long window (7 days) so the section isn't empty on quiet days.
"""
from ._rss import latest


def fetch(cfg):
    return latest(cfg)
