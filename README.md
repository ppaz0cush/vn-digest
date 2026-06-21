# Vietnamese Tech Digest

A personal, single-user daily digest of top posts from Vietnamese & global tech
sources. A scheduled job fetches each morning into Supabase; a static reader app
(GitHub Pages) lets the one user triage posts (read / skip / save). All free tier.

See [`BUILD_SPEC.md`](BUILD_SPEC.md) for the full design.

## Layout

```
sources.yaml                 # the editable source list (add/remove feeds here)
fetcher/                     # Python fetcher (one module per source strategy)
site/                        # static reader app (HTML/CSS/vanilla JS)
supabase/migrations/         # schema + RLS + grants
setup/                       # provisioning + local-dev scripts
.github/workflows/           # daily cron fetch + Pages deploy
```

## Run it locally (what you asked to see)

**Prereqs:** Docker running, the [`supabase`](https://github.com/supabase/cli)
CLI, Python 3.11+.

```bash
# one-time: python deps
python3 -m venv .venv && .venv/bin/pip install -r fetcher/requirements.txt

# bring up local Supabase + schema + user, fetch live sources, serve the site:
./setup/dev_local.sh --reset
```

Then open **http://localhost:8000** and log in with the credentials printed by
the script (default `hcmc-alibaba@axonactive.com` / `digest-local-2026`, set in
`.env.local`). On later runs drop `--reset` to keep your triage data.

Under the hood `dev_local.sh`:
1. `supabase start` — local Postgres + Auth + PostgREST (Docker).
2. applies `supabase/migrations/` (schema, RLS, grants).
3. creates the single user via the Admin API.
4. runs `python -m fetcher.main` against the **real** live sources, writing to
   the local DB.
5. serves `site/` on :8000.

Run just the fetcher manually:

```bash
set -a; . ./.env.local; set +a
.venv/bin/python -m fetcher.main            # writes to local DB
.venv/bin/python -m fetcher.main --dry-run  # print only, no DB write
.venv/bin/python -m fetcher.main --only tinhte,vnexpress
```

## Sources — current status

| Source | Strategy | Result |
|--------|----------|--------|
| tinhte | RSS `<slash:comments>` | ✅ ranked by comments |
| vnexpress | RSS + comment-count API | ✅ ranked by comments |
| anonyviet | RSS latest | ✅ |
| engineerpro | RSS latest (Substack) | ✅ |
| dailydev | GraphQL `anonymousFeed` | ⚠️ works, but the *anonymous* feed is a frozen "all-time popular" set with stale dates — so the recency window is disabled and it shows a static top-5 by upvotes. Drop the source if you don't want that. |
| spiderum | category page scrape | ✅ but the SSR only renders a few posts; low-volume by nature. |
| voz | headless browser (ranked) → RSS fallback | ✅ **Top by views**, across multiple sub-forums (`forums:` list; `<type>/<slug>.<id>` supports voz's `/s/` nodes). `per_forum_items` caps each forum so a high-traffic one (e.g. Chuyện trò linh tinh) can't crowd out the rest. voz fronts its HTML behind a Cloudflare JS challenge that plain HTTP can't solve, so the fetcher drives a headless **Playwright/Chromium** (which runs the challenge JS), takes the recently-active threads and ranks them by views/replies, excluding pinned megathreads. If Playwright is missing or the challenge isn't solved (possible on some Actions IPs), it auto-falls back to voz RSS as chronological "Latest". Toggle with `use_browser` / `rank_by` in `sources.yaml`. |

A typical run yields ~40–50 items. Each source is wrapped in try/except so one
failure never aborts the run.

## Trending ("Top by what's hot *today*")

Engagement counts on these sites are **cumulative/lifetime** (voz "Views",
article comment totals) — there's no per-day metric exposed. So ranking by the
raw number favors old-but-bumped threads. To get a real "hottest in the last
~24h" signal, the fetcher snapshots each item's score every run and ranks
`trending: true` sources by the **gain since the previous run** (`score_delta`),
not the lifetime total:

- An established thread ranks on *today's* activity (views/comments gained).
- A brand-new item (no prior snapshot) ranks by its current count — its
  engagement is effectively all-recent — so it's never buried on day one.
- The reader shows a `🔥 +1.2k hôm nay` badge next to the cumulative total.

Enabled by default for **voz / tinhte / vnexpress**; toggle per source with
`trending:` in `sources.yaml`. (dailydev stays off — its anonymous feed is
frozen, so its delta is always 0.) The delta is computed against the *previous
fetch*, which is ~24h on the daily cron.

## Write target: Supabase, Notion, or both

The fetcher can write into Supabase (the static reader app) and/or a **Notion
database** (use Notion's own table/filter/sort/views as the reader). Pick with
the `TARGET` env var — `supabase` (default), `notion`, or `both`:

```bash
TARGET=notion python -m fetcher.main   # Notion only
TARGET=both   python -m fetcher.main   # Notion + Supabase (keeps Supabase a hot backup)
```

Items map to TYPED Notion properties (Source = **multi-select**, Label/Status =
select, Score/Δ today = number, Published = date, URL = url), so all of Notion's
filtering and sorting work natively. `Source` carries both the source and (for
voz) the sub-forum, e.g. `["voz", "diem bao"]`, so you can filter by either.
voz titles link to the thread's `/unread` page (jumps to your first unread post
when logged in). On update the fetcher never overwrites `Status`, so your
triage is preserved. **One-time Notion setup:**

1. In a **new, dedicated Notion workspace** (search is per-workspace, so the
   archive won't pollute your main one), create an internal integration at
   <https://www.notion.so/my-integrations> → copy its secret (`NOTION_TOKEN`).
2. Create a page in that workspace and **connect the integration to it**
   (page ••• menu → Connections).
3. Create the database with the correct schema:
   ```bash
   NOTION_TOKEN=ntn_xxx NOTION_PARENT_PAGE_ID=<that page id> \
     python setup/notion_init.py        # prints NOTION_DB_ID
   ```
4. Set `NOTION_TOKEN` + `NOTION_DB_ID` (env locally; GitHub secrets for CI) and
   set the `FETCH_TARGET` repo variable to `notion` or `both`.

`db.py` (Supabase) and `notion.py` share one fetcher, so scraper fixes apply to
both. The Supabase version is tagged `supabase-v1` as a restore point.

## Deploy to the cloud (when happy locally)

Do the one-time manual prereqs in `BUILD_SPEC.md` §4 (Supabase access token,
`gh auth login`), then:

```bash
export SUPABASE_ACCESS_TOKEN=sbp_...   ORG_ID=...   DB_PASSWORD=...
export MY_EMAIL=...   MY_PASSWORD=...
./setup/provision.sh
```

This creates the Supabase project, pushes the schema, disables signups, creates
your account, creates the GitHub repo, sets secrets/variables, and enables
Pages. The daily fetch runs at 00:00 UTC (07:00 ICT); the Pages workflow writes
`config.js` from repo variables and deploys `site/` on push.

## Security model

"Gate the data, not the page." The static shell and the anon key are public, but
RLS means a logged-out visitor can read **nothing** (verified: `items` returns
401 to anon), and a logged-in user can only read/write their **own** status rows.
Only the fetcher's `service_role` key (a GitHub secret, never in the client) can
write `items`.
