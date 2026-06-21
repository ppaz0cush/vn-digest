# Running

Assumes you've done [SETUP.md](SETUP.md). Load your env first:

```bash
set -a; . ./.env.local; set +a      # exports NOTION_TOKEN + NOTION_DB_ID
```

## Fetch

```bash
.venv/bin/python -m fetcher.main
```
Reads `sources.yaml`, fetches every source, ranks/filters, and upserts into
Notion (creates new rows, updates existing ones by URL — never touching your
`Status`).

Useful flags:

| Command | What it does |
|---|---|
| `python -m fetcher.main --dry-run` | Fetch and print, **no writes**. Works without Notion creds. |
| `python -m fetcher.main --only voz,tinhte` | Run just those sources. |
| `python -m fetcher.main --dry-run --only voz` | Debug one source quickly. |

The run prints a per-source summary; each source is wrapped in try/except, so
one failing source (e.g. voz blocked) logs and the rest still run.

## Prune (the button)

Cleanup is **manual** — it never runs during a fetch. It archives **all** rows
older than N days (no exceptions — Saved rows are deleted too, so save anything
you want to keep elsewhere). Archived rows go to Notion's trash.

**Locally:**
```bash
.venv/bin/python -m fetcher.prune --days 30
```
(`--days` defaults to `NOTION_PRUNE_DAYS` or 30.)

**As a click in GitHub:** Actions tab → **prune-notion** → *Run workflow* → enter
days. Or:
```bash
gh workflow run prune-notion -f days=30
```

## The daily cron

`.github/workflows/fetch.yml` runs `python -m fetcher.main` daily at 22:15 UTC
(05:15 Asia/Ho_Chi_Minh) and installs Chromium for the voz fetch. Run it
on demand anytime with `gh workflow run daily-fetch` or the *Run workflow*
button. (GitHub may delay scheduled runs by 5–30 min.)

> **Why a daily cron and not on-demand?** The source feeds are ephemeral — they
> only expose their latest ~20 items. The cron captures each day's posts before
> they age out of the feeds; if you only fetched when you visited, you'd only
> ever get "today," never the days you missed.

## Environment variables

| Var | Used by | Notes |
|---|---|---|
| `NOTION_TOKEN` | fetch, prune | Integration secret (`ntn_...`). GitHub secret in CI. |
| `NOTION_DB_ID` | fetch, prune | Target database id. GitHub secret in CI. |
| `NOTION_PARENT_PAGE_ID` | `setup/notion_init.py` | Only for the one-time DB creation. |
| `NOTION_PRUNE_DAYS` | prune | Default for `--days` (optional). |

## Troubleshooting

- **voz returns 0 / "browser path failed"** — Cloudflare blocked the headless
  browser from that IP; the fetcher falls back to voz RSS automatically. Skim the
  Action log; if it persists from GitHub's datacenter IP, voz will show as
  "Latest" instead of "Top".
- **`NOTION_TOKEN and NOTION_DB_ID must be set`** — you didn't source
  `.env.local` (or the GitHub secrets aren't set).
- **Nothing in Notion but the run said "created N"** — make sure the integration
  is connected to the page/database (SETUP step 3) and you're using the right
  `NOTION_DB_ID`.
