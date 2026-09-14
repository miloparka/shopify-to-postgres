-- ============================================================================
-- Shopify -> Supabase: full schema backup
-- ============================================================================
-- This is a standalone, self-contained snapshot of the current schema --
-- tables, indexes, the order_details view, and RLS/security -- kept as a
-- backup separate from the timestamped files in supabase/migrations/.
--
-- Use it to:
--   * Recreate the schema from scratch on a fresh Supabase/Postgres database
--     if the original project is ever lost or you need a clean environment.
--   * Have a single readable reference for "what does the schema actually
--     look like right now" without replaying the full migration history.
--
-- This is NOT meant to replace supabase/migrations/ for normal development --
-- keep using `supabase db diff`/migrations for day-to-day schema changes.
-- This file is just a point-in-time backup you can re-run safely (it drops
-- and recreates everything below, so don't run it against a database whose
-- data you want to keep).
--
-- Paste this into the Supabase SQL editor, or run it via psql/the Supabase
-- CLI against any Postgres database.
--
-- Regenerate this file whenever the schema changes meaningfully, so it
-- stays a true backup rather than going stale.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Drop everything first, so this script is safely re-runnable
-- ----------------------------------------------------------------------------
drop view if exists order_details;
drop table if exists order_shipping_lines;
drop table if exists order_line_items;
drop table if exists orders;
drop table if exists product_images;
drop table if exists product_variants;
drop table if exists products;
drop table if exists customers;
drop table if exists sync_state;

-- ----------------------------------------------------------------------------
-- customers
-- Pseudonymous: Shopify's numeric id is the only identifier kept.
-- Excluded on purpose: first_name, last_name, email, phone, company,
-- defaultAddress street/zip/name/phone, note.
-- ----------------------------------------------------------------------------
create table customers (
    id                 bigint primary key,        -- Shopify's numeric customer id (pseudonymous key)
    state              text,                       -- enabled/disabled/invited/declined
    verified_email     boolean,
    accepts_marketing  boolean,
    tax_exempt         boolean,
    currency           text,                       -- from amountSpent.currencyCode
    orders_count       integer,
    total_spent        numeric(12,2) default 0,
    tags               text[],                     -- review before use: free-text tags can
                                                     -- occasionally contain a name; scrub in
                                                     -- transform.py if that's a risk for your store
    customer_locale    text,
    country             text,                       -- geography only, from defaultAddress
    province           text,
    city               text,
    created_at         timestamptz,
    updated_at         timestamptz,
    synced_at          timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- products
-- ----------------------------------------------------------------------------
create table products (
    id                 bigint primary key,
    title              text not null,
    body_html          text,                       -- descriptionHtml
    vendor             text,
    product_type       text,
    handle             text,
    status             text,                       -- active/archived/draft
    tags               text[],
    package_type      text,                       -- custom metafield: packaging type
    published_at       timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz,
    synced_at          timestamptz not null default now()
);

create table product_variants (
    id                    bigint primary key,
    product_id            bigint not null references products(id) on delete cascade,
    title                 text,
    sku                   text,
    barcode               text,
    price                 numeric(12,2),
    compare_at_price      numeric(12,2),
    inventory_quantity    integer,
    weight                numeric(10,3),
    weight_unit           text,
    requires_shipping     boolean,
    taxable               boolean,
    position              integer,
    created_at            timestamptz,
    updated_at            timestamptz,
    synced_at             timestamptz not null default now()
);

create table product_images (
    id            bigint primary key,
    product_id    bigint not null references products(id) on delete cascade,
    src           text,
    alt           text,
    position      integer,                         -- assigned from array order in transform.py,
                                                     -- not a field Shopify's Image type exposes
    synced_at     timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- orders
-- Excluded on purpose: email, phone, contact/customer email, billing_address,
-- shipping_address (street-level), browser_ip, client_details (user agent),
-- payment gateway/card details, note, note_attributes (can contain PII).
-- ----------------------------------------------------------------------------
create table orders (
    id                    bigint primary key,
    customer_id           bigint references customers(id),  -- nullable: guest checkout
    order_number          text,                       -- e.g. "#1001" (Shopify's `name` field)
    currency              text,
    financial_status      text,                       -- displayFinancialStatus
    fulfillment_status    text,                       -- displayFulfillmentStatus
    total_price           numeric(12,2),
    subtotal_price        numeric(12,2),
    total_tax             numeric(12,2),
    total_discounts       numeric(12,2),
    total_shipping        numeric(12,2),
    source_name           text,                       -- e.g. "web", "pos"
    tags                  text[],
    discount_codes        jsonb,                       -- codes only, no customer data
    shipping_country      text,                        -- geography only
    shipping_province     text,
    shipping_city         text,
    created_at            timestamptz,
    updated_at            timestamptz,
    processed_at          timestamptz,
    cancelled_at          timestamptz,
    cancel_reason         text,
    closed_at             timestamptz,
    synced_at             timestamptz not null default now()
);

create table order_line_items (
    id                    bigint primary key,
    order_id              bigint not null references orders(id) on delete cascade,
    product_id            bigint references products(id),
    variant_id            bigint references product_variants(id),
    title                 text,
    sku                   text,
    quantity              integer not null,
    price                 numeric(12,2) not null,
    total_discount        numeric(12,2),
    fulfillment_status    text,
    synced_at             timestamptz not null default now()
);

create table order_shipping_lines (
    id            bigint generated always as identity primary key,
    order_id      bigint not null references orders(id) on delete cascade,
    title         text,               -- e.g. "Standard Shipping"
    price         numeric(12,2),
    code          text,
    synced_at     timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- sync_state
-- Single-row watermark table for incremental syncing (see
-- sync/sync_all.py and migrations/20260914120000_sync_state.sql).
-- ----------------------------------------------------------------------------
create table sync_state (
    id               boolean primary key default true,
    last_synced_at   timestamptz,
    constraint sync_state_singleton check (id)
);

-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
create index idx_orders_customer_id on orders(customer_id);
create index idx_orders_created_at on orders(created_at);
create index idx_variants_product_id on product_variants(product_id);
create index idx_images_product_id on product_images(product_id);
create index idx_line_items_order_id on order_line_items(order_id);
create index idx_line_items_product_id on order_line_items(product_id);
create index idx_shipping_lines_order_id on order_shipping_lines(order_id);

-- ----------------------------------------------------------------------------
-- Convenience view -- pre-joins the common case
-- ----------------------------------------------------------------------------
create view order_details as
select
    o.id as order_id,
    o.order_number,
    o.total_price,
    o.financial_status,
    o.fulfillment_status,
    o.shipping_city,
    o.shipping_province,
    o.shipping_country,
    o.created_at,
    c.id as customer_id,
    li.title as product_title,
    li.quantity,
    li.price as unit_price
from orders o
left join customers c on c.id = o.customer_id
left join order_line_items li on li.order_id = o.id;

-- ----------------------------------------------------------------------------
-- Row level security -- no anon/authenticated access, only the service_role
-- key (used by the sync script) can read/write.
-- ----------------------------------------------------------------------------
alter table customers enable row level security;
alter table products enable row level security;
alter table product_variants enable row level security;
alter table product_images enable row level security;
alter table orders enable row level security;
alter table order_line_items enable row level security;
alter table order_shipping_lines enable row level security;
alter table sync_state enable row level security;

revoke all on table
    customers, products, product_variants, product_images,
    orders, order_line_items, order_shipping_lines, sync_state
from anon, authenticated;
revoke all on order_details from anon, authenticated;

alter view order_details set (security_invoker = on);

-- ============================================================================
-- End of backup. To restore: paste this whole file into a fresh Supabase
-- project's SQL editor (or run via psql/CLI), then repopulate data with
-- either supabase/seed.sql (demo data) or `python -m sync.sync_all`
-- (MODE=demo or MODE=live).
-- ============================================================================
