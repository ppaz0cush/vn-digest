# Editing sources

The source list lives in **`sources.yaml`**. The fetcher reads it on every run,
so most changes are just edits there + a commit.

## Tune an existing source

Edit its block in `sources.yaml`. Fields:

| Field | Applies to | Meaning |
|---|---|---|
| `name` | all | Must match a key in `WEEKLY_SOURCES` / `ALL_SOURCES` in `fetcher/main.py` (this is how it's dispatched). |
| `mode` | all | `weekly_top` (tracked all week, top N published on Monday) or `all` (every post, as soon as it's seen). |
| `top` | weekly_top | How many make the weekly list. |
| `url` | feed sources | The RSS/feed URL. |
| `lookback_days` | all | Only posts from the last N days; `null` = no limit (whole history). |

**voz-only fields:**

| Field | Meaning |
|---|---|
| `forums` | Sub-forums. Format `<slug>.<id>` (a `/f/` forum) or `<type>/<slug>.<id>` (e.g. `s/example-slug.103`). |
| `max_pages` | Most list pages read per forum per run (20 threads each). |
| `skip_sticky` | `true` = ignore pinned threads. |
| `max_views` | Threads above this are skipped (voz shows 1M+ rounded to whole millions). |

**tinhte-only:** `refresh_top`: how many top candidates get their comment count
re-read from the article page at publish.

**engineerpro-only:** `archive_url`: Substack's archive API (full history);
`url` is the RSS fallback.

**When the weekly list is published:** the top-level `publish:` block
(`weekday`, `hour`, `timezone`). Runs happen at 03:15, 09:15, 15:15 and 21:15
Vietnam time (`.github/workflows/fetch.yml`), so pick an hour just before one
of those.

### Add / remove a voz sub-forum
Open the forum on voz.vn, copy the `<slug>.<id>` from its URL
(`voz.vn/f/<slug>.<id>/`), and add it to the `forums:` list. For voz's "showcase"
nodes the URL is `/s/<slug>.<id>/` → write it as `s/<slug>.<id>`. Commit.

## Add a brand-new source

1. **Create the module** `fetcher/sources/<name>.py`.
   - **`mode: all`** (every post): expose `fetch(cfg)` returning a list of
     ```python
     {"url": "...", "title": "...", "published_at": dt}   # tz-aware datetime or None
     ```
     Plain RSS? Reuse the helper:
     ```python
     from ._rss import latest
     def fetch(cfg):
         return latest(cfg)
     ```
   - **`mode: weekly_top`**: expose three functions, each getting the source's
     slice of the tracking file (`src["items"]` is yours to fill):
     - `collect(cfg, src, now, week_start)`: record what you see; return a
       short summary string.
     - `publish(cfg, src, now, week_start)`: return the week's top N as rows
       (see `weekly.comment_row` for the shape).
     - `after_publish(src, now, week_start)`: reset for the next week, if needed.

     See `tinhte.py` (counts in the feed), `vnexpress.py` (counts from an API)
     and `voz.py` (HTML + gains), plus `_rss.fetch_feed`, `fetcher/http.get` and
     the `fetcher/util` date helpers.

2. **Register it** in `fetcher/main.py`:
   ```python
   from .sources import ..., yoursource
   ALL_SOURCES = {..., "yoursource": yoursource}      # or WEEKLY_SOURCES
   ```

3. **Add a config block** to `sources.yaml` with `name: yoursource`, its `mode`
   and the fields above.

Test it: `python -m fetcher.main --dry-run --publish --only yoursource`.

## Remove a source

Delete its block from `sources.yaml` (enough to stop fetching it). To remove it
fully, also delete `fetcher/sources/<name>.py` and its line in `main.py`. Its
rows already in Notion stay until you prune them.

## Notes

- **Honest labels:** weekly lists are `Top`; every-post sources are `Latest`.
- After editing, the schedule picks it up automatically; or run it once with
  `gh workflow run daily-fetch`.
