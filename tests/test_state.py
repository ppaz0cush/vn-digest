from datetime import timedelta

from fetcher.state import State
from fetcher.util import to_iso

from tests.helpers import vn


def test_round_trip(tmp_path):
    path = tmp_path / "nested" / "state.json"
    st = State.load(path)
    assert st.last_publish is None and st.tracking_since is None
    now = vn(2026, 10, 17, 16)
    st.start_tracking(now)
    st.weekly_db_id = "abc"
    st.source("voz")["items"]["1"] = {"title": "Điểm báo", "last_seen_at": to_iso(now)}
    st.save()

    again = State.load(path)
    assert again.tracking_since == now
    assert again.weekly_db_id == "abc"
    assert again.source("voz")["items"]["1"]["title"] == "Điểm báo"
    assert "Điểm báo" in path.read_text(encoding="utf-8")   # readable, not \u-escaped
    assert not list(path.parent.glob("*.tmp"))


def test_tracking_start_is_set_once():
    st = State(path="unused")
    st.start_tracking(vn(2026, 10, 17))
    st.start_tracking(vn(2026, 10, 18))
    assert st.tracking_since == vn(2026, 10, 17)


def test_failure_streak():
    st = State(path="unused")
    assert st.record_result("voz", False) == 1
    assert st.record_result("voz", False) == 2
    assert st.record_result("voz", True) == 0


def test_last_error_is_kept_for_debugging():
    st = State(path="unused")
    st.record_result("engineerpro", False, vn(2026, 10, 17, 20), "HTTPError: 403 Forbidden")
    st.record_result("engineerpro", True, vn(2026, 10, 18, 3))
    src = st.source("engineerpro")
    assert src["last_error"] == {"at": to_iso(vn(2026, 10, 17, 20)), "error": "HTTPError: 403 Forbidden"}
    assert src["last_ok_at"] == to_iso(vn(2026, 10, 18, 3)) and src["failures"] == 0


def test_prune_forgets_stale_items_but_keeps_created_markers():
    now = vn(2026, 10, 30)
    st = State(path="unused")
    items = st.source("voz")["items"]
    items["old"] = {"last_seen_at": to_iso(now - timedelta(days=15))}
    items["recent"] = {"last_seen_at": to_iso(now - timedelta(days=2))}
    st.source("engineerpro")["created"]["https://x/p/1"] = to_iso(now - timedelta(days=400))
    st.prune(now)
    assert set(items) == {"recent"}
    assert "https://x/p/1" in st.source("engineerpro")["created"]
