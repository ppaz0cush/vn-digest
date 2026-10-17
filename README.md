# VN Digest

A personal, single-user **weekly** digest of Vietnamese & global sources. A
scheduled job collects all week and, every Monday morning, writes the week's top
posts into a **Notion database**: you read and triage them with Notion's own
table / filters / views (web + mobile). All free tier.

What lands in Notion (the **"VN Digest Weekly"** database):

| Source | What | When |
|---|---|---|
| voz (Điểm báo, Chuyện trò linh tinh™, from f17 with love) | the 20 threads that **gained the most views** that week | Monday morning |
| tinhte | the 2 most-commented articles published that week | Monday morning |
| vnexpress (Khoa học công nghệ) | the 2 most-commented articles published that week | Monday morning |
| anonyviet | every new post | as soon as a run sees it |
| engineerpro | every post: its whole archive, then each new one | as soon as a run sees it |

## How it works

```
  GitHub Actions (4x a day)                       Notion: "VN Digest Weekly"
  ┌─────────────────────────────┐                 ┌───────────────────────────┐
  │ python -m fetcher.main      │   Notion API    │ one row per post, typed    │
  │  • read sources.yaml        │ ─────────────▶  │ props: Source/Score/Δ week │
  │  • new posts (every run)    │                 │ Status: New/Read/Saved/... │
  │  • weekly top N (Monday)    │                 └───────────────────────────┘
  └──────────────┬──────────────┘
                 │ view/comment counts seen this week
                 ▼
       `state` branch: state.json   (the tracking file)
```

The fetcher is the only code. Notion is the storage **and** the UI; the tracking
file on the `state` branch remembers the counts between runs (it's needed to
know how many views a thread *gained* this week).

> The original daily database (used before Oct 2026) is **never touched**. The
> fetcher writes only to "VN Digest Weekly", which it creates on its first run
> on the same Notion page.

## Maintenance cheat-sheet 📌

It runs itself: 4 times a day, and the weekly lists appear after **Monday 03:00
Vietnam time** (GitHub runs can start a few hours late). Things you might do:

### Prune (clean up Notion when it feels big)
Archives **all** rows of the weekly database last fetched more than N days ago
(Saved included, so keep anything important elsewhere). The original database is
never touched, and pruned anonyviet/engineerpro posts don't come back. Pick any one:
- **GitHub UI:** Actions tab → **prune-notion** → **Run workflow** → enter days (e.g. `30`).
- **CLI:** `gh workflow run prune-notion -f days=30 -R ppaz0cush/vn-digest`
- **Local:** `set -a; . ./.env.local; set +a && python -m fetcher.prune --days 30`

### Preview or publish early
Actions tab → **daily-fetch** → **Run workflow**:
- tick **publish** + **dry_run** → this week's lists are printed in the run log, nothing is written;
- tick only **publish** → the weekly lists are written now (the next list then covers the time since).

### If it stops
Every scheduled run re-enables the workflow, because GitHub disables schedules in
public repos after 60 days without activity (that happened Oct 3–16, 2026). If it
ever shows as disabled anyway:
- **GitHub UI:** Actions tab → **daily-fetch** → **Enable workflow** button.
- **CLI:** `gh workflow enable daily-fetch -R ppaz0cush/vn-digest`

A source failing for a whole day (4 runs in a row), or a failed Monday publish,
turns the run red, and GitHub emails you. To check it's alive: Actions tab →
**daily-fetch** should show recent green runs; each run's page has a per-source
summary.

## Repo layout

```
sources.yaml              # the source list + weekly publish time: edit this
fetcher/
  main.py                 # entrypoint: collect every run, publish weekly
  weekly.py               # publish timing + shared helpers
  state.py                # the tracking file (state branch / .state/state.json)
  notion.py               # Notion writer (weekly database only)
  prune.py                # manual "clean up old rows" CLI
  http.py  util.py        # shared HTTP session + date helpers
  requirements.txt
  sources/                # ONE module per source (dispatched by name)
    _rss.py               #   shared RSS helper (not a source)
    voz.py tinhte.py vnexpress.py anonyviet.py engineerpro.py
setup/notion_init.py      # optional: create the weekly database by hand
tests/                    # offline tests (pytest)
.github/workflows/
  fetch.yml               # 4x-a-day schedule (+ manual publish / dry run)
  prune.yml               # manual prune button
docs/                     # ← detailed guides (start here)
```

## Documentation

- **[docs/SETUP.md](docs/SETUP.md)**: one-time setup (Notion integration, secrets, views) + deploying on GitHub.
- **[docs/RUNNING.md](docs/RUNNING.md)**: running the fetcher, the weekly publish, the tracking file, prune; env vars; troubleshooting.
- **[docs/SOURCES.md](docs/SOURCES.md)**: exactly how each source is fetched and ranked, and what every Notion column means.
- **[docs/EDITING.md](docs/EDITING.md)**: how to edit a source, add a new one, or remove one.

## Quick start (local)

```bash
python3 -m venv .venv && .venv/bin/pip install -r fetcher/requirements.txt
.venv/bin/python -m playwright install --with-deps chromium   # for voz
.venv/bin/python -m fetcher.main --dry-run --publish          # fetch + preview the weekly lists; no writes
.venv/bin/pip install pytest && .venv/bin/python -m pytest -q # offline tests
```
To write into Notion, do the one-time **[SETUP](docs/SETUP.md)**, then:
```bash
set -a; . ./.env.local; set +a                       # NOTION_TOKEN + NOTION_DB_ID
.venv/bin/python -m fetcher.main
```

> The Supabase + static-site version this started from is in the git history
> (the commits before `cd5ebfb`).
