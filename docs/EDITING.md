# Editing sources

The source list lives in **`sources.yaml`**. The fetcher reads it on every run,
so most changes are just edits there + a commit.

## Tune an existing source

Edit its block in `sources.yaml`. Common fields:

| Field | Applies to | Meaning |
|---|---|---|
| `name` | all | Must match a key in `SOURCES` in `fetcher/main.py` (this is how it's dispatched). |
| `url` | feed sources | The RSS/feed URL. |
| `rank` | all | `top` (by engagement) or `latest` (chronological). |
| `rank_by` | `top` | `views`, `comments`, etc. (which `score` to rank by). |
| `trending` | `top` | `true` → rank by **gain since last run** instead of the lifetime total. |
| `tiebreak` | `top` | `published_desc` to break score ties by newest. |
| `window_hours` | all | Recency look-back. `null` = no window. (No effect if items have no date, e.g. spiderum.) |
| `max_items` | all | Cap after ranking. |
| `label` | all | `Top` / `Latest` — the honest tag shown in Notion's `Label`. |

**voz-only fields:**

| Field | Meaning |
|---|---|
| `forums` | List of sub-forums. Format `<slug>.<id>` (a `/f/` forum) or `<type>/<slug>.<id>` (e.g. `s/example-slug.103`). |
| `use_browser` | `true` = headless-browser ranked fetch; `false` = RSS-only (no Playwright needed). |
| `skip_sticky` | `true` = ignore pinned megathreads. |
| `per_forum_items` | Keep top-N per forum so one busy forum can't dominate. |

### Add / remove a voz sub-forum
Open the forum on voz.vn, copy the `<slug>.<id>` from its URL
(`voz.vn/f/<slug>.<id>/`), and add it to the `forums:` list. For voz's "showcase"
nodes the URL is `/s/<slug>.<id>/` → write it as `s/<slug>.<id>`. Commit.

## Add a brand-new source

3 steps:

1. **Create the module** `fetcher/sources/<name>.py` exposing `fetch(cfg)` that
   returns a list of dicts with these keys:
   ```python
   {
     "url": "...",            # required, unique (dedup key)
     "title": "...",          # required
     "source_detail": "...",  # optional, free text
     "published_at": dt,      # tz-aware datetime or None
     "score": 123,            # int engagement count, or None
     "score_type": "comments" # 'comments'|'views'|... or None
   }
   ```
   `main.py` handles delta/window/rank/cap/dedup — your module only fetches.
   - **Plain RSS?** Reuse the helper:
     ```python
     from ._rss import latest
     def fetch(cfg):
         return latest(cfg)
     ```
   - **RSS with a count, or HTML/JSON?** See `tinhte.py` / `spiderum.py` /
     `voz.py` for patterns (and `_rss.fetch_feed`, `fetcher/http.get`,
     `fetcher/util` date helpers).

2. **Register it** in `fetcher/main.py`:
   ```python
   from .sources import ..., yoursource
   SOURCES = { ..., "yoursource": yoursource.fetch }
   ```

3. **Add a config block** to `sources.yaml` with `name: yoursource` and the
   fields above.

Test it: `python -m fetcher.main --dry-run --only yoursource`.

## Remove a source

Delete its block from `sources.yaml` (enough to stop fetching it). To remove it
fully, also delete `fetcher/sources/<name>.py` and its line in `SOURCES`.
Existing rows already in Notion stay until you prune them.

## Notes

- **Honest labels:** if a source has no real engagement number, use `rank:
  latest` / `label: Latest` — don't call a chronological feed "Top".
- **Windows rule of thumb:** short (24h) for high-volume ranked sources so you
  get *today's* hot items; long (7–14d) for low-volume ones so the section
  isn't empty on quiet days.
- After editing, the daily cron picks it up automatically; or run it once with
  `gh workflow run daily-fetch`.
