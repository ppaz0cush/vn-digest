-- Delta / "trending" support: track each item's previous score so the fetcher
-- can rank by engagement GAINED since the last run (e.g. views/comments in the
-- last ~24h), not just lifetime totals.
alter table items add column if not exists prev_score    integer;      -- score at the previous run
alter table items add column if not exists score_delta   integer;      -- score - prev_score (gain since last run; may be null on first sighting)
alter table items add column if not exists last_score_at timestamptz;  -- when the current `score` was captured
alter table items add column if not exists prev_score_at timestamptz;  -- when `prev_score` was captured

-- (Existing table grants cover new columns automatically.)
