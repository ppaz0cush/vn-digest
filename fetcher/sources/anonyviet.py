"""anonyviet — every post from https://anonyviet.com/feed/ (mode: all).

The feed holds the latest 10 posts (about a week), and runs happen several
times a day, so nothing is missed. `lookback_days` keeps old posts out.
"""
from ._rss import latest


def fetch(cfg):
    return latest(cfg)
