-- ============================================================================
-- Per-line tax capture: Shopify's real tax_lines data (rate + amount per
-- line item and per shipping line), not just the single order-level total
-- this schema captured before.
--
-- Shopify exposes TaxLine (title, rate, ratePercentage, priceSet, source,
-- channelLiable) in three separate places: Order.taxLines/currentTaxLines
-- (the order-level aggregate orders.total_tax already reflects), and
-- separately on LineItem and ShippingLine -- each carries its OWN tax
-- lines. That's exactly the per-product-vs-shipping breakdown this store
-- needs (e.g. a reduced VAT rate on food items vs. the standard rate on
-- everything else and on shipping) but couldn't see from the order total
-- alone.
--
-- Two child tables, one per parent, mirroring how order_line_items and
-- order_shipping_lines already relate to their own parents:
--
--   * order_line_item_tax_lines -- keyed by line_item_id. order_line_items
--     is upserted against Shopify's own stable id, so this FK is stable
--     too; rows are cleared and re-inserted per synced line item on every
--     sync, since a TaxLine has no id of its own from Shopify to upsert
--     against.
--
--   * order_shipping_line_tax_lines -- keyed by order_id, NOT by
--     order_shipping_lines' own id. order_shipping_lines uses a synthetic
--     `generated always as identity` primary key that gets a fresh value
--     every sync (that table is deleted-then-reinserted per order, never
--     upserted -- see sync/sync_all.py), so an FK pointing at it would go
--     stale the moment a new id was assigned. order_id is stable, and this
--     schema's query only ever pulls one shipping line per order today
--     (Order.shippingLine, the singular deprecated field, not the
--     shippingLines connection), so it's already effectively 1:1 -- keying
--     on order_id sidesteps the instability without losing anything.
-- ============================================================================

create table order_line_item_tax_lines (
    id                 bigint generated always as identity primary key,
    line_item_id       bigint not null references order_line_items(id) on delete cascade,
    title              text,               -- e.g. "VAT" / "ALV"
    rate               numeric(9,6),       -- fraction, e.g. 0.135 for 13.5%
    rate_percentage    numeric(9,4),       -- same rate as a percentage, e.g. 13.5
    amount             numeric(12,2),      -- tax amount in shop currency
    source             text,               -- who/what calculated this tax line
    channel_liable     boolean,            -- null = unknown liability, per Shopify's docs
    synced_at          timestamptz not null default now()
);

create table order_shipping_line_tax_lines (
    id                 bigint generated always as identity primary key,
    order_id           bigint not null references orders(id) on delete cascade,
    title              text,
    rate               numeric(9,6),
    rate_percentage    numeric(9,4),
    amount             numeric(12,2),
    source             text,
    channel_liable     boolean,
    synced_at          timestamptz not null default now()
);

create index idx_line_item_tax_lines_line_item_id on order_line_item_tax_lines(line_item_id);
create index idx_shipping_line_tax_lines_order_id on order_shipping_line_tax_lines(order_id);

-- Same deny-all-except-service_role convention as every other table.
alter table order_line_item_tax_lines enable row level security;
alter table order_shipping_line_tax_lines enable row level security;

revoke all on table order_line_item_tax_lines, order_shipping_line_tax_lines
from anon, authenticated;
