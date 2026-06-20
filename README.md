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
| voz | sorted XenForo listing | ⚠️ Cloudflare returns **403** from this network. The fetcher tolerates it and skips voz. Set a real `<slug>.<id>` in `sources.yaml` and verify from your own IP; it may work for you (this is the residential-vs-datacenter caveat in the spec). |

A typical run yields ~35–40 items. Each source is wrapped in try/except so one
failure never aborts the run.

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
