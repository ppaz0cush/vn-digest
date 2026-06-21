"""Fetcher entrypoint.

Reads sources.yaml, dispatches each source to its strategy module, normalizes
to the `items` schema, ranks/filters/caps, and UPSERTs into Supabase.

Run locally:
    SUPABASE_URL=http://localhost:54321 \
    SUPABASE_SERVICE_ROLE_KEY=<local service_role> \
    python -m fetcher.main

Add --dry-run to print results without writing to the DB.
"""
import os
import sys
import argparse
import traceback
from pathlib import Path
from datetime import datetime, timezone

import os
import yaml

from . import rank as rankmod
from . import db as supabase_sink
from . import notion as notion_sink
from .sources import (
    rss_latest, rss_comments, vnexpress, voz, spiderum,
)


def get_sinks():
    """Pick write targets from the TARGET env var: 'supabase' (default),
    'notion', or 'both'. For 'both', Notion is primary (drives the deltas) so
    switching to 'notion' later keeps the trend history continuous. Returns a
    list of modules each exposing fetch_prev_scores() + upsert_items()."""
    target = os.environ.get("TARGET", "supabase").lower()
    if target == "notion":
        return [notion_sink]
    if target == "both":
        return [notion_sink, supabase_sink]
    return [supabase_sink]

STRATEGIES = {
    "rss_latest": rss_latest.fetch,
    "rss_comments": rss_comments.fetch,
    "vnexpress": vnexpress.fetch,
    "voz_html": voz.fetch,
    "spiderum": spiderum.fetch,
}

ITEM_COLUMNS = (
    "url", "source", "title", "source_detail", "published_at",
    "score", "score_type", "rank_label", "rank_position", "metadata",
)


def load_config():
    path = Path(__file__).resolve().parent.parent / "sources.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize(item, cfg):
    """Project a source item dict onto the DB columns."""
    return {
        "url": item["url"],
        "source": cfg["name"],
        "title": item["title"][:1000],
        "source_detail": item.get("source_detail"),
        "published_at": item.get("published_at"),
        "score": item.get("score"),
        "score_type": item.get("score_type"),
        "rank_label": cfg.get("label", "Latest"),
        "rank_position": item.get("rank_position"),
        "metadata": item.get("metadata"),
        "prev_score": item.get("prev_score"),
        "score_delta": item.get("score_delta"),
        "last_score_at": item.get("last_score_at"),
        "prev_score_at": item.get("prev_score_at"),
    }


def apply_deltas(raw, prev_scores, run_ts):
    """Annotate each item with its score delta vs. the previous run and a
    `_trend` value used for trending ranking.

    score_delta = score - prev_score   (true gain since last run; may be null)
    _trend      = the value we rank 'trending' sources by:
        - if we have a previous score: the gain since then (>=0), so an old
          thread bumped today ranks on TODAY's activity, not its lifetime total;
        - if this is the first time we see the item: its current score (a new
          thread's count is effectively all-recent), so new hot items aren't
          buried on day one.
    """
    for it in raw:
        score = it.get("score")
        prev = prev_scores.get(it.get("url"))
        prev_score = prev["score"] if prev else None
        it["last_score_at"] = run_ts   # "Fetched" time — set for EVERY item
        if score is not None and prev_score is not None:
            it["prev_score"] = prev_score
            it["prev_score_at"] = prev["last_score_at"]
            it["score_delta"] = score - prev_score
            it["_trend"] = max(score - prev_score, 0)
        else:
            it["_trend"] = score if score is not None else None
    return raw


def run_source(cfg, prev_scores, run_ts):
    strategy = cfg.get("strategy")
    fn = STRATEGIES.get(strategy)
    if fn is None:
        print(f"[skip] {cfg.get('name')}: unknown strategy {strategy!r}")
        return []

    raw = fn(cfg)  # source modules may mutate cfg (e.g. dailydev fallback)
    raw = apply_deltas(raw, prev_scores, run_ts)

    # 'trending' sources rank by gain-since-last-run; others keep their config.
    rank = cfg.get("rank", "latest")
    if cfg.get("trending") and rank == "top":
        rank = "trending"

    processed = rankmod.process(
        raw,
        rank=rank,
        window_hours=cfg.get("window_hours", 168),
        max_items=cfg.get("max_items", 10),
        tiebreak=cfg.get("tiebreak"),
    )
    # Dedupe on url within this source (stable, keep first).
    seen, deduped = set(), []
    for it in processed:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        deduped.append(it)
    return [normalize(it, cfg) for it in deduped]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and print, but do not write to the DB")
    ap.add_argument("--only", help="comma-separated source names to run")
    args = ap.parse_args()

    config = load_config()
    only = set(s.strip() for s in args.only.split(",")) if args.only else None

    sinks = get_sinks()
    print(f"write target(s): {', '.join(s.__name__.split('.')[-1] for s in sinks)}")

    run_ts = datetime.now(timezone.utc).isoformat()
    # Deltas come from the primary sink's previous snapshot.
    prev_scores = sinks[0].fetch_prev_scores()  # {url: {score, last_score_at}}; {} if unreachable
    print(f"loaded {len(prev_scores)} previous scores for delta ranking")

    all_items = []
    for cfg in config.get("sources", []):
        name = cfg.get("name")
        if only and name not in only:
            continue
        print(f"\n=== {name} ({cfg.get('strategy')}) ===")
        try:
            items = run_source(cfg, prev_scores, run_ts)
            print(f"[{name}] -> {len(items)} items")
            for it in items:
                if it.get("score_delta") is not None:
                    badge = f" [+{it['score_delta']} {it['score_type']} today | {it['score']} total]"
                elif it.get("score") is not None:
                    badge = f" [{it['score']} {it['score_type']}]"
                else:
                    badge = ""
                print(f"    {it['rank_position']:>2}. {it['title'][:80]}{badge}")
            all_items.extend(items)
        except Exception:
            print(f"[{name}] FAILED — continuing:")
            traceback.print_exc()

    print(f"\nTOTAL: {len(all_items)} items from {len(config.get('sources', []))} sources")

    if args.dry_run:
        print("(dry-run: not writing)")
        return

    for sink in sinks:
        sink.upsert_items(all_items)


if __name__ == "__main__":
    main()
