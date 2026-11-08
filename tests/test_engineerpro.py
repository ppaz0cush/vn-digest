import json
from urllib.parse import parse_qs, urlsplit

import pytest

from fetcher.sources import engineerpro

POSTS = [{"canonical_url": f"https://ep.substack.com/p/{i}", "title": f"Post {i}",
          "post_date": "2026-10-14T13:24:17.352Z"} for i in range(3)]
CFG = {"archive_url": "https://ep.substack.com/api/v1/archive", "url": "https://ep.substack.com/feed"}
FIRST_PAGE = "https://ep.substack.com/api/v1/archive?sort=new&limit=25"
# Substack's answer to the old offset paging or a limit over 25 (since Nov 2026).
API_ERROR = '{"errors":[{"location":"query","param":"limit","value":50,"msg":"Invalid value"}]}'
RSS = [{"url": "https://ep/p/rss", "title": "R"}]


def _cursor(url):
    return parse_qs(urlsplit(url).query).get("cursor", [None])[0]


def methods(monkeypatch, **behaviour):
    """Replace the fetch methods: each name -> the archive's pages
    ({cursor: (posts, next cursor)}, None = the first page), or an exception."""
    calls = []

    def make(name):
        def method(url):
            calls.append((name, url))
            result = behaviour[name]
            if isinstance(result, Exception):
                raise result
            return result[_cursor(url)]
        return method

    monkeypatch.setattr(engineerpro, "METHODS", [(n, make(n)) for n in ("direct", "browser", "r.jina.ai")])
    return calls


def only_direct(pages):
    return {"direct": pages, "browser": RuntimeError("unused"), "r.jina.ai": RuntimeError("unused")}


def test_uses_direct_when_it_works(monkeypatch):
    calls = methods(monkeypatch, **only_direct({None: (POSTS, None)}))
    posts = engineerpro.fetch(CFG)
    assert [p["url"] for p in posts] == [p["canonical_url"] for p in POSTS]
    assert posts[0]["published_at"].isoformat().startswith("2026-10-14T13:24:17")
    assert calls == [("direct", FIRST_PAGE)]                        # no next cursor: the last page
    assert engineerpro.last_via == "direct"


def test_falls_back_when_substack_blocks_github(monkeypatch):
    calls = methods(monkeypatch, **{"direct": RuntimeError("403 Client Error: Forbidden"),
                                    "browser": RuntimeError("Timeout 20000ms exceeded"),
                                    "r.jina.ai": {None: (POSTS[:2], "c1"), "c1": (POSTS[2:], None)}})
    assert len(engineerpro.fetch(CFG)) == 3
    # the next page starts with the method that worked
    assert [c[0] for c in calls] == ["direct", "browser", "r.jina.ai", "r.jina.ai"]
    assert engineerpro.last_via == "r.jina.ai"


def _posts(start, n):
    return [dict(POSTS[0], canonical_url=f"https://ep/p/{i}") for i in range(start, start + n)]


def test_pages_through_the_whole_archive(monkeypatch):
    calls = methods(monkeypatch, **only_direct({None: (_posts(0, 25), "c1"), "c1": (_posts(25, 25), "c2"),
                                                "c2": (_posts(50, 20), None)}))
    posts = engineerpro.fetch(CFG)
    assert len(posts) == 70 and len({p["url"] for p in posts}) == 70
    assert [_cursor(url) for _, url in calls] == [None, "c1", "c2"]


def test_the_cursor_is_url_encoded(monkeypatch):
    cursor = "eyJ+/x=="     # base64: a raw '+' would reach Substack as a space
    calls = methods(monkeypatch, **only_direct({None: (POSTS[:1], cursor), cursor: (POSTS[1:], None)}))
    assert len(engineerpro.fetch(CFG)) == 3
    assert calls[1][1] == FIRST_PAGE + "&cursor=eyJ%2B%2Fx%3D%3D"


def test_stops_when_a_page_brings_nothing_new(monkeypatch):
    monkeypatch.setattr(engineerpro, "METHODS", [("direct", lambda url: (_posts(0, 5), "stuck"))])
    assert len(engineerpro.fetch(CFG)) == 5


def test_rss_is_the_last_resort(monkeypatch):
    methods(monkeypatch, **{n: RuntimeError("blocked") for n in ("direct", "browser", "r.jina.ai")})
    monkeypatch.setattr(engineerpro, "latest", lambda cfg: RSS)
    assert engineerpro.fetch(CFG) == RSS
    assert engineerpro.last_via == "rss"


def test_an_empty_archive_falls_back_to_rss(monkeypatch):
    methods(monkeypatch, **only_direct({None: ([], None)}))
    monkeypatch.setattr(engineerpro, "latest", lambda cfg: RSS)
    assert engineerpro.fetch(CFG) == RSS


def test_when_rss_fails_too_the_archive_error_is_kept(monkeypatch):
    methods(monkeypatch, **{n: RuntimeError(f"{n} blocked") for n in ("direct", "browser", "r.jina.ai")})

    def rss(cfg):
        raise RuntimeError("403 Client Error: Forbidden")

    monkeypatch.setattr(engineerpro, "latest", rss)
    with pytest.raises(RuntimeError) as err:
        engineerpro.fetch(CFG)
    assert "r.jina.ai: r.jina.ai blocked" in str(err.value)
    assert "RSS feed: 403 Client Error" in str(err.value)


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error")


def test_jina_reads_the_archive(monkeypatch):
    asked = []

    def get(url, **kwargs):
        asked.append(url)
        return _Resp(json.dumps({"posts": POSTS, "nextCursor": None}))

    monkeypatch.setattr(engineerpro, "METHODS", [("r.jina.ai", engineerpro._jina)])
    monkeypatch.setattr(engineerpro, "get", get)
    assert len(engineerpro.fetch(CFG)) == 3
    assert asked == ["https://r.jina.ai/" + FIRST_PAGE]


def test_an_api_error_relayed_by_jina_is_not_an_empty_archive(monkeypatch):
    # Nov 2026: Jina relayed the API's 400 body with a 200 and the run saw "no posts".
    monkeypatch.setattr(engineerpro, "METHODS", [("r.jina.ai", engineerpro._jina)])
    monkeypatch.setattr(engineerpro, "get", lambda url, **kwargs: _Resp(API_ERROR))
    monkeypatch.setattr(engineerpro, "latest", lambda cfg: RSS)
    assert engineerpro.fetch(CFG) == RSS


@pytest.mark.parametrize("body", [
    json.dumps({"posts": POSTS, "nextCursor": "c1"}),                                      # direct / browser / Jina
    "Title: \nURL Source: x\n\nMarkdown Content:\n" + json.dumps({"posts": POSTS, "nextCursor": "c1"}) + "\n",
])
def test_the_page_is_found_in_the_response(body):
    assert engineerpro._json_page(body) == (POSTS, "c1")


@pytest.mark.parametrize("body", [
    "<html><title>Just a moment...</title></html>",    # a Cloudflare challenge
    API_ERROR,                                         # an API error (Jina relays it with a 200)
    json.dumps(POSTS),                                 # the old format: a bare list
])
def test_anything_else_is_not_mistaken_for_data(body):
    with pytest.raises(ValueError):
        engineerpro._json_page(body)
