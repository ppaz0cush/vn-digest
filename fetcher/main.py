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

import yaml

from . import rank as rankmod
from .db import upsert_items
from .sources import (
    rss_latest, rss_comments, vnexpress, dailydev, voz, spiderum,
)

STRATEGIES = {
    "rss_latest": rss_latest.fetch,
    "rss_comments": rss_comments.fetch,
    "vnexpress": vnexpress.fetch,
    "dailydev_graphql": dailydev.fetch,
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
    }


def run_source(cfg):
    strategy = cfg.get("strategy")
    fn = STRATEGIES.get(strategy)
    if fn is None:
        print(f"[skip] {cfg.get('name')}: unknown strategy {strategy!r}")
        return []

    raw = fn(cfg)  # source modules may mutate cfg (e.g. dailydev fallback)
    processed = rankmod.process(
        raw,
        rank=cfg.get("rank", "latest"),
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

    all_items = []
    for cfg in config.get("sources", []):
        name = cfg.get("name")
        if only and name not in only:
            continue
        print(f"\n=== {name} ({cfg.get('strategy')}) ===")
        try:
            items = run_source(cfg)
            print(f"[{name}] -> {len(items)} items")
            for it in items:
                badge = f" [{it['score']} {it['score_type']}]" if it.get("score") is not None else ""
                print(f"    {it['rank_position']:>2}. {it['title'][:80]}{badge}")
            all_items.extend(items)
        except Exception:
            print(f"[{name}] FAILED — continuing:")
            traceback.print_exc()

    print(f"\nTOTAL: {len(all_items)} items from {len(config.get('sources', []))} sources")

    if args.dry_run:
        print("(dry-run: not writing to DB)")
        return

    upsert_items(all_items)


if __name__ == "__main__":
    main()
