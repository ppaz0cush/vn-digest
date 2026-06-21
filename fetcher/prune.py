"""Manual prune — your "clean up now" button.

Archives Notion rows older than --days (keeps anything you Saved). Run it
whenever you want; it never runs during a normal fetch.

    set -a; . ./.env.local; set +a        # NOTION_TOKEN + NOTION_DB_ID
    python -m fetcher.prune --days 30

Also exposed as a one-click GitHub Actions workflow (.github/workflows/prune.yml).
"""
import os
import argparse

from . import notion


def main():
    ap = argparse.ArgumentParser(description="Archive old Notion rows (keeps Saved).")
    ap.add_argument("--days", type=int,
                    default=int(os.environ.get("NOTION_PRUNE_DAYS", "30")),
                    help="archive rows older than this many days (default 30)")
    args = ap.parse_args()
    print(f"Pruning Notion rows older than {args.days} days (keeping Saved)…")
    notion.prune(args.days)


if __name__ == "__main__":
    main()
