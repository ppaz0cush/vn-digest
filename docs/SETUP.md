# Setup

One-time setup for Notion and the GitHub schedule. After this, the only ongoing
thing you touch is `sources.yaml`.

## 1. Local prerequisites

- Python 3.11+
- `python3 -m venv .venv && .venv/bin/pip install -r fetcher/requirements.txt`
- `.venv/bin/python -m playwright install --with-deps chromium` (Chromium for voz)

## 2. Notion: workspace + integration + page

1. **Create a dedicated workspace** in Notion (sidebar → workspace switcher →
   *Add a workspace*). Notion search is **per-workspace**, so a separate
   workspace keeps the digest's archive out of your main notes' search.

2. **Create an internal integration** at <https://www.notion.so/my-integrations>
   → *New integration* → pick that workspace → copy the **secret**
   (`ntn_...`). This is your `NOTION_TOKEN`.

3. **Create a page** in the workspace (e.g. "VN Digest"), then on that page:
   **••• menu → Connections → add your integration**. (This is what grants the
   token access; without it the API can't see the page.)

4. **The weekly database creates itself.** On its first run the fetcher creates
   **"VN Digest Weekly"** with the right columns (see
   [SOURCES.md](SOURCES.md#notion-columns)), on the page that holds the
   original database (`NOTION_DB_ID`). The original database is only read to
   find that page, and never written to.
   - New install without an original database: set `NOTION_PARENT_PAGE_ID` to
     the page from step 3 instead (the 32-char id in its URL).
   - Or create it by hand: `NOTION_TOKEN=... NOTION_PARENT_PAGE_ID=... python
     setup/notion_init.py`, then set `NOTION_WEEKLY_DB_ID` to the id it prints.

5. **Save your env** in `.env.local` (gitignored):
   ```bash
   export NOTION_TOKEN="ntn_xxx"
   export NOTION_DB_ID="<original database id>"   # read only, to find its page
   # export NOTION_WEEKLY_DB_ID="<id>"             # optional: pin the weekly database
   ```

Test it:
```bash
set -a; . ./.env.local; set +a
.venv/bin/python -m fetcher.main --dry-run --publish   # nothing written
.venv/bin/python -m fetcher.main                       # creates the weekly database + writes
```

## 3. Deploy the schedule (GitHub Actions)

1. Push this repo to GitHub.
2. Add the secrets (the first two already exist in this repo):
   ```bash
   gh secret set NOTION_TOKEN  --body "ntn_xxx"
   gh secret set NOTION_DB_ID  --body "<original DATABASE id>"
   gh secret set NOTION_WEEKLY_DB_ID --body "<id>"   # optional
   ```
   `NOTION_DB_ID` is a **database** id, not a page id. If you only have a page
   (new install), set `NOTION_WEEKLY_DB_ID` from `setup/notion_init.py` instead.
3. That's it. `.github/workflows/fetch.yml` runs 4x a day, installs Chromium
   itself, keeps its tracking file on the `state` branch (created on the first
   run), and publishes the weekly lists after Monday 03:00 Vietnam time.
   Trigger a first run now:
   ```bash
   gh workflow run daily-fetch
   ```
   The workflow grants itself the two permissions it needs: `contents: write`
   (push the `state` branch) and `actions: write` (keep the schedule enabled).

## 4. Set up your Notion views

In **VN Digest Weekly**, add saved views (all native, no code):
- **This week**: filter `Fetched is within the past week`, group by `Source`, sort `Rank` ↑
- **Inbox**: filter `Status is New`
- **Saved**: filter `Status is Saved`

Hide the noisy columns (`URL`, `Prev score`) in your views; see the column
reference in [SOURCES.md](SOURCES.md#notion-columns).

## Notes

- **Rotate the token** if it's ever exposed: regenerate at
  notion.so/my-integrations and update `NOTION_TOKEN` (env + GitHub secret).
- **Keeping the database lean:** pruning is manual; see [RUNNING.md](RUNNING.md#prune-the-button).
- **Don't delete "VN Digest Weekly"** to clean up: the next run would create a
  new, empty one (losing your views and statuses). Prune instead.
- **The original database is left exactly as it is**: nothing reads its rows or
  writes to it any more.
