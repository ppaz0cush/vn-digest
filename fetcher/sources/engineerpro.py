"""engineerpro — EngineerPro VN Substack RSS (https://engineerprovn.substack.com/feed).

Chronological, no engagement metric ('Latest'). They post only ~2-3x/week, so
config uses a long window (14 days) to keep the section populated.
"""
from ._rss import latest


def fetch(cfg):
    return latest(cfg)
