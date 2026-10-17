# Running

Assumes you've done [SETUP.md](SETUP.md). Load your env first:

```bash
set -a; . ./.env.local; set +a      # exports NOTION_TOKEN + NOTION_DB_ID
```

## Fetch

```bash
.venv/bin/python -m fetcher.main
```
Each run:
1. **'all' sources** (anonyviet, engineerpro): posts not written before are
   created in Notion. A post is written once, so pruning it doesn't bring it back.
2. **Weekly sources** (voz, tinhte, vnexpress): view/comment counts are recorded
   in the tracking file. Nothing is written to Notion.
3. **Weekly publish:** the first run after Monday 03:00 Vietnam time (the
   `publish:` block in `sources.yaml`) writes each weekly source's top N. Rows
   are keyed by URL: a thread already in Notion is updated, and your `Status` is
   never touched.

Useful flags:

| Command | What it does |
|---|---|
| `python -m fetcher.main --dry-run` | Fetch and print, **no Notion writes**, tracking file not saved. Works without Notion creds. |
| `python -m fetcher.main --dry-run --publish` | ... and print what this week's lists would be. |
| `python -m fetcher.main --publish` | Publish the weekly lists now instead of waiting for Monday. |
| `python -m fetcher.main --only voz,tinhte` | Run just those sources (never auto-publishes). |
| `python -m fetcher.main --state path.json` | Use another tracking file (default `.state/state.json`). |

The run prints a per-source summary (also shown on the GitHub run page). Each
source is wrapped in try/except, so one failing source logs and the rest still
run.

## The schedule

`.github/workflows/fetch.yml` runs at 02:15, 08:15, 14:15 and 20:15 UTC (09:15,
15:15, 21:15, 03:15 Vietnam time), so the 03:15 Monday run publishes. GitHub
may start scheduled runs late (hours, sometimes), and a late or skipped run just
means the next run publishes. Manual runs: Actions tab → **daily-fetch** → *Run
workflow*, with two tick boxes:
- **publish**: publish the weekly lists now;
- **dry_run**: print only (no Notion writes, tracking file not saved).

Or from the CLI: `gh workflow run daily-fetch -f publish=true -f dry_run=true`.

**Alerting:** a run fails (red; GitHub emails you) only when a source has failed
4 runs in a row (about a day), or the weekly publish couldn't be written. A
failed publish is retried by the next run.

**Keepalive:** each scheduled run re-enables the workflow, because GitHub
disables schedules in public repos after 60 days without activity.

> **Why collect all week?** The feeds only show their latest items (tinhte about
> a day), and voz shows lifetime view totals only. Counting views *gained* this
> week, or finding the week's most-commented articles, needs counts recorded
> along the way.

## The tracking file

A small JSON file with everything the weekly ranking needs: view/comment counts
seen this week, when the last list went out, which posts were already written,
the weekly database's id, and per source its failure streak, `last_ok_at` and
`last_error` (time + message). In CI it lives on the repo's **`state` branch**
(`state.json`, a single commit replaced every run, so the branch never grows).
The workflow copies it to `.state/state.json` before a run and pushes it back
after. You can open it on GitHub to see why something ranked, or why a source
failed, without reading the run logs.

Locally the fetcher uses its own `.state/state.json` (gitignored). It's
separate from CI's, but rows are keyed by URL, so local runs never duplicate
anything.

If the file is ever lost, nothing breaks: the next run starts fresh and the
following weekly list is partial (older voz threads only count views from
when they were first seen again).

## Prune (the button)

Cleanup is **manual**. It archives **all** rows of "VN Digest Weekly" last
fetched more than N days ago (Saved included, so save anything you want to keep
elsewhere). Archived rows go to Notion's trash. The original database is never
touched.

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

## Environment variables

| Var | Used by | Notes |
|---|---|---|
| `NOTION_TOKEN` | fetch, prune | Integration secret (`ntn_...`). GitHub secret in CI. |
| `NOTION_DB_ID` | fetch, prune | The **original** database: read once to find its page (to create the weekly one next to it); never written. GitHub secret. |
| `NOTION_WEEKLY_DB_ID` | fetch, prune | Optional: pin the weekly database instead of finding/creating it. |
| `NOTION_PARENT_PAGE_ID` | fetch, `setup/notion_init.py` | Optional: page to create the weekly database in (new installs). |
| `NOTION_PRUNE_DAYS` | prune | Default for `--days` (optional). |
| `VN_DIGEST_STATE` | fetch, prune | Tracking file path (default `.state/state.json`). |

## Tests

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q
```
Offline (no network): publish timing, the tracking file, voz parsing (against a
saved real page) and weekly-gain math, the Notion guard, and whole runs against
a fake Notion.

## Troubleshooting

- **voz failed / "could not load ..."**: Cloudflare blocked the headless
  browser. Each page is retried in a fresh browser session; a run where voz
  fails just records nothing, and the weekly list uses the counts from the
  other runs. After 4 failed runs in a row the run turns red.
- **engineerpro failed**: Substack blocks GitHub's servers, so it depends on
  the browser / Jina Reader fallbacks (see [SOURCES.md](SOURCES.md)). The error
  of each method is in `last_error` in `state.json` on the `state` branch.
- **`NOTION_TOKEN must be set`**: you didn't source `.env.local` (or the GitHub
  secrets aren't set). Use `--dry-run` to test without Notion.
- **"refusing to touch the original database"**: `NOTION_WEEKLY_DB_ID` is set
  to the original database's id. Unset it (the weekly database is found or
  created automatically).
- **Can't find the new database:** it's on the same Notion page as the original
  one, titled "VN Digest Weekly". The first run's log prints its URL.
