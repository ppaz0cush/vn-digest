"""End-to-end runs of fetcher.main with fake sources and an in-memory Notion."""
import types
from argparse import Namespace

import pytest

from fetcher import main as m
from fetcher.state import State

from tests.helpers import vn


class FakeNotion:
    """Stands in for fetcher.notion.Notion: one in-memory weekly database."""
    instances = []

    def __init__(self):
        self.rows = {}           # url -> row
        self.writes = 0
        FakeNotion.instances.append(self)

    def weekly_database(self, state, create=True):
        state.weekly_db_id = "weekly-db"
        return "weekly-db"

    def index(self, db_id):
        return {url: url for url in self.rows}

    def write(self, db_id, rows, index, update_existing=True):
        created = updated = 0
        for r in rows:
            self.writes += 1
            if r["url"] not in index:
                index[r["url"]] = r["url"]
                self.rows[r["url"]] = r
                created += 1
            elif update_existing:
                self.rows[r["url"]] = r
                updated += 1
        return created, updated, []


@pytest.fixture
def env(monkeypatch, tmp_path):
    notion = FakeNotion()
    posts = [{"url": "https://ep/p/1", "title": "Post 1", "published_at": vn(2026, 7, 8)},
             {"url": "https://ep/p/2", "title": "Post 2", "published_at": vn(2026, 10, 14)}]
    published = []

    def collect(cfg, src, now, week_start):
        src["items"]["t1"] = {"title": "Thread", "seen": str(now)}
        return "1 thread"

    def publish(cfg, src, now, week_start):
        published.append(week_start)
        return [{"url": "https://voz/t/1", "title": "Thread", "source": "fakeweekly", "subsource": None,
                 "label": "Top", "score": 10, "prev_score": 0, "delta": 10, "rank": 1,
                 "published_at": None, "fetched_at": now}]

    def after_publish(src, now, week_start):
        src["reset_at"] = str(now)

    weekly_mod = types.SimpleNamespace(collect=collect, publish=publish, after_publish=after_publish)
    all_mod = types.SimpleNamespace(fetch=lambda cfg: list(posts))
    monkeypatch.setitem(m.WEEKLY_SOURCES, "fakeweekly", weekly_mod)
    monkeypatch.setitem(m.ALL_SOURCES, "fakeall", all_mod)
    monkeypatch.setattr(m, "load_config", lambda: {
        "publish": {"weekday": "monday", "hour": 3, "timezone": "Asia/Ho_Chi_Minh"},
        "sources": [{"name": "fakeweekly", "mode": "weekly_top"},
                    {"name": "fakeall", "mode": "all", "lookback_days": None}]})
    monkeypatch.setattr(m, "Notion", lambda: notion)
    monkeypatch.setenv("NOTION_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    state_path = tmp_path / "state.json"

    def run(now, **flags):
        args = Namespace(dry_run=False, publish=False, only=None, state=str(state_path))
        for k, v in flags.items():
            setattr(args, k, v)
        return m.run(args, now=now)

    return types.SimpleNamespace(run=run, notion=notion, posts=posts, published=published,
                                 state=lambda: State.load(state_path), state_path=state_path,
                                 weekly_mod=weekly_mod)


def test_first_runs_write_new_posts_and_wait_for_monday(env):
    assert env.run(vn(2026, 10, 17, 16))                       # Saturday: first run
    assert set(env.notion.rows) == {"https://ep/p/1", "https://ep/p/2"}   # every post, any age
    assert env.notion.rows["https://ep/p/1"]["label"] == "Latest"
    st = env.state()
    assert st.tracking_since == vn(2026, 10, 17, 16) and st.last_publish is None
    assert env.published == []

    env.posts.append({"url": "https://ep/p/3", "title": "Post 3", "published_at": vn(2026, 10, 18)})
    writes = env.notion.writes
    assert env.run(vn(2026, 10, 18, 9, 15))                    # Sunday
    assert env.notion.writes == writes + 1                     # only the new post
    assert env.published == []


def test_monday_run_publishes_once(env):
    env.run(vn(2026, 10, 17, 16))
    assert env.run(vn(2026, 10, 19, 3, 15))                    # Monday 03:15
    assert "https://voz/t/1" in env.notion.rows
    assert env.published == [vn(2026, 10, 12, 3, 15)]           # first list: the previous 7 days
    st = env.state()
    assert st.last_publish == vn(2026, 10, 19, 3, 15)
    assert st.source("fakeweekly")["reset_at"]                  # next week's baselines set

    env.run(vn(2026, 10, 19, 9, 15))
    assert len(env.published) == 1                              # not again the same week
    env.run(vn(2026, 10, 26, 3, 15))
    assert env.published[-1] == vn(2026, 10, 19, 3, 15)         # next week starts at the last list


def test_dry_run_writes_nothing_and_saves_nothing(env):
    assert env.run(vn(2026, 10, 19, 3, 15), dry_run=True, publish=True)
    assert env.notion.rows == {} and env.notion.writes == 0
    assert not env.state_path.exists()


def test_a_pruned_post_does_not_come_back(env):
    env.run(vn(2026, 10, 17, 16))
    del env.notion.rows["https://ep/p/1"]                       # you pruned it in Notion
    env.run(vn(2026, 10, 18, 9, 15))
    assert "https://ep/p/1" not in env.notion.rows


def test_fails_only_after_a_day_of_failures(env, monkeypatch):
    def broken(cfg, src, now, week_start):
        raise RuntimeError("voz is down")
    monkeypatch.setattr(env.weekly_mod, "collect", broken)
    results = [env.run(vn(2026, 10, 17, h)) for h in (3, 9, 15, 21)]
    assert results == [True, True, True, False]                 # 4th failure in a row -> red run
    assert env.state().source("fakeweekly")["failures"] == 4


def test_a_notion_hiccup_is_retried_within_the_run(env, monkeypatch):
    env.run(vn(2026, 10, 17, 16))
    real, calls = env.notion.weekly_database, []

    def flaky(state, create=True):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Notion 502")
        return real(state, create)

    monkeypatch.setattr(env.notion, "weekly_database", flaky)
    assert env.run(vn(2026, 10, 19, 3, 15))                     # Monday
    assert env.state().source("fakeall")["failures"] == 1       # the hiccup hit the 'all' source...
    assert "https://voz/t/1" in env.notion.rows                 # ...and the publish retried and wrote
