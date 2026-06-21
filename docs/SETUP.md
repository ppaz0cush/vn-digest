# Setup

One-time setup for the Notion database and the daily cron. After this, the only
ongoing thing you touch is `sources.yaml`.

## 1. Local prerequisites

- Python 3.11+
- `python3 -m venv .venv && .venv/bin/pip install -r fetcher/requirements.txt`
- `.venv/bin/python -m playwright install chromium` (Chromium for the voz fetch)

## 2. Notion: workspace + integration + database

1. **Create a dedicated workspace** in Notion (sidebar → workspace switcher →
   *Add a workspace*). Notion search is **per-workspace**, so a separate
   workspace keeps the digest's archive out of your main notes' search.

2. **Create an internal integration** at <https://www.notion.so/my-integrations>
   → *New integration* → pick that workspace → copy the **secret**
   (`ntn_...`). This is your `NOTION_TOKEN`.

3. **Create a page** in the workspace (e.g. "VN Digest"), then on that page:
   **••• menu → Connections → add your integration**. (This is what grants the
   token access — without it the API can't see the page.)

4. **Create the database** with the correct typed schema. Copy the page id from
   its URL (the 32-char hex string), then:
   ```bash
   NOTION_TOKEN=ntn_xxx NOTION_PARENT_PAGE_ID=<page id> \
     .venv/bin/python setup/notion_init.py
   ```
   It prints `NOTION_DB_ID`. (It creates the properties described in
   [SOURCES.md](SOURCES.md#notion-columns) — don't hand-build them.)

5. **Save your env** in `.env.local` (gitignored):
   ```bash
   export NOTION_TOKEN="ntn_xxx"
   export NOTION_DB_ID="<id from step 4>"
   ```

Test it:
```bash
set -a; . ./.env.local; set +a
.venv/bin/python -m fetcher.main          # writes into Notion
```
Open the database in Notion — you should see the rows.

## 3. Deploy the daily cron (GitHub Actions)

1. Push this repo to GitHub (`gh repo create vn-digest --private --source=. --push`).
2. Add the two secrets:
   ```bash
   gh secret set NOTION_TOKEN  --body "ntn_xxx"
   gh secret set NOTION_DB_ID  --body "<your DATABASE id>"
   ```
   ⚠️ Use the **database** id (printed by `notion_init.py`, step 2.4), NOT the
   parent *page* id. They look identical but are different:
   - the **page** id is in the page URL `.../Articles-Digest-<32 hex>` → that's `NOTION_PARENT_PAGE_ID` (only used to create the DB)
   - the **database** id is what `notion_init.py` prints (or the database's own URL) → that's `NOTION_DB_ID` (a *different* 32-hex string)
   If you pass the page id, every write fails with *"… is a page, not a database."*
3. That's it. `.github/workflows/fetch.yml` runs daily at 22:15 UTC (05:15 ICT)
   and installs Chromium itself. Trigger a first run now:
   ```bash
   gh workflow run daily-fetch
   ```

## 4. Set up your Notion views

In the database, add saved views (all native, no code):
- **Inbox** — filter `Status is New`, sort `Δ today` ↓
- **Hot today** — sort `Δ today` ↓
- **By forum** — filter `Source contains diem bao` (or group by `Source`)
- **Saved** — filter `Status is Saved`

Hide the noisy columns (`URL`, `Prev score`, `Rank`) in your views — see the
column reference in [SOURCES.md](SOURCES.md#notion-columns).

## Notes

- **Rotate the token** if it's ever exposed: regenerate at
  notion.so/my-integrations and update `NOTION_TOKEN` (env + GitHub secret).
- **Keeping the DB lean:** pruning is manual — see [RUNNING.md](RUNNING.md#prune-the-button).
- **Don't delete the whole database** to clean up — it changes `NOTION_DB_ID`
  and wipes your saved views. Use the prune button (or clear rows) instead.
- **Prune deletes everything older than N days** (Saved included) — save
  anything you want to keep outside this database.
