"""Manual prune: your "clean up now" button for the weekly database.

Archives every row of "VN Digest Weekly" last fetched more than --days ago
(Saved rows too: keep anything important elsewhere). Archived rows go to
Notion's trash. The original database is never touched. Posts from 'all'
sources (anonyviet, engineerpro) that you prune don't come back.

    set -a; . ./.env.local; set +a        # NOTION_TOKEN (+ NOTION_DB_ID)
    python -m fetcher.prune --days 30

Also a one-click GitHub Actions workflow (.github/workflows/prune.yml).
"""
import argparse
import os

from .notion import Notion
from .state import DEFAULT_PATH, State


def main():
    ap = argparse.ArgumentParser(description="Archive weekly-digest rows older than --days.")
    ap.add_argument("--days", type=int, default=int(os.environ.get("NOTION_PRUNE_DAYS", "30")),
                    help="archive rows last fetched more than this many days ago (default 30)")
    ap.add_argument("--state", default=DEFAULT_PATH, help="tracking state file (to find the database)")
    args = ap.parse_args()
    if args.days < 1:
        raise SystemExit("--days must be at least 1")

    notion = Notion()
    db_id = notion.weekly_database(State.load(args.state), create=False)
    if not db_id:
        raise SystemExit("no 'VN Digest Weekly' database found; nothing to prune")
    print(f"Archiving weekly-digest rows last fetched more than {args.days} days ago...")
    print(f"[notion] archived {notion.archive_older_than(db_id, args.days)} rows")


if __name__ == "__main__":
    main()
