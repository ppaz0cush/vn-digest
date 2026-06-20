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
drop policy if exists items_read on items;
create policy items_read on items
  for select to authenticated using (true);

-- item_status: a user may only see and modify their OWN rows.
drop policy if exists status_select on item_status;
drop policy if exists status_insert on item_status;
drop policy if exists status_update on item_status;
drop policy if exists status_delete on item_status;
create policy status_select on item_status for select to authenticated using (auth.uid() = user_id);
create policy status_insert on item_status for insert to authenticated with check (auth.uid() = user_id);
create policy status_update on item_status for update to authenticated using (auth.uid() = user_id);
create policy status_delete on item_status for delete to authenticated using (auth.uid() = user_id);

-- user_state: same, own row only.
drop policy if exists state_select on user_state;
drop policy if exists state_insert on user_state;
drop policy if exists state_update on user_state;
create policy state_select on user_state for select to authenticated using (auth.uid() = user_id);
create policy state_insert on user_state for insert to authenticated with check (auth.uid() = user_id);
create policy state_update on user_state for update to authenticated using (auth.uid() = user_id);

-- BASE TABLE GRANTS ----------------------------------------------------------
-- RLS decides WHICH rows; these GRANTs decide whether the role may touch the
-- table at all. (Supabase's hosted default privileges usually cover this, but
-- we grant explicitly so the schema is portable and works when applied raw.)
-- items: clients only READ (and only when logged in); the fetcher writes.
grant select on items to authenticated;
grant select, insert, update on items to service_role;
-- per-user triage + state: logged-in users do full CRUD on their OWN rows
-- (RLS enforces ownership); service_role retains full access.
grant select, insert, update, delete on item_status to authenticated, service_role;
grant select, insert, update, delete on user_state  to authenticated, service_role;
