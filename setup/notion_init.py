"""Create the "VN Digest Weekly" Notion database by hand (optional).

You normally don't need this: the fetcher creates the database automatically on
its first run, on the same Notion page as the original database. Use this only
to create it somewhere else:

    NOTION_TOKEN=ntn_xxx NOTION_PARENT_PAGE_ID=<page id> python setup/notion_init.py

then save the printed id as NOTION_WEEKLY_DB_ID (in .env.local and as a GitHub
secret). The parent page id is the 32-char id in the page URL; the integration
must be connected to that page (••• menu -> Connections).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetcher.notion import Notion  # noqa: E402

parent = os.environ["NOTION_PARENT_PAGE_ID"].replace("-", "")
db_id = Notion(original_db_id="").create_database(parent)
print("\nNOTION_WEEKLY_DB_ID =", db_id)
print("\nNext: put it in .env.local and run:  gh secret set NOTION_WEEKLY_DB_ID --body", db_id)
