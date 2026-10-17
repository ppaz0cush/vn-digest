"""VN Digest fetcher: collects all week, publishes a weekly list to Notion.

Every run (GitHub Actions runs it 4x a day):
  - 'all' sources (anonyviet, engineerpro): new posts go straight into Notion.
  - 'weekly_top' sources (voz, tinhte, vnexpress): view/comment counts are
    recorded in the tracking state (fetcher/state.py); nothing goes to Notion.
  - The first run after the weekly boundary (`publish:` in sources.yaml, Monday
    03:00 Vietnam time) writes each weekly source's top N to Notion.

    python -m fetcher.main                       # normal run
    python -m fetcher.main --dry-run             # fetch + print: no Notion writes, state not saved
    python -m fetcher.main --dry-run --publish   # ... and preview the weekly lists
    python -m fetcher.main --only voz,tinhte     # just these sources
"""
import argparse
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import weekly
from .notion import Notion
from .state import DEFAULT_PATH, State
from .util import to_iso
from .sources import anonyviet, engineerpro, tinhte, vnexpress, voz

# Dispatch by source NAME (the `name:` in sources.yaml) and its `mode:`.
WEEKLY_SOURCES = {"voz": voz, "tinhte": tinhte, "vnexpress": vnexpress}  # collect/publish/after_publish
ALL_SOURCES = {"anonyviet": anonyviet, "engineerpro": engineerpro}        # fetch

FAIL_AFTER_RUNS = 4   # a source failing this many runs in a row (~1 day) fails the workflow


def load_config():
    path = Path(__file__).resolve().parent.parent / "sources.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Target:
    """The weekly Notion database, resolved lazily. Dry runs never write."""

    def __init__(self, state, dry_run):
        self.state, self.dry_run = state, dry_run
        self.notion = Notion() if os.environ.get("NOTION_TOKEN") else None
        if self.notion is None and not dry_run:
            raise SystemExit("NOTION_TOKEN must be set (or use --dry-run)")
        self._db_id = self._index = None

    def index(self):
        """{url: page_id} of the weekly database ({} in a dry run before it exists).
        Not cached on failure, so a Notion hiccup is retried by the next caller."""
        if self._index is None:
            index = {}
            if self.notion is not None:
                db_id = self.notion.weekly_database(self.state, create=not self.dry_run)
                if db_id:
                    index = self.notion.index(db_id)
                self._db_id = db_id
            self._index = index
        return self._index

    def write(self, rows, *, update_existing=True):
        """Returns (created, updated, failed_urls)."""
        index = self.index()
        if self.dry_run:
            return sum(r["url"] not in index for r in rows), 0, []
        return self.notion.write(self._db_id, rows, index, update_existing=update_existing)


def collect_all(cfg, state, target, now):
    """'all' source: write every post that hasn't been written before."""
    name = cfg["name"]
    src = state.source(name)
    fetched = ALL_SOURCES[name].fetch(cfg)
    if not fetched:
        raise RuntimeError("the source returned no posts")
    posts = weekly.within_days(fetched, cfg.get("lookback_days"), now)
    rows = [weekly.post_row(name, p, now) for p in posts if p["url"] not in src["created"]]
    created, _, failed = target.write(rows, update_existing=False)
    for r in rows:
        print(f"    + {r['title'][:90]}")
    if not target.dry_run:
        for r in rows:
            if r["url"] not in failed:   # (rows already in Notion count as written)
                src["created"][r["url"]] = to_iso(now)
    if failed:
        raise RuntimeError(f"{len(failed)} Notion write(s) failed")
    return f"{len(posts)} posts, {created} new"


def _badge(row):
    if row.get("delta") is not None:
        return f"+{row['delta']:,} views this week | {row['score']:,} total"
    if row.get("score") is not None:
        return f"{row['score']:,} comments"
    return ""


def publish(sources, state, target, now, week_start, *, mark):
    """Write each weekly source's top N. Returns (ok, note). On a Notion failure
    nothing is marked, so the next run retries (writes are keyed by URL)."""
    print(f"\n=== weekly lists ({week_start:%Y-%m-%d %H:%M} -> {now:%Y-%m-%d %H:%M} UTC) ===")
    weekly_cfgs = [c for c in sources if c.get("mode") == "weekly_top"]
    rows, ok = [], True
    for cfg in weekly_cfgs:
        name = cfg["name"]
        try:
            part = WEEKLY_SOURCES[name].publish(cfg, state.source(name), now, week_start)
        except Exception:
            traceback.print_exc()
            print(f"[{name}] weekly list FAILED (the other sources still publish)")
            ok = False
            continue
        print(f"[{name}] top {len(part)}:")
        for r in part:
            print(f"    {r['rank']:>2}. {r['title'][:80]}  [{_badge(r)}]")
        rows += part
    try:
        created, updated, failed = target.write(rows)
    except Exception:
        traceback.print_exc()
        return False, "FAILED: couldn't write to Notion (will retry next run)"
    if failed:
        return False, f"FAILED: {len(failed)} Notion write(s) (will retry next run)"
    if mark and not target.dry_run:
        for cfg in weekly_cfgs:
            WEEKLY_SOURCES[cfg["name"]].after_publish(state.source(cfg["name"]), now, week_start)
        state.mark_published(now)
    return ok, f"{len(rows)} rows ({created} new, {updated} updated)"


def summarize(report, publish_note, now, pub_cfg, dry_run):
    zone = ZoneInfo((pub_cfg or {}).get("timezone", weekly.DEFAULTS["timezone"]))
    nxt = weekly.next_boundary(now, pub_cfg).astimezone(zone)
    lines = ["", "=== summary ==="] + [f"{n:12} {status}: {detail}" for n, status, detail in report]
    lines.append(f"{'weekly list':12} {publish_note or 'next after ' + nxt.strftime('%a %d/%m %H:%M') + ' (Vietnam time)'}")
    if dry_run:
        lines.append("(dry run: nothing written to Notion, state not saved)")
    print("\n".join(lines))
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("| Source | Result | Details |\n|---|---|---|\n")
            for n, status, detail in report:
                f.write(f"| {n} | {status} | {detail} |\n")
            f.write(f"\n**Weekly list:** {publish_note or 'next after ' + nxt.strftime('%a %d/%m %H:%M') + ' (Vietnam time)'}\n")


def run(args, now=None):
    now = now or datetime.now(timezone.utc)
    config = load_config()
    pub_cfg = config.get("publish") or {}
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    sources = [c for c in config.get("sources", []) if not only or c["name"] in only]

    state = State.load(args.state)
    state.start_tracking(now)
    target = Target(state, args.dry_run)
    week_start = weekly.week_start(state, now)
    report, ok = [], True

    for cfg in sources:
        name, mode = cfg["name"], cfg.get("mode")
        print(f"\n=== {name} ({mode}) ===")
        try:
            if mode == "all":
                detail = collect_all(cfg, state, target, now)
            elif mode == "weekly_top":
                detail = WEEKLY_SOURCES[name].collect(cfg, state.source(name), now, week_start)
            else:
                raise ValueError(f"unknown mode {mode!r} (expected weekly_top or all)")
            state.record_result(name, True)
            report.append((name, "ok", detail))
        except Exception as exc:
            traceback.print_exc()
            streak = state.record_result(name, False)
            report.append((name, f"FAILED ({streak} run(s) in a row)", str(exc)[:200]))
            if streak >= FAIL_AFTER_RUNS:
                ok = False
        print(f"[{name}] {report[-1][1]}: {report[-1][2]}")

    publish_note = None
    if args.publish or (not only and weekly.publish_due(state, now, pub_cfg)):
        published, publish_note = publish(sources, state, target, now, week_start, mark=not only)
        ok = ok and published

    state.prune(now)
    if not args.dry_run:
        state.save()
    summarize(report, publish_note, now, pub_cfg, args.dry_run)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="VN Digest: collect sources, publish weekly lists to Notion.")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and print only: no Notion writes, state not saved")
    ap.add_argument("--publish", action="store_true",
                    help="publish the weekly lists now instead of waiting for the weekly boundary")
    ap.add_argument("--only", help="comma-separated source names to run (never auto-publishes)")
    ap.add_argument("--state", default=DEFAULT_PATH, help=f"tracking state file (default {DEFAULT_PATH})")
    args = ap.parse_args(argv)
    sys.exit(0 if run(args) else 1)


if __name__ == "__main__":
    main()
