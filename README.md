# VN Digest

A personal, single-user daily digest of top posts from a set of Vietnamese &
global sources (you choose them — not limited to any one topic). A scheduled job
fetches each morning and writes the items into a **Notion database** — you read
and triage them using Notion's own table / filters / views (web + mobile). All
free tier.

## How it works

```
  GitHub Actions (daily cron)              Notion database (your reader)
  ┌────────────────────────┐               ┌───────────────────────────┐
  │ python -m fetcher.main │   Notion API  │ one row per post, typed    │
  │  • read sources.yaml   │ ───────────▶  │ props: Source/Score/Δ/...  │
  │  • fetch each source   │   create /    │ filter • sort • Status     │
  │  • rank / filter / cap │   update      │ (New/Read/Saved/Skipped)   │
  └────────────────────────┘               └───────────────────────────┘
```

The fetcher is the only code; Notion is the storage **and** the UI.

## Repo layout

```
sources.yaml              # the source list — edit this to add/remove sources
fetcher/
  main.py                 # entrypoint: read config, fetch, rank, write
  rank.py                 # recency window + ranking + cap
  notion.py               # Notion writer + prune()
  prune.py                # manual "clean up old rows" CLI
  http.py  util.py        # shared HTTP session + date helpers
  requirements.txt
  sources/                # ONE module per source (dispatched by name)
    _rss.py               #   shared RSS helper (not a source)
    voz.py tinhte.py vnexpress.py anonyviet.py spiderum.py engineerpro.py
setup/notion_init.py      # one-time: create the Notion DB with the right schema
.github/workflows/
  fetch.yml               # daily cron
  prune.yml               # manual prune button
docs/                     # ← detailed guides (start here)
```

## Documentation

- **[docs/SETUP.md](docs/SETUP.md)** — one-time setup (Notion workspace, integration, database) + deploying the daily cron on GitHub.
- **[docs/RUNNING.md](docs/RUNNING.md)** — running the fetcher and the prune button (locally and in CI), env vars.
- **[docs/SOURCES.md](docs/SOURCES.md)** — exactly how each source is fetched, and what every Notion column means.
- **[docs/EDITING.md](docs/EDITING.md)** — how to edit a source, add a new one, or remove one.

## Quick start (local)

```bash
python3 -m venv .venv && .venv/bin/pip install -r fetcher/requirements.txt
.venv/bin/python -m playwright install chromium      # for voz
.venv/bin/python -m fetcher.main --dry-run           # fetch + print, no writes
```
To write into Notion, do the one-time **[SETUP](docs/SETUP.md)**, then:
```bash
set -a; . ./.env.local; set +a                       # NOTION_TOKEN + NOTION_DB_ID
.venv/bin/python -m fetcher.main
```

> The Supabase + static-site version this started from is preserved at the git
> tag `supabase-v1` if it's ever needed.
