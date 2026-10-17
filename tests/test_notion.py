import pytest

from fetcher.notion import Notion, NotionError, properties
from fetcher.state import State

ORIGINAL = "1234abcd-0000-0000-0000-000000000000"


def notion(monkeypatch, handler=None):
    for var in ("NOTION_WEEKLY_DB_ID", "NOTION_PARENT_PAGE_ID"):
        monkeypatch.delenv(var, raising=False)
    n = Notion(token="test-token", original_db_id=ORIGINAL)
    calls = []

    def fake_call(method, path, payload=None, attempts=4):
        calls.append((method, path))
        if handler is None:
            raise AssertionError(f"unexpected Notion call {method} {path}")
        return handler(method, path, payload)

    monkeypatch.setattr(n, "_call", fake_call)
    return n, calls


def test_never_touches_the_original_database(monkeypatch):
    n, calls = notion(monkeypatch)
    same_id = ORIGINAL.replace("-", "").upper()        # any spelling of the same id
    with pytest.raises(NotionError):
        n.write(same_id, [{"url": "https://x", "title": "t"}], {})
    with pytest.raises(NotionError):
        n.index(ORIGINAL)
    with pytest.raises(NotionError):
        n.archive_older_than(same_id, 30)
    assert calls == []


def test_refuses_an_override_pointing_at_the_original(monkeypatch):
    n, _ = notion(monkeypatch)
    monkeypatch.setenv("NOTION_WEEKLY_DB_ID", ORIGINAL)
    with pytest.raises(NotionError):
        n.weekly_database()


def test_creates_the_weekly_database_next_to_the_original(monkeypatch):
    def handler(method, path, payload):
        if path == "/search":
            return {"results": [], "has_more": False}
        if (method, path) == ("GET", f"/databases/{ORIGINAL}"):
            return {"parent": {"type": "page_id", "page_id": "parent-page"}}
        if (method, path) == ("POST", "/databases"):
            assert payload["parent"]["page_id"] == "parent-page"
            assert "Δ week" in payload["properties"] and "Δ today" not in payload["properties"]
            return {"id": "weekly-db", "url": "https://notion.so/weekly-db"}
        raise AssertionError(path)

    n, calls = notion(monkeypatch, handler)
    st = State(path="unused")
    assert n.weekly_database(st) == "weekly-db"
    assert st.weekly_db_id == "weekly-db"
    # the only request involving the original database is that one read
    assert [c for c in calls if ORIGINAL in c[1]] == [("GET", f"/databases/{ORIGINAL}")]


def test_finds_the_remembered_database_and_never_creates_in_dry_runs(monkeypatch):
    def handler(method, path, payload):
        if path == "/databases/remembered":
            return {"id": "remembered"}
        if path == "/search":
            return {"results": [], "has_more": False}
        raise AssertionError(path)

    n, calls = notion(monkeypatch, handler)
    st = State(path="unused")
    st.weekly_db_id = "remembered"
    assert n.weekly_database(st, create=False) == "remembered"
    assert n.weekly_database(State(path="unused"), create=False) is None
    assert ("POST", "/databases") not in calls


def test_status_is_only_set_when_creating():
    row = {"url": "https://x", "title": "t", "source": "voz", "subsource": "diem bao", "label": "Top",
           "score": 5, "delta": 3, "prev_score": 2, "rank": 1, "published_at": None, "fetched_at": None}
    created = properties(row, creating=True)
    assert created["Status"] == {"select": {"name": "New"}}
    assert created["Source"] == {"multi_select": [{"name": "voz"}, {"name": "diem bao"}]}
    assert created["Δ week"] == {"number": 3}
    assert "Status" not in properties(row, creating=False)
