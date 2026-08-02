# How sources are fetched

## The shared pipeline (`fetcher/main.py`)

Each run:
1. Read the previous scores from Notion → `{url: {score, last_score_at}}` (for the trending deltas).
2. For each source in `sources.yaml`, dispatch by **name** to its module in `fetcher/sources/` and call `fetch(cfg)` → raw items.
3. **Compute deltas** (`apply_deltas`): stamp `last_score_at = now` on every item; if it has a score *and* we've seen its URL before, set `prev_score`, `score_delta = score − prev_score`, and `_trend = max(delta, 0)`; if it's new, `_trend = score`.
4. **Filter → rank → cap** (`rank.py`, see bottom).
5. Dedupe by URL within the source, then **upsert** to Notion.

Every source returns items shaped: `url, title, source_detail, published_at, score, score_type` (voz also adds `subsource` and `metadata`). HTTP goes through a shared session with User-Agent `vn-digest/1.0`; a browser UA is used only where a site requires it.

## Per source

### tinhte — `sources/tinhte.py`
- `GET https://tinhte.vn/rss`, parsed with feedparser.
- Comment count is embedded in each item as `<slash:comments>` — read straight from the feed, no extra request → `score`, `score_type="comments"`.
- Config: window 24h, `trending`, cap 1 → keep last-24h articles, rank by **comments gained since last run**, top 1.

### vnexpress — `sources/vnexpress.py`
- `GET https://vnexpress.net/rss/so-hoa.rss` (the Số hóa section).
- RSS has no comment counts, so: build items from the feed → **filter to the 24h window first** (to limit API calls) → for each survivor, extract the numeric id (`(\d+)\.html`) and call the public comment API
  `https://usi-saas.vnexpress.net/index/get?objectid=<ID>&objecttype=1&siteid=1000000&offset=0&limit=1` → read `data.totalitem` → `score`, `score_type="comments"`.
- Config: window 24h, `trending`, cap 1.

### anonyviet / engineerpro — `sources/anonyviet.py`, `sources/engineerpro.py`
- Thin wrappers over `_rss.latest()`: `GET` the feed, take title/link/published, **no score**.
- anonyviet: `https://anonyviet.com/feed/`, window 7 days, cap 20.
- engineerpro: `https://engineerprovn.substack.com/feed`, window 14 days, cap 20 (they post ~2–3×/week).
- Both are `rank: latest` (chronological).

### spiderum — `sources/spiderum.py`
- `GET` the category page (`…/danh-muc/quan-diem-tranh-luan?sort=new&page_idx=1`) with a browser UA.
- Tries the embedded `__NEXT_DATA__` JSON first; falls back to scraping `/bai-dang/` anchors (grouped by slug — title from the text anchor, views from a "2.2k" badge).
- The listing exposes **no post dates**, so `published_at` is null → the window can't filter it; page order (newest-first) + cap 1 govern.
- Config: `rank: latest`, cap 1.

### voz — `sources/voz.py` (the complex one)
Runs **per forum** in the `forums:` list. Entry format: `<slug>.<id>` (a `/f/` forum) or `<type>/<slug>.<id>` for other node types (e.g. `s/example-slug.103` for voz's `/s/` nodes).

**Ranked path (headless browser):**
- Launch headless **Chromium** (Playwright), `goto https://voz.vn/<type>/<slug>/` — the **default listing = most-recently-active threads** (deliberately *not* `?order=view_count`, which returns stale all-time threads). voz fronts this with a Cloudflare **JS managed challenge** that plain HTTP can't pass; the real browser executes the challenge JS, then the thread rows appear (retries up to 2×).
- Parse each `div.structItem--thread`: skip pinned/sticky; title + link (URL rewritten to **`/unread`** so clicking jumps to your first unread post); views/replies from the meta cell (`19K`→19000, `3M`→3000000); time from `.structItem-latestDate` (last activity). `score` = views (or replies if `rank_by: replies`); `subsource` = readable forum label (e.g. "diem bao").
- **Per-forum cap** (`per_forum_items`): keep each forum's **N most-recently-active** threads (the listing is in last-activity order). Small capture keeps each forum represented evenly, and no single busy forum crowds out the rest.

**Fallback (RSS):** if Playwright is missing or the challenge isn't solved, fetch `https://voz.vn/<type>/<slug>/index.rss` (not challenged, but chronological, no counts). If *every* forum fell back, voz is relabeled **Latest**.

- Config: 3 forums, window 24h, `rank_by: views`, `trending`, `per_forum_items: 3`, overall cap 9.

## Post-processing (`fetcher/rank.py`)

- **Window filter:** keep items whose `published_at` (last-activity for voz) is within `window_hours` of now. `null` window = keep all; items with no date are kept.
- **Rank:**
  - `latest` → newest first by `published_at`.
  - `top` → by `score` desc (optional `tiebreak: published_desc`).
  - `trending` (auto-applied when a `top` source sets `trending: true`) → by `_trend` (the ~24h gain) desc, tiebreak newest. On cold start (no prior score) it ranks by current score.
- **Cap** at `max_items`, assign `rank_position` (1-based), dedupe by URL.

## Notion columns

What the fetcher writes into each row (created with `setup/notion_init.py`):

| Column | Type | Meaning |
|---|---|---|
| **Title** | title | Headline; a clickable link to the article (voz → `/unread`). |
| **URL** | url | Raw link; also the dedup key. |
| **Source** | multi-select | `[source, sub-forum]`, e.g. `["voz","diem bao"]` — filter by either. |
| **Label** | select | `Top` (engagement-ranked) or `Latest` (chronological). |
| **Status** | select | Your triage: New / Read / Saved / Skipped. **You** set this; the fetcher never overwrites it. |
| **Score** | number | Engagement total — views (voz) or comments (tinhte/vnexpress). |
| **Δ today** | number | Gain since the previous run (~24h). Sort by this for "hot now". |
| **Prev score** | number | Score at the previous run (input to Δ today). Internal. |
| **Rank** | number | The fetcher's top-N position within the source that run. |
| **Published** | date | When the article/thread was published (last activity for voz). |
| **Fetched** | date | When the fetcher last captured/updated the row. Used by prune. |

Don't delete these properties (the fetcher writes them; prune reads `Status` + `Fetched`; dedup reads `URL`). Hide the noisy ones (`URL`, `Prev score`, `Rank`) in your views instead.
