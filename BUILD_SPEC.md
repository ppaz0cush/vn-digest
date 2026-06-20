# Vietnamese Tech Digest — Build Specification

> Hand this file to Claude Code (Claude CLI). It describes a complete, free,
> automated daily tech-news digest. **Goal: build everything as code. Minimize
> manual dashboard clicking** — use the Supabase CLI + GitHub CLI for all
> provisioning. The only unavoidable manual steps are listed in §4.

---

## 1. What this is

A personal, single-user daily digest of top posts from several Vietnamese and
global tech sources. A scheduled job fetches the day's posts every morning and
writes them to a database; a static website reads from that database and lets
the one user (me) triage posts with read/skip/save statuses. The whole thing
runs on free tiers.

- **One user only.** Public signups disabled; exactly one account exists.
- **~20–35 posts/day**, ranked or latest depending on source.
- **Reddit is NOT automated** — I browse it manually. Do not build anything for it.

---

## 2. Tech stack (locked)

| Layer | Choice | Notes |
|-------|--------|-------|
| Hosting (site) | **GitHub Pages** | Serves the static reader app |
| Scheduler | **GitHub Actions** (cron) | Runs the fetcher daily |
| Fetcher | **Python 3.11+** | `requests`, `feedparser`, `beautifulsoup4`, `lxml`, `python-dateutil` |
| Frontend | **Static HTML + CSS + vanilla JS** | No framework. Clean, minimal news-reader UI |
| Database + Auth | **Supabase** (free tier) | Postgres + Row-Level Security + Supabase Auth |
| Provisioning | **Supabase CLI + GitHub CLI** | All infra as code (see §12) |

Everything is free. No paid APIs (Blind and Threads were deliberately excluded —
see §15).

---

## 3. Architecture

```
            ┌──────────────────────────┐
  cron      │  GitHub Actions (daily)  │
  00:00 UTC │  Python fetcher          │
            │  - reads sources.yaml    │
            │  - fetches each source   │
            │  - ranks / filters / caps│
            │  - UPSERT items → Supabase (service_role key)
            └────────────┬─────────────┘
                         │ writes items
                         ▼
                 ┌───────────────┐
                 │   Supabase    │  items (shared) + item_status (per-user) + user_state
                 │  Postgres+RLS │
                 │  + Auth       │
                 └───────▲───────┘
                         │ reads items + own statuses (anon key + login)
            ┌────────────┴─────────────┐
            │  GitHub Pages (static)   │
            │  HTML/CSS/JS reader app  │  ← I log in, triage posts
            └──────────────────────────┘
```

Key point: **the daily job only writes to the DB.** The static site is fixed
(deployed on push) and shows fresh data because it queries Supabase on load.
The site is NOT regenerated daily.

---

## 4. Manual prerequisites (the ONLY clicking required)

Everything else in this spec is scripted. A human must do just these once:

1. **Create a Supabase account** at supabase.com, then generate a **personal
   access token** (Account → Access Tokens). Export it:
   `export SUPABASE_ACCESS_TOKEN=sbp_xxx`
   This token lets the CLI/Management API create the project, push schema,
   configure auth, and read the API keys — no further dashboard use needed.
2. **Authenticate GitHub CLI**: `gh auth login` (or set a PAT).
3. **Pick two inputs** (not clicks): a database password and a region for the
   Supabase project; my email + a password for the single account.

After this, run the setup in §12 and everything provisions from the terminal.

---

## 5. Repository layout

```
vn-tech-digest/
├─ sources.yaml                 # the editable source list (add/remove forums here)
├─ fetcher/
│  ├─ main.py                   # entrypoint: read config, fetch all, upsert
│  ├─ sources/                  # one module per fetch strategy
│  │  ├─ rss_comments.py        # Tinhte (comment counts in RSS)
│  │  ├─ rss_latest.py          # AnonyViet, EngineerPro
│  │  ├─ vnexpress.py           # RSS + per-article comment API
│  │  ├─ dailydev.py            # GraphQL (RSS fallback)
│  │  ├─ voz.py                 # HTML scrape of sorted sub-forum listing
│  │  └─ spiderum.py            # category feed
│  ├─ rank.py                   # recency filter + sort + cap helpers
│  ├─ db.py                     # Supabase upsert (service_role)
│  └─ requirements.txt
├─ site/                        # static reader app (served by Pages)
│  ├─ index.html
│  ├─ app.js
│  └─ style.css
├─ supabase/
│  └─ migrations/
│     └─ 0001_init.sql          # schema + RLS (see §8)
├─ setup/
│  ├─ provision.sh              # Supabase + GitHub provisioning (see §12)
│  └─ create_user.py            # create the single account via admin API
└─ .github/workflows/
   ├─ fetch.yml                 # daily cron (see §11)
   └─ pages.yml                 # deploy site/ to Pages on push (optional; or use built-in Pages)
```

---

## 6. Source configuration — `sources.yaml`

This file IS the "add/delete forums" mechanism. To add a voz sub-forum or
another feed, edit this file and commit. The fetcher reads it on every run.

```yaml
# Recency windows are set to RECOMMENDED defaults:
#   - high-volume + ranked sources use a SHORT window (~previous day) so you get
#     TODAY's most-discussed, not week-old posts (comment/upvote counts accumulate
#     over time, so a long window surfaces stale items).
#   - low-volume "get all" sources use a LONG window (7 days) so the section is
#     not empty on days they didn't post.
# Adjust window_hours per source freely.

sources:
  - name: voz
    strategy: voz_html
    # TODO(human): set the sub-forum(s) you want. Find the slug.id by opening the
    # sub-forum on voz.vn and copying it from the URL, e.g. voz.vn/f/<slug>.<id>/
    # The generic site-wide feed is a noisy firehose — target tech/IT sections.
    forums:
      - "REPLACE_WITH_SUBFORUM_SLUG.ID"   # e.g. "diem-bao.33"  (placeholder — verify)
    rank: top
    rank_by: views          # 'views' is harder to game than 'replies' (bumping)
    window_hours: 48        # threads ACTIVE in the last 48h
    max_items: 10
    label: "Top"

  - name: dailydev
    strategy: dailydev_graphql
    rank: top
    rank_by: upvotes
    window_hours: 168       # last 7 days
    max_items: 5
    label: "Top"

  - name: tinhte
    strategy: rss_comments
    url: "https://tinhte.vn/rss"
    rank: top
    rank_by: comments       # comment count is in the RSS via <slash:comments>
    tiebreak: published_desc
    window_hours: 48
    max_items: 10
    label: "Top"

  - name: vnexpress
    strategy: vnexpress
    url: "https://vnexpress.net/rss/so-hoa.rss"
    rank: top
    rank_by: comments       # via the comment-count API (RSS has no counts)
    tiebreak: published_desc
    window_hours: 48
    max_items: 10
    label: "Top"

  - name: anonyviet
    strategy: rss_latest
    url: "https://anonyviet.com/feed/"
    rank: latest
    window_hours: 168       # 7 days (low volume)
    max_items: 10
    label: "Latest"

  - name: spiderum
    strategy: spiderum
    # CONFIRMED scope: the "Quan điểm - Tranh luận" category only.
    category_url: "https://spiderum.com/danh-muc/quan-diem-tranh-luan?sort=new&page_idx=1"
    post_url_pattern: "https://spiderum.com/bai-dang/{slug}"
    rank: latest
    window_hours: 168
    max_items: 10
    label: "Latest"

  - name: engineerpro
    strategy: rss_latest
    url: "https://engineerprovn.substack.com/feed"
    rank: latest
    window_hours: 336       # 14 days — they post only ~2-3×/week
    max_items: 10
    label: "Latest"
```

---

## 7. Per-source fetch logic

All sources: dedupe on `url` (the stable primary key). Always capture
`title`, `url`, `published_at`. Apply the source's `window_hours` recency
filter, then rank/sort, then cap at `max_items`. Tag each item with the
source's `label` ("Top" / "Latest") — **labels must be honest**; do not call a
chronological feed "Top".

**voz (`voz_html`)** — Its RSS is chronological, so to rank by engagement you
must scrape a *sorted* XenForo thread listing per configured sub-forum:
`https://voz.vn/f/<slug>.<id>/?order=view_count&direction=desc` (also try
`order=reply_count`). Parse thread rows for title, thread URL, view count,
reply count, and last-activity time. Filter to threads active within
`window_hours`, sort by `rank_by` (default views), cap. Store the engagement
number in `items.score` and `score_type='views'` (or 'replies_views').
⚠ Verify the sorted-listing URL and row selectors work for the chosen sub-forum
before relying on it — confirm a real `<slug>.<id>` first.

**dailydev (`dailydev_graphql`)** — POST to `https://api.daily.dev/graphql`
(unauthenticated). Verified working query shape:
```graphql
query { anonymousFeed(first: 20, ranking: POPULARITY) {
  edges { node { title permalink numUpvotes numComments createdAt readTime source { name } } } } }
```
Note field is `numUpvotes` (not `upvotes`). The anonymous feed may return
older `createdAt` values, so **filter to last 7 days client-side**, sort by
`numUpvotes`, take 5. `score=numUpvotes`, `score_type='upvotes'`.
**Fallback:** if GraphQL breaks (it is an internal/unofficial API), fall back to
the official RSS (`https://api.daily.dev/rss`) as a chronological "Latest".

**tinhte (`rss_comments`)** — Parse the RSS. Comment count is in each item as
`<slash:comments>` (namespace `http://purl.org/rss/1.0/modules/slash/`).
Filter to `window_hours` by `pubDate`, sort by comment count desc, tiebreak by
`pubDate` desc, take 10. `score=<comments>`, `score_type='comments'`.

**vnexpress (`vnexpress`)** — Parse the RSS for items; extract the numeric
article ID from each link (the digits before `.html`). **Filter to
`window_hours` FIRST** (to limit API calls), then for each remaining article
call the public comment-count API:
`https://usi-saas.vnexpress.net/index/get?objectid=<ID>&objecttype=1&siteid=1000000&offset=0&limit=1`
Read `data.totalitem` as the comment count. Sort desc, tiebreak `pubDate`, take
10. `score=totalitem`, `score_type='comments'`. (Verified: returns
`{"error":0,...,"data":{"total":N,"totalitem":M,...}}` without login.)

**anonyviet / engineerpro (`rss_latest`)** — Parse the RSS, filter to
`window_hours` by `pubDate`, sort by `pubDate` desc, take up to `max_items`.
`score=null`, `label='Latest'`.

**spiderum (`spiderum`)** — Fetch the configured `category_url`. The category
page is a Next.js app; extract posts either from a discoverable category JSON
API (inspect the page's network calls / `__NEXT_DATA__` embedded JSON) or by
parsing the rendered listing. Build each post URL from `post_url_pattern` +
slug. Filter to `window_hours` by post date, sort by date desc, take up to 10.
If engagement (point/views/comments) is available in the payload, store it in
`score`/`score_type`; otherwise leave null. `label='Latest'`.

---

## 8. Database schema — `supabase/migrations/0001_init.sql`

```sql
-- ITEMS: the fetched digest posts (global/shared; written only by the fetcher)
create table if not exists items (
  url           text primary key,            -- stable unique key: dedup + read-state anchor
  source        text not null,               -- 'voz' | 'tinhte' | ...
  title         text not null,
  source_detail text,                        -- forum name / author / sub-source
  published_at  timestamptz,
  fetched_at    timestamptz not null default now(),
  score         integer,                     -- engagement count (comments/upvotes/views)
  score_type    text,                        -- 'comments' | 'upvotes' | 'replies_views' | null
  rank_label    text not null,               -- 'Top' | 'Latest'
  rank_position integer,                      -- order within its source for that run
  metadata      jsonb
);
create index if not exists items_published_idx on items (published_at desc);
create index if not exists items_source_idx     on items (source);

-- ITEM_STATUS: the single user's triage. Absence of a row == "new/unread".
create table if not exists item_status (
  user_id    uuid not null references auth.users(id) on delete cascade,
  item_url   text not null references items(url)     on delete cascade,
  status     text not null check (status in ('read','skipped','saved')),
  updated_at timestamptz not null default now(),
  primary key (user_id, item_url)
);

-- USER_STATE: last visit time, for "new since I last looked".
create table if not exists user_state (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  last_visit_at timestamptz
);

-- ROW LEVEL SECURITY ---------------------------------------------------------
alter table items       enable row level security;
alter table item_status enable row level security;
alter table user_state  enable row level security;

-- items: any authenticated user may READ; no write policy => only the
-- service_role key (used by the fetcher) can insert/update, bypassing RLS.
create policy items_read on items
  for select to authenticated using (true);

-- item_status: a user may only see and modify their OWN rows.
create policy status_select on item_status for select to authenticated using (auth.uid() = user_id);
create policy status_insert on item_status for insert to authenticated with check (auth.uid() = user_id);
create policy status_update on item_status for update to authenticated using (auth.uid() = user_id);
create policy status_delete on item_status for delete to authenticated using (auth.uid() = user_id);

-- user_state: same, own row only.
create policy state_select on user_state for select to authenticated using (auth.uid() = user_id);
create policy state_insert on user_state for insert to authenticated with check (auth.uid() = user_id);
create policy state_update on user_state for update to authenticated using (auth.uid() = user_id);
```

---

## 9. The fetcher (Python) — behavioral spec

`fetcher/main.py` should:

1. Load `sources.yaml`.
2. For each enabled source, dispatch to its `strategy` module and collect items.
   Wrap each source in try/except so one failing source never aborts the run;
   log failures and continue.
3. Normalize every item to the `items` schema columns (§8). `url` is required
   and is the dedup key.
4. Set `rank_position` per source by final sort order.
5. **Upsert** all items into Supabase `items` using the **service_role** key
   (`on conflict (url) do update` to refresh score/title, or `do nothing` to
   keep first-seen — prefer updating `score` and `title`, keeping original
   `fetched_at`). This makes the table a growing, deduplicated archive.
6. Use a custom HTTP User-Agent (e.g. `vn-tech-digest/1.0`) for all requests.

Connect to Supabase via the `supabase` Python client or direct REST with the
service_role key. Read `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from env
(provided by GitHub Actions secrets).

---

## 10. The website (`site/`) — spec

A clean, minimal, fast news-reader. Vanilla JS using the Supabase JS client
(loaded from CDN). The **anon key is safe to embed in client JS** — it is
designed to be public and is protected by RLS; do not try to hide it.

**Auth**
- On load, require a Supabase Auth session. If not logged in, show a simple
  email + password login form. (Signups are disabled server-side; only my
  account works — see §13.)

**Data load (after login)**
- Query `items` (RLS allows read) for the current digest — default view: items
  with `published_at` within the last ~48h, ordered by `source` then
  `rank_position`. Provide an "Archive" view that queries all items with a text
  search on `title`.
- Query the user's `item_status` rows and `user_state.last_visit_at`.
- Compute **"new since last visit"**: any item with `published_at >
  last_visit_at` gets a "new" badge. After loading, update `last_visit_at` to
  now (upsert into `user_state`).

**Render**
- Group by source, with a header per source showing its honest label
  ("Top" / "Latest"). Within a group, preserve `rank_position` order.
- Each card: title (links to `url`, opens in new tab), source/source_detail,
  relative published time ("3h ago" from `published_at`), and the engagement
  badge when `score` is present (e.g. "💬 19" for comments, "▲ 766" for
  upvotes, "👁 1.2k" for views).

**Triage (the core interaction)**
- Per-card statuses: **New** (default, no row) → **Skip** / **Save** / **Read**.
  One tap each; write the status to `item_status` immediately (upsert).
- **Click-through auto-marks Read**: clicking the title link sets status=read.
- A **"Hide read"** toggle (inbox-zero): when on, read AND skipped items are
  hidden, so the list shrinks as I triage; empty list = done.
- A **"Mark all as read"** button for busy days.
- Marking must be lower-friction than reading — favor one-tap buttons (or
  swipe on mobile); no multi-step menus.

**Aesthetic**
- Minimal, lots of whitespace, legible Vietnamese text, fast. Read/skipped
  cards visually de-emphasized (greyed/collapsed); "new" subtly highlighted.
  No heavy framework, no external trackers.

---

## 11. GitHub Actions — `.github/workflows/fetch.yml`

```yaml
name: daily-fetch
on:
  schedule:
    - cron: "0 0 * * *"      # 00:00 UTC == 07:00 Asia/Ho_Chi_Minh (UTC+7)
  workflow_dispatch: {}       # allow manual runs
jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r fetcher/requirements.txt
      - run: python -m fetcher.main
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
```

A separate `pages.yml` deploys `site/` to GitHub Pages on push to `main`
(or configure Pages to serve the `site/` directory directly — see §12).

---

## 12. Automated setup — `setup/provision.sh`

Run after the §4 prerequisites — **but develop and verify everything locally
first (§16); only run this once you are happy.** This does ALL cloud
provisioning from the terminal; no dashboard clicking beyond the access token.

```bash
#!/usr/bin/env bash
set -euo pipefail
# Requires: SUPABASE_ACCESS_TOKEN exported; `supabase` and `gh` CLIs installed;
# `gh auth login` already done.

PROJECT_NAME="vn-tech-digest"
DB_PASSWORD="${DB_PASSWORD:?set DB_PASSWORD}"
REGION="${REGION:-ap-southeast-1}"          # closest to HCMC; adjust if needed
ORG_ID="${ORG_ID:?set ORG_ID (from: supabase orgs list)}"
MY_EMAIL="${MY_EMAIL:?set MY_EMAIL}"
MY_PASSWORD="${MY_PASSWORD:?set MY_PASSWORD}"

# 1) Create the Supabase project (or skip if PROJECT_REF already set)
PROJECT_REF="$(supabase projects create "$PROJECT_NAME" \
  --org-id "$ORG_ID" --db-password "$DB_PASSWORD" --region "$REGION" \
  --output json | jq -r '.id')"
echo "Project ref: $PROJECT_REF"

# 2) Apply schema + RLS as a migration
supabase link --project-ref "$PROJECT_REF" --password "$DB_PASSWORD"
supabase db push                                   # applies supabase/migrations/*

# 3) Read API keys via CLI (no copy-paste from dashboard)
ANON_KEY="$(supabase projects api-keys --project-ref "$PROJECT_REF" --output json | jq -r '.[] | select(.name=="anon") | .api_key')"
SERVICE_KEY="$(supabase projects api-keys --project-ref "$PROJECT_REF" --output json | jq -r '.[] | select(.name=="service_role") | .api_key')"
SUPABASE_URL="https://${PROJECT_REF}.supabase.co"

# 4) Disable public signups via the Management API (one account only)
curl -sS -X PATCH "https://api.supabase.com/v1/projects/${PROJECT_REF}/config/auth" \
  -H "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"disable_signup": true, "mailer_autoconfirm": true}'
#   NOTE: verify exact field names against the current Management API; if a field
#   differs, adjust. Goal: signups OFF, email auto-confirm ON.

# 5) Create the single account via the Admin API (scripted, no UI)
SUPABASE_URL="$SUPABASE_URL" SERVICE_KEY="$SERVICE_KEY" \
  MY_EMAIL="$MY_EMAIL" MY_PASSWORD="$MY_PASSWORD" \
  python setup/create_user.py

# 6) Inject the anon key + URL into the static site config (client-safe)
#    e.g. write site/config.js  ->  window.SUPABASE_URL=...; window.SUPABASE_ANON_KEY=...
printf 'window.SUPABASE_URL="%s";\nwindow.SUPABASE_ANON_KEY="%s";\n' \
  "$SUPABASE_URL" "$ANON_KEY" > site/config.js

# 7) Create the GitHub repo, push, set secrets, enable Pages — all via gh
gh repo create "$PROJECT_NAME" --private --source=. --remote=origin --push
gh secret set SUPABASE_URL --body "$SUPABASE_URL"
gh secret set SUPABASE_SERVICE_ROLE_KEY --body "$SERVICE_KEY"

OWNER="$(gh api user --jq .login)"
# Enable Pages serving the site/ directory (GitHub Actions build) via the API:
gh api -X POST "repos/${OWNER}/${PROJECT_NAME}/pages" \
  -f "source[branch]=main" -f "source[path]=/site" || \
  echo "If this fails, set Pages source once in repo settings (Pages: branch=main, folder=/site)."

echo "Done. Trigger a first fetch: gh workflow run daily-fetch"
```

`setup/create_user.py` (Admin API; no clicking):
```python
import os, requests
url = os.environ["SUPABASE_URL"]; key = os.environ["SERVICE_KEY"]
r = requests.post(f"{url}/auth/v1/admin/users",
    headers={"apikey": key, "Authorization": f"Bearer {key}",
             "Content-Type": "application/json"},
    json={"email": os.environ["MY_EMAIL"], "password": os.environ["MY_PASSWORD"],
          "email_confirm": True})
print(r.status_code, r.text)
r.raise_for_status()
```

**Residual manual fallbacks** (only if a CLI/API call above is unavailable in
the current Supabase/GitHub versions): the two single-toggle items are
"disable signups" (Auth settings) and "set Pages source" (Pages settings).
Everything else is fully scripted.

---

## 13. Single-account access

- Public signups are **disabled** (§12 step 4), so no one else can register.
- Exactly **one user** is created via the Admin API (§12 step 5).
- **RLS** (§8) means even though the static site/anon key are public, the
  database only returns/accepts a user's own status + state rows, and `items`
  are read-only to clients. This is "gate the data, not the page" — the public
  shell is harmless because it is empty without my login.

---

## 14. Things to fill in before/at build

1. **voz sub-forum(s)** — replace `REPLACE_WITH_SUBFORUM_SLUG.ID` in
   `sources.yaml`. Open the desired tech/IT sub-forum on voz.vn and copy the
   `<slug>.<id>` from its URL. Then verify the sorted-listing scrape in
   `voz.py` against that real sub-forum.
2. **Spiderum** — confirmed as the `quan-diem-tranh-luan` category only (already
   set). Change `category_url` if you want a different/additional category.
3. **Recency windows** — defaults follow the "short for high-volume ranked,
   long for low-volume latest" rule (see comment in `sources.yaml`). Tune freely.

---

## 15. Excluded / manual (do not build)

- **Reddit** — anonymous JSON access is blocked (403); official API needs OAuth
  and possibly no new free keys. I browse my multireddit manually (Top → Today,
  ~15 min/day). **Not part of this build.**
- **Blind** — hard-blocked (403), only paid third-party scrapers work. Excluded.
- **Threads** — official API needs a Meta app + OAuth + app review + token
  refresh; too heavy. Excluded.

---

## 16. Local development (test before deploy)

**Yes — almost everything runs locally**, so you can verify the whole digest
before any cloud deploy. The only extra prerequisite is **Docker** (for the
local Supabase stack).

**Spin up the local stack**
1. `supabase start` — runs Postgres + Auth + PostgREST + a local Studio in
   Docker, and prints a local API URL (`http://localhost:54321`) plus local
   `anon` and `service_role` keys (`supabase status` reprints them).
2. `supabase db reset` — applies `supabase/migrations/*` (schema + RLS) to the
   local database.
3. Create a local test user — call the Admin API against `localhost` (same as
   `setup/create_user.py`, pointed at the local URL/key) or use local Studio at
   `http://localhost:54323`.

**Run the fetcher against local**
```bash
SUPABASE_URL=http://localhost:54321 \
SUPABASE_SERVICE_ROLE_KEY=<local service_role from `supabase status`> \
python -m fetcher.main
```
It fetches the **real** public sources and writes into your **local** database.
Inspect the rows in local Studio. This is the place to iterate on `voz.py` and
`spiderum.py`, which parse live HTML and are the likeliest to need tweaks.

**Run the site against local**
- Point `site/config.js` at the local URL + local anon key, serve `site/` with
  `python -m http.server` (or `npx serve`), open it in the browser, and log in
  as the test user. Verify the digest renders, triage statuses persist, and RLS
  works (you only ever see your own statuses).

Only when all of that looks right do you run §12 to provision the cloud project
and deploy.

**What is NOT local (and why that's fine):**
- **External sources** are always the real live sites — you *want* real data to
  test ranking/filtering, so this is correct, not a limitation.
- **GitHub Actions cron** — no need to run it locally; the cron just executes
  the fetcher you already ran by hand. (Optional: `act` can run the workflow
  YAML in Docker if you want to test the workflow itself.)
- **GitHub Pages** — just static hosting; serving `site/` locally is the
  equivalent. After deploy, only check that the live `config.js` and Pages path
  are correct.

**One honest caveat:** locally the fetcher runs from your **residential IP**,
but on GitHub Actions it runs from a **datacenter IP**. For these seven sources
that risk is low (all tested clean), but it is the one behavior local can't
fully guarantee — a source could in theory work from your laptop yet be blocked
from Actions (exactly what happened with Reddit). After the first deploy, skim
the Action logs for any source that fails from the datacenter IP.

**Local keys ≠ cloud keys:** the local anon/service keys are fixed dev keys
from the CLI — don't commit them. The real keys come from §12 provisioning,
which writes the production `site/config.js`.

---

## 17. Build order (suggested for Claude CLI)

1. Scaffold the repo (§5) and write `sources.yaml` (§6).
2. Write `supabase/migrations/0001_init.sql` (§8).
3. Implement the fetcher modules + `rank.py` + `db.py` + `main.py` (§7, §9).
   Test each source locally against `supabase start` (local stack) first.
4. Build the static site (§10) against the local Supabase.
5. Write the Actions workflows (§11).
6. Write `setup/provision.sh` + `setup/create_user.py` (§12).
7. Run setup, trigger a first fetch (`gh workflow run daily-fetch`), verify the
   site renders the day's posts and triage statuses persist.
