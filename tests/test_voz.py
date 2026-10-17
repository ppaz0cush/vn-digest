from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fetcher.sources import voz
from fetcher.util import to_iso

FIXTURE = Path(__file__).parent / "fixtures" / "voz_diem_bao_p1.html"
WEEK = datetime(2026, 10, 12, tzinfo=timezone.utc)   # week start (last publish)
NOW = WEEK + timedelta(days=7)


# --- parsing a real voz page ----------------------------------------------------

def test_parse_real_listing_page():
    threads = voz.parse_listing(FIXTURE.read_text(encoding="utf-8"), "diem-bao.33")
    assert len(threads) == 7
    assert [t["id"] for t in threads if t["sticky"]] == ["1110746"]   # the pinned rules thread

    iran = next(t for t in threads if t["id"] == "1216621")
    assert iran["views"] == 3_000_000 and iran["replies"] == 23_000
    assert iran["url"].startswith("https://voz.vn/t/tinh-hinh-iran")
    assert iran["url"].endswith(".1216621/unread")
    assert iran["started_at"] == datetime.fromtimestamp(1773201602, tz=timezone.utc)
    assert iran["last_post_at"] > iran["started_at"]
    assert iran["subsource"] == "diem bao"

    newest = next(t for t in threads if t["id"] == "1286605")
    assert newest["views"] == 56_000 and newest["started_at"].date().isoformat() == "2026-10-07"


def test_listing_url():
    q = "?last_days=7&order=view_count&direction=desc"
    assert voz.listing_url("diem-bao.33") == f"https://voz.vn/f/diem-bao.33/{q}"
    assert voz.listing_url("diem-bao.33", 2) == f"https://voz.vn/f/diem-bao.33/page-2{q}"
    assert voz.listing_url("s/example-slug.103", 3) == f"https://voz.vn/s/example-slug.103/page-3{q}"


@pytest.mark.parametrize("text,value", [("19K", 19_000), ("3M", 3_000_000), ("1.2K", 1_200),
                                        ("821", 821), ("1,234", 1_234), ("", None), ("n/a", None)])
def test_count(text, value):
    assert voz._count(text) == value


# --- weekly gain ------------------------------------------------------------------

def item(title, views, *, base=None, first=None, started=None, seen=NOW):
    return {"title": title, "url": f"https://voz.vn/t/{title}.1/unread", "subsource": "diem bao",
            "views": views, "base_views": base, "first_seen_views": first,
            "started_at": to_iso(started), "last_seen_at": to_iso(seen)}


def sample_items():
    return {
        "old": item("old", 50_000, base=40_000, started=WEEK - timedelta(days=30)),  # +10K since last list
        "new": item("new", 30_000, started=WEEK + timedelta(days=2)),               # started this week: +30K
        "mid": item("mid", 25_000, first=20_000, started=WEEK - timedelta(days=30)),  # first seen mid-week: +5K
        "huge": item("huge", 3_000_000, base=2_000_000),          # shown in millions: skipped
        "flat": item("flat", 9_000, base=9_000),                  # gained nothing: left out
        "stale": item("stale", 99_000, base=1_000, seen=WEEK - timedelta(days=1)),  # not seen this week
    }


def test_ranking_by_views_gained():
    ranked = voz.ranked(sample_items(), WEEK, max_views=999_999)
    assert [(gain, it["title"], base) for gain, _, it, base in ranked] == [
        (30_000, "new", 0), (10_000, "old", 40_000), (5_000, "mid", 20_000)]


def test_publish_rows_then_start_next_week():
    src = {"items": sample_items()}
    rows = voz.publish({"top": 2, "max_views": 999_999}, src, NOW, WEEK)
    assert [(r["rank"], r["title"], r["delta"], r["prev_score"], r["score"]) for r in rows] == [
        (1, "new", 30_000, 0, 30_000), (2, "old", 10_000, 40_000, 50_000)]
    assert rows[0]["source"] == "voz" and rows[0]["subsource"] == "diem bao" and rows[0]["label"] == "Top"

    voz.after_publish(src, NOW, WEEK)
    assert "stale" not in src["items"]                      # not seen all week: forgotten
    assert src["items"]["new"]["base_views"] == 30_000      # next week counts from here


# --- sharing the places between forums (split: even) -----------------------------

FORUMS = ["news.1", "chat.2", "love.3"]


def forum_items():
    """news gains 90K..50K, chat 9K..5K, love only 2 threads (1K, 500)."""
    items = {}
    for forum, gains in (("news.1", [90, 80, 70, 60, 50]), ("chat.2", [9, 8, 7, 6, 5]),
                         ("love.3", [1, 0.5])):
        for i, g in enumerate(gains):
            it = item(f"{forum}-{i}", int(g * 1000), base=0)
            it["forum"] = forum
            items[it["title"]] = it
    return items


def test_even_split_gives_every_forum_a_share():
    cfg = {"forums": FORUMS, "top": 7}                       # 7 -> 3/2/2 places
    picked = [it["title"] for _g, _v, it, _b in voz.select(forum_items(), WEEK, cfg)]
    assert picked == ["news.1-0", "news.1-1", "news.1-2", "chat.2-0", "chat.2-1",
                      "love.3-0", "love.3-1"]


def test_places_a_forum_cannot_fill_go_to_the_best_of_the_rest():
    cfg = {"forums": FORUMS, "top": 9}                       # 3/3/3, but love has only 2
    picked = [it["title"] for _g, _v, it, _b in voz.select(forum_items(), WEEK, cfg)]
    assert len(picked) == 9 and picked.count("love.3-0") == 1
    assert "news.1-3" in picked                              # the spare place: next-best overall


def test_overall_split_is_one_ranking():
    cfg = {"forums": FORUMS, "top": 5, "split": "overall"}
    picked = [it["forum"] for _g, _v, it, _b in voz.select(forum_items(), WEEK, cfg)]
    assert picked == ["news.1"] * 5


def test_paging_cutoff_per_forum():
    cfg = {"forums": FORUMS, "top": 7}                       # quotas 3/2/2
    cutoffs = voz._cutoffs(forum_items(), WEEK, cfg)
    # news: its 3rd best (70K) but never above the overall 7th best (8K)
    assert cutoffs == {"news.1": 8_000, "chat.2": 8_000, "love.3": 500}
    assert voz._cutoffs({}, WEEK, cfg) == {f: 0 for f in FORUMS}   # nothing known yet: read all


# --- collecting: paging stops once nothing on later pages can make the top N -----

def listing(rows):
    """A minimal voz list page: rows of (thread id, views[, sticky])."""
    out = []
    for tid, views, *sticky in rows:
        status = ('<li><i class="structItem-status structItem-status--sticky"></i></li>'
                  if sticky and sticky[0] else "")
        out.append(f"""
<div class="structItem structItem--thread js-threadListItem-{tid}">
 <div class="structItem-cell structItem-cell--main"><ul class="structItem-statuses">{status}</ul>
  <div class="structItem-title"><a href="/t/thread-{tid}.{tid}/">Thread {tid}</a></div>
  <ul class="structItem-parts"><li class="structItem-startDate"><a><time class="u-dt" data-timestamp="1790000000">x</time></a></li></ul>
 </div>
 <div class="structItem-cell structItem-cell--meta"><dl><dt>Trả lời</dt><dd>5</dd></dl><dl><dt>Lượt xem</dt><dd>{views}</dd></dl></div>
 <div class="structItem-cell structItem-cell--latest"><time class="structItem-latestDate u-dt" data-timestamp="1792000000">x</time></div>
</div>""")
    return "<html><body>" + "".join(out) + "</body></html>"


class FakeBrowser:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def get(self, url):
        self.requested.append(url)
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        return page if page is not None else listing([])


def test_collect_stops_paging_below_the_cutoff():
    br = FakeBrowser({
        voz.listing_url("f.1", 1): listing([("9", 5_000_000, True), ("1", 90_000), ("2", 50_000)]),
        voz.listing_url("f.1", 2): listing([("3", 30_000), ("4", 20_000)]),
        voz.listing_url("f.1", 3): listing([("5", 10_000)]),
    })
    # current gains: 50K and 25K -> with top 2 the cutoff is 25K, so after page 2
    # (lowest 20K) nothing further down can make the list
    src = {"items": {"a": item("a", 80_000, base=30_000), "b": item("b", 60_000, base=35_000)}}
    detail = voz.collect({"forums": ["f.1"], "top": 2, "max_pages": 8}, src, NOW, WEEK, browser=br)
    assert br.requested == [voz.listing_url("f.1", 1), voz.listing_url("f.1", 2)]
    assert set(src["items"]) == {"a", "b", "1", "2", "3", "4"}          # pinned "9" skipped
    new = src["items"]["1"]
    assert new["views"] == 90_000 and new["first_seen_views"] == 90_000 and new["base_views"] is None
    assert "4 threads from 2 pages" in detail


def test_collect_stops_when_voz_repeats_the_last_page():
    last = listing([("1", 900), ("2", 800)])
    br = FakeBrowser({voz.listing_url("f.1", 1): last, voz.listing_url("f.1", 2): last})
    voz.collect({"forums": ["f.1"], "top": 20, "max_pages": 8}, {"items": {}}, NOW, WEEK, browser=br)
    assert len(br.requested) == 2


def test_collect_reports_a_forum_that_fails_but_keeps_the_others():
    br = FakeBrowser({voz.listing_url("bad.1", 1): RuntimeError("challenge"),
                      voz.listing_url("ok.2", 1): listing([("1", 900)])})
    src = {"items": {}}
    with pytest.raises(RuntimeError, match="bad.1"):
        voz.collect({"forums": ["bad.1", "ok.2"], "max_pages": 1}, src, NOW, WEEK, browser=br)
    assert set(src["items"]) == {"1"}
