import json

import pytest

from fetcher.sources import engineerpro

POSTS = [{"canonical_url": f"https://ep.substack.com/p/{i}", "title": f"Post {i}",
          "post_date": "2026-10-14T13:24:17.352Z"} for i in range(3)]
CFG = {"archive_url": "https://ep.substack.com/api/v1/archive", "url": "https://ep.substack.com/feed"}


def methods(monkeypatch, **behaviour):
    """Replace the fetch methods: each name -> list to return, or an exception."""
    calls = []

    def make(name):
        def method(url):
            calls.append((name, url))
            result = behaviour[name]
            if isinstance(result, Exception):
                raise result
            return result
        return method

    monkeypatch.setattr(engineerpro, "METHODS", [(n, make(n)) for n in ("direct", "browser", "r.jina.ai")])
    return calls


def test_uses_direct_when_it_works(monkeypatch):
    calls = methods(monkeypatch, **{"direct": POSTS, "browser": RuntimeError("unused"),
                                    "r.jina.ai": RuntimeError("unused")})
    posts = engineerpro.fetch(CFG)
    assert [p["url"] for p in posts] == [p["canonical_url"] for p in POSTS]
    assert posts[0]["published_at"].isoformat().startswith("2026-10-14T13:24:17")
    assert [c[0] for c in calls] == ["direct"] and engineerpro.last_via == "direct"
    assert calls[0][1] == "https://ep.substack.com/api/v1/archive?sort=new&search=&offset=0&limit=50"


def test_falls_back_when_substack_blocks_github(monkeypatch):
    calls = methods(monkeypatch, **{"direct": RuntimeError("403 Client Error: Forbidden"),
                                    "browser": RuntimeError("Timeout 20000ms exceeded"),
                                    "r.jina.ai": POSTS})
    assert len(engineerpro.fetch(CFG)) == 3
    assert [c[0] for c in calls] == ["direct", "browser", "r.jina.ai"]
    assert engineerpro.last_via == "r.jina.ai"


def test_pages_through_the_whole_archive(monkeypatch):
    pages = {0: [dict(POSTS[0], canonical_url=f"https://ep/p/{i}") for i in range(50)],
             50: [dict(POSTS[0], canonical_url="https://ep/p/last")]}
    monkeypatch.setattr(engineerpro, "METHODS",
                        [("direct", lambda url: pages[int(url.split("offset=")[1].split("&")[0])])])
    assert len(engineerpro.fetch(CFG)) == 51


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
