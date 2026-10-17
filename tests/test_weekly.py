from datetime import timedelta

from fetcher import weekly
from fetcher.state import State

from tests.helpers import vn


def test_boundary_is_the_last_monday_3am_vietnam_time():
    assert weekly.boundary(vn(2026, 10, 17, 16)) == vn(2026, 10, 12, 3)      # Saturday
    assert weekly.boundary(vn(2026, 10, 19, 2, 59)) == vn(2026, 10, 12, 3)   # Monday, before 03:00
    assert weekly.boundary(vn(2026, 10, 19, 3)) == vn(2026, 10, 19, 3)       # Monday 03:00
    assert weekly.next_boundary(vn(2026, 10, 17, 16)) == vn(2026, 10, 19, 3)


def test_publish_day_is_configurable():
    cfg = {"weekday": "sunday", "hour": 20, "timezone": "Asia/Ho_Chi_Minh"}
    assert weekly.boundary(vn(2026, 10, 17, 16), cfg) == vn(2026, 10, 11, 20)


def test_a_new_install_waits_for_the_next_boundary():
    st = State(path="unused")
    st.start_tracking(vn(2026, 10, 17, 16))
    assert not weekly.publish_due(st, vn(2026, 10, 17, 16))
    assert not weekly.publish_due(st, vn(2026, 10, 19, 2, 59))
    assert weekly.publish_due(st, vn(2026, 10, 19, 3, 15))


def test_publishes_once_a_week_even_when_runs_are_late_or_dropped():
    st = State(path="unused")
    st.start_tracking(vn(2026, 10, 17, 16))
    st.mark_published(vn(2026, 10, 19, 6, 10))                   # Monday's run came 3h late
    assert not weekly.publish_due(st, vn(2026, 10, 20, 9, 15))
    assert not weekly.publish_due(st, vn(2026, 10, 26, 2, 59))
    assert weekly.publish_due(st, vn(2026, 10, 26, 9, 15))       # 03:15 run dropped: the next one publishes


def test_week_start():
    st = State(path="unused")
    now = vn(2026, 10, 19, 3, 15)
    assert weekly.week_start(st, now) == now - timedelta(days=7)   # before the first list
    st.mark_published(vn(2026, 10, 19, 3, 20))
    assert weekly.week_start(st, vn(2026, 10, 22)) == vn(2026, 10, 19, 3, 20)


def test_within_days():
    now = vn(2026, 10, 17)
    items = [{"published_at": now - timedelta(days=20)},
             {"published_at": now - timedelta(days=1)},
             {"published_at": None}]
    assert len(weekly.within_days(items, 14, now)) == 2    # undated posts are kept
    assert len(weekly.within_days(items, None, now)) == 3  # no limit
