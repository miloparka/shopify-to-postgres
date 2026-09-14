-- ============================================================================
-- sync_state: watermark table for incremental syncing
-- ============================================================================
-- Holds a single row recording when the last successful sync started, so
-- `python -m sync.sync_all` (MODE=live) can ask Shopify for only records
-- updated since then instead of re-pulling the full store every run. See
-- sync/sync_all.py for how this is read and written.
--
-- The `id boolean primary key default true` + check(id) combo is a common
-- Postgres pattern for enforcing "this table only ever has one row": `id`
-- can only be `true`, and it's the primary key, so a second insert can only
-- ever collide -- which is exactly why sync_all.py uses `.upsert()` against
-- id=true rather than insert.
-- ============================================================================

create table sync_state (
    id               boolean primary key default true,
    last_synced_at   timestamptz,
    constraint sync_state_singleton check (id)
);

alter table sync_state enable row level security;
revoke all on table sync_state from anon, authenticated;
