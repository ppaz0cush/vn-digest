# How sources are fetched

## The shared pipeline (`fetcher/main.py`)

Every run (4x a day):
1. Load the tracking file (`fetcher/state.py`).
2. For each source in `sources.yaml`, dispatch by **name** to its module in
   `fetcher/sources/`, by **mode**:
   - `mode: all`: `fetch(cfg)` returns posts; those within `lookback_days` that
     weren't written before are created in Notion (create-only, keyed by URL).
   - `mode: weekly_top`: `collect(...)` records counts in the tracking file.
3. If the weekly boundary has passed since the last list (or `--publish`):
   each weekly source's `publish(...)` returns its top N, they're written to
   Notion, then `after_publish(...)` starts the next week (voz: today's counts
   become the baselines).
4. Save the tracking file; print a summary.

"This week" means since the last weekly list (for the very first list: the
previous 7 days). HTTP goes through a shared session with User-Agent
`vn-digest/1.0`; a browser UA is used only where a site requires it.

## Per source

### voz: `sources/voz.py` (weekly top 20 by views gained)
Forums (from `forums:`): **Điểm báo** (`diem-bao.33`, news), **Chuyện trò linh
tinh™** (`chuyen-tro-linh-tinh.17`, general chat) and **from f17 with love**
(`from-f17-with-love.69`, love, marriage and family life). Entry format:
`<slug>.<id>` (a `/f/` forum) or `<type>/<slug>.<id>` (e.g. `s/example-slug.103`).

**Every run:**
- Headless **Chromium** (Playwright) opens each forum's own list "updated in the
  last 7 days, sorted by views":
  `https://voz.vn/f/<slug>/page-<n>?last_days=7&order=view_count&direction=desc`.
  voz sits behind Cloudflare, which blocks plain HTTP and also challenges a
  second page in the same browser session, so every page gets a fresh session
  (2 s apart; failed pages are retried).
- Each thread row gives: thread id, title, link (rewritten to **`/unread`** so
  clicking jumps to your first unread post), views and replies (rounded, e.g.
  `41K`, `3M`), start date and last-post date. Pinned threads are skipped.
- Pages are read until the lowest view total on a page is below the current
  20th-best weekly gain (max `max_pages`). A thread can't gain more views than it
  has in total, so nothing further down can make the list.
- Counts are recorded per thread: first seen (time, views), latest views, and
  the baseline set at the last weekly list.

**At publish:** gain = views now − views at the last weekly list.
- Threads started during the week count all their views.
- Threads first seen mid-week count from when they were first seen.
- Threads shown in millions (`max_views`) are skipped: voz rounds them to whole
  millions, so their weekly gain can't be measured.
- Top 20 across the 3 forums. Then every thread's current views become next
  week's baseline, and threads not seen all week are forgotten.

### tinhte: `sources/tinhte.py` (weekly top 2 by comments)
- **Every run:** `GET https://tinhte.vn/rss` (about the last day of articles);
  each article's comment count is in the feed as `<slash:comments>`.
- **At publish:** candidates = articles published this week. The feed only shows
  an article for about a day, so the 10 most-commented candidates
  (`refresh_top`) get their current count re-read from the article page (the
  `commentCount` in its JSON-LD). Top 2 by comments.

### vnexpress: `sources/vnexpress.py` (weekly top 2 by comments)
- **Every run:** `GET https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss` (the
  "Khoa học công nghệ" section, which absorbed "Số hóa"; ~13 articles a day, the
  feed covers ~4–5 days). Articles are recorded with their publish date.
- **At publish:** every candidate (published this week) gets its comment count
  from the public API
  `https://usi-saas.vnexpress.net/index/get?objectid=<ID>&objecttype=1&siteid=1000000&offset=0&limit=1`
  (`data.totalitem`; the ID is the digits before `.html`). Top 2 by comments.

### anonyviet: `sources/anonyviet.py` (every post)
- `GET https://anonyviet.com/feed/` (the latest 10 posts, about a week).
  `lookback_days: 14` keeps old posts out.

### engineerpro: `sources/engineerpro.py` (every post, ever)
- Substack's public archive API
  `https://engineerprovn.substack.com/api/v1/archive?sort=new&offset=<n>&limit=50`
  lists the whole history (articles and podcast episodes, incl. paid-only
  posts), so the first run writes the full archive and later runs add new
  posts. If the API fails, the RSS feed (latest 20, same URLs) is used.

## Notion columns

What the fetcher writes into each row of **VN Digest Weekly**:

| Column | Type | Meaning |
|---|---|---|
| **Title** | title | Headline; a clickable link to the post (voz → `/unread`). |
| **URL** | url | Raw link; also the dedup key. |
| **Source** | multi-select | `[source, sub-forum]`, e.g. `["voz","diem bao"]`; filter by either. |
| **Label** | select | `Top` (weekly ranking) or `Latest` (every post of an 'all' source). |
| **Status** | select | Your triage: New / Read / Saved / Skipped. **You** set this; the fetcher never overwrites it. |
| **Score** | number | voz: total views (rounded by voz). tinhte/vnexpress: comments. |
| **Δ week** | number | voz: views gained this week (what the list is ranked by). |
| **Prev score** | number | voz: views at the start of the week (0 = started this week). |
| **Rank** | number | Position in this week's list for that source. |
| **Published** | date | Article/post date; for voz, when the thread started. |
| **Fetched** | date | When the row was written or last updated. Used by prune and by a "This week" view. |

Don't delete these properties (the fetcher writes them; prune reads `Fetched`;
dedup reads `URL`). Hide the noisy ones (`URL`, `Prev score`) in your views instead.

A voz thread that makes the list again in a later week updates its existing row
(new numbers, new `Fetched`, `Status` untouched).
