import json

import pytest

from fetcher.sources import engineerpro

POSTS = [{"canonical_url": f"https://ep.substack.com/p/{i}", "title": f"Post {i}",
          "post_date": "2026-10-14T13:24:17.352Z"} for i in range(3)]
CFG = {"archive_url": "https://ep.substack.com/api/v1/archive", "url": "https://ep.substack.com/feed"}


def methods(monkeypatch, **behaviour):
    """Replace the fetch methods: each name -> the archive's only page (a list;
    later offsets get []), or an exception."""
    calls = []

    def make(name):
        def method(url):
            calls.append((name, url))
            result = behaviour[name]
            if isinstance(result, Exception):
                raise result
            return result if "offset=0&" in url else []
        return method

    monkeypatch.setattr(engineerpro, "METHODS", [(n, make(n)) for n in ("direct", "browser", "r.jina.ai")])
    return calls


def test_uses_direct_when_it_works(monkeypatch):
    calls = methods(monkeypatch, **{"direct": POSTS, "browser": RuntimeError("unused"),
                                    "r.jina.ai": RuntimeError("unused")})
    posts = engineerpro.fetch(CFG)
    assert [p["url"] for p in posts] == [p["canonical_url"] for p in POSTS]
    assert posts[0]["published_at"].isoformat().startswith("2026-10-14T13:24:17")
    assert [c[0] for c in calls] == ["direct", "direct"] and engineerpro.last_via == "direct"
    assert calls[0][1] == "https://ep.substack.com/api/v1/archive?sort=new&search=&offset=0&limit=50"
    assert calls[1][1].endswith("offset=3&limit=50")                   # until an empty page


def test_falls_back_when_substack_blocks_github(monkeypatch):
    calls = methods(monkeypatch, **{"direct": RuntimeError("403 Client Error: Forbidden"),
                                    "browser": RuntimeError("Timeout 20000ms exceeded"),
                                    "r.jina.ai": POSTS})
    assert len(engineerpro.fetch(CFG)) == 3
    # the next page starts with the method that worked
    assert [c[0] for c in calls] == ["direct", "browser", "r.jina.ai", "r.jina.ai"]
    assert engineerpro.last_via == "r.jina.ai"


def _pages(monkeypatch, pages):
    """Serve archive pages by offset ([] past the end); returns the offsets asked for."""
    asked = []

    def direct(url):
        offset = int(url.split("offset=")[1].split("&")[0])
        asked.append(offset)
        return pages.get(offset, [])

    monkeypatch.setattr(engineerpro, "METHODS", [("direct", direct)])
    return asked


def _posts(start, n):
    return [dict(POSTS[0], canonical_url=f"https://ep/p/{i}") for i in range(start, start + n)]


def test_pages_through_the_whole_archive(monkeypatch):
    asked = _pages(monkeypatch, {0: _posts(0, 50), 50: _posts(50, 1)})
    assert len(engineerpro.fetch(CFG)) == 51
    assert asked == [0, 50, 51]


def test_a_short_first_page_is_not_the_end(monkeypatch):
    # Substack caps the first page at 23 posts whatever the limit; later pages are full.
    asked = _pages(monkeypatch, {0: _posts(0, 23), 23: _posts(23, 50), 73: _posts(73, 45)})
    posts = engineerpro.fetch(CFG)
    assert len(posts) == 118 and len({p["url"] for p in posts}) == 118
    assert asked == [0, 23, 73, 118] and engineerpro.last_via == "direct"


def test_stops_when_a_page_brings_nothing_new(monkeypatch):
    monkeypatch.setattr(engineerpro, "METHODS", [("direct", lambda url: _posts(0, 5))])   # ignores offset
    assert len(engineerpro.fetch(CFG)) == 5


def test_rss_is_the_last_resort(monkeypatch):
    methods(monkeypatch, **{n: RuntimeError("blocked") for n in ("direct", "browser", "r.jina.ai")})
    monkeypatch.setattr(engineerpro, "latest", lambda cfg: [{"url": "https://ep/p/rss", "title": "R"}])
    assert engineerpro.fetch(CFG)[0]["url"] == "https://ep/p/rss"
    assert engineerpro.last_via == "rss"


@pytest.mark.parametrize("body", [
    json.dumps(POSTS),                                              # direct / browser
    "Title: \nURL Source: x\n\nMarkdown Content:\n" + json.dumps(POSTS) + "\n",   # extra text around it
])
def test_json_list_is_found_in_the_response(body):
    assert len(engineerpro._json_list(body)) == 3


def test_a_blocked_page_is_not_mistaken_for_data():
    with pytest.raises(ValueError):
        engineerpro._json_list("<html><title>Just a moment...</title></html>")
