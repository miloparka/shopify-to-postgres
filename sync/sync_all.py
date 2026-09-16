"""
Runs a full sync: customers, products (+ variants + images), then orders
(+ line items + shipping lines), in that order, since orders/line_items/
shipping_lines have foreign keys pointing at the other tables.

Usage:
    python -m sync.sync_all            # uses demo data (MODE unset or 'demo')
    MODE=live python -m sync.sync_all  # uses live Shopify API

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables
to be set (see .env.example). For MODE=live, also requires
SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN.

Incremental syncing (MODE=live only):
    After the first successful run, this script records when that run
    started in the `sync_state` table (see
    supabase/migrations/20260914120000_sync_state.sql). Every subsequent
    run asks Shopify for only products/customers/orders updated since
    that timestamp instead of pulling everything again -- much cheaper
    once a store has tens of thousands of records.

    A record only shows up as "updated" if Shopify's updated_at moved --
    a DELETED record never does, so incremental runs never remove rows
    that were deleted in Shopify. Run a full resync occasionally (or
    after anything you suspect deleted records) to reconcile:

        MODE=live FULL_SYNC=true python -m sync.sync_all

    FULL_SYNC=true also ignores (but still overwrites, on success) any
    existing watermark, which is the way to recover if the watermark
    table is ever wrong or the two get out of sync for any reason.
"""

import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
load_dotenv()

from data_source.demo_source import DemoDataSource
from data_source.live_shopify_source import LiveShopifyDataSource
from sync.transform import (
    transform_customer,
    transform_images,
    transform_order,
    transform_product,
    transform_shipping_line,
    transform_shipping_line_tax_lines,
    transform_variants,
)


def get_data_source():
    mode = os.environ.get("MODE", "demo")
    if mode == "live":
        return LiveShopifyDataSource()
    return DemoDataSource()


def get_supabase_client():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


# Rows per upsert/insert call to Supabase. A single request holding every
# row for a large store (tens of thousands of customers, for example) risks
# hitting request-size/timeout limits, and -- more importantly -- Postgres
# refuses an upsert where the SAME primary key appears twice within one
# command ("ON CONFLICT DO UPDATE command cannot affect row a second time"),
# which would otherwise fail the *entire* batch over a single duplicate.
# Batching bounds the blast radius of both problems to one chunk.
BATCH_SIZE = 500


def _dedupe_by_id(rows: list[dict]) -> list[dict]:
    """Collapse rows sharing the same 'id' down to one (last one wins),
    so a single upsert command never contains the same primary key twice.
    Duplicates can happen at real scale if Shopify's cursor pagination
    drifts on a large, actively-changing connection -- adding an explicit
    sortKey to the queries (see live_shopify_source.py) is the primary fix,
    but this is a cheap safety net regardless of the cause.
    """
    deduped = {row["id"]: row for row in rows}
    if len(deduped) != len(rows):
        print(f"  (deduplicated {len(rows) - len(deduped)} row(s) sharing an id before upsert)")
    return list(deduped.values())


def _upsert_in_batches(supabase, table: str, rows: list[dict]) -> None:
    rows = _dedupe_by_id(rows)
    for i in range(0, len(rows), BATCH_SIZE):
        supabase.table(table).upsert(rows[i:i + BATCH_SIZE]).execute()


def _insert_in_batches(supabase, table: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), BATCH_SIZE):
        supabase.table(table).insert(rows[i:i + BATCH_SIZE]).execute()


# ----------------------------------------------------------------------------
# Incremental sync watermark
#
# Stored in a single-row `sync_state` table rather than a local file so it's
# shared across machines/runs and survives a fresh checkout -- see
# supabase/migrations/20260914120000_sync_state.sql.
# ----------------------------------------------------------------------------

def _get_last_synced_at(supabase) -> str | None:
    result = supabase.table("sync_state").select("last_synced_at").eq("id", True).execute()
    rows = result.data
    if rows and rows[0].get("last_synced_at"):
        return rows[0]["last_synced_at"]
    return None


def _set_last_synced_at(supabase, timestamp: str) -> None:
    supabase.table("sync_state").upsert({"id": True, "last_synced_at": timestamp}).execute()


def sync_customers(source, supabase, updated_since: str | None = None):
    raw_customers = source.get_customers(updated_since)
    rows = [transform_customer(node) for node in raw_customers]
    if rows:
        _upsert_in_batches(supabase, "customers", rows)
    print(f"Synced {len(rows)} customers")


def sync_products(source, supabase, updated_since: str | None = None):
    raw_products = source.get_products(updated_since)
    product_rows = []
    variant_rows = []
    image_rows = []
    for node in raw_products:
        product_row = transform_product(node)
        product_rows.append(product_row)
        variant_rows.extend(transform_variants(node, product_row["id"]))
        image_rows.extend(transform_images(node, product_row["id"]))

    if product_rows:
        _upsert_in_batches(supabase, "products", product_rows)
    if variant_rows:
        _upsert_in_batches(supabase, "product_variants", variant_rows)
    if image_rows:
        _upsert_in_batches(supabase, "product_images", image_rows)

    print(
        f"Synced {len(product_rows)} products, "
        f"{len(variant_rows)} variants, {len(image_rows)} images"
    )


def sync_orders(source, supabase, updated_since: str | None = None):
    raw_orders = source.get_orders(updated_since)
    order_rows = []
    line_item_rows = []
    line_item_tax_line_rows = []
    shipping_line_rows = []
    shipping_line_tax_line_rows = []
    order_ids = []
    line_item_ids = []

    for node in raw_orders:
        order_row, items, item_tax_lines = transform_order(node)
        order_rows.append(order_row)
        line_item_rows.extend(items)
        line_item_tax_line_rows.extend(item_tax_lines)
        line_item_ids.extend(item["id"] for item in items)
        order_ids.append(order_row["id"])

        shipping_line = transform_shipping_line(node)
        if shipping_line:
            shipping_line_rows.append(shipping_line)
        shipping_line_tax_line_rows.extend(transform_shipping_line_tax_lines(node))

    if order_rows:
        _upsert_in_batches(supabase, "orders", order_rows)
    if line_item_rows:
        _upsert_in_batches(supabase, "order_line_items", line_item_rows)

    if line_item_ids:
        # order_line_item_tax_lines has no natural Shopify id to upsert
        # against either (a TaxLine doesn't carry one) -- but line_item_id
        # IS stable, since order_line_items is upserted against Shopify's
        # own id, so clearing and re-inserting by line_item_id is safe and
        # idempotent, same reasoning as order_shipping_lines below.
        line_item_ids = list(dict.fromkeys(line_item_ids))
        for i in range(0, len(line_item_ids), BATCH_SIZE):
            supabase.table("order_line_item_tax_lines").delete().in_(
                "line_item_id", line_item_ids[i:i + BATCH_SIZE]
            ).execute()
    if line_item_tax_line_rows:
        _insert_in_batches(supabase, "order_line_item_tax_lines", line_item_tax_line_rows)

    if order_ids:
        # order_shipping_lines has no natural Shopify id to upsert against
        # (it's a synthetic identity column), so clear and re-insert per
        # synced order to stay idempotent across repeated runs. Batched too,
        # since `.in_()` on tens of thousands of ids in one request has the
        # same size/timeout risk as a giant upsert.
        order_ids = list(dict.fromkeys(order_ids))  # de-dupe, preserve order
        for i in range(0, len(order_ids), BATCH_SIZE):
            supabase.table("order_shipping_lines").delete().in_(
                "order_id", order_ids[i:i + BATCH_SIZE]
            ).execute()
            # order_shipping_line_tax_lines is keyed by order_id rather
            # than order_shipping_lines' own id (see transform.py's
            # transform_shipping_line_tax_lines for why), so it's cleared
            # in the same pass, by the same order_ids.
            supabase.table("order_shipping_line_tax_lines").delete().in_(
                "order_id", order_ids[i:i + BATCH_SIZE]
            ).execute()
    if shipping_line_rows:
        _insert_in_batches(supabase, "order_shipping_lines", shipping_line_rows)
    if shipping_line_tax_line_rows:
        _insert_in_batches(supabase, "order_shipping_line_tax_lines", shipping_line_tax_line_rows)

    print(
        f"Synced {len(order_rows)} orders, {len(line_item_rows)} line items "
        f"({len(line_item_tax_line_rows)} tax lines), {len(shipping_line_rows)} "
        f"shipping lines ({len(shipping_line_tax_line_rows)} tax lines)"
    )


# ----------------------------------------------------------------------------
# Failure classification
#
# Best-effort, human-readable one-line summary of *why* a run failed. This
# isn't exhaustive error handling -- an unrecognized error still crashes
# the script and fails the run exactly as before, just with a generic
# fallback message. Its only job is to make the printed
# "SYNC_FAILURE_REASON: ..." line (grepped out of the logs by the GitHub
# Actions workflow's Slack notification step) say something more useful
# than "the process exited non-zero" when the cause is a known, common one.
# ----------------------------------------------------------------------------

def _describe_failure(exc: BaseException) -> str:
    text = str(exc)

    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        status = response.status_code if response is not None else None
        if status == 401:
            return (
                "Shopify rejected the access token (401 Unauthorized) -- it "
                "may have been revoked, the app uninstalled, or the client "
                "secret rotated. Re-check SHOPIFY_ACCESS_TOKEN / "
                "SHOPIFY_CLIENT_ID+SECRET."
            )
        if status == 404:
            return (
                "Shopify returned 404 -- check SHOPIFY_STORE_URL is the "
                "exact shop domain (e.g. your-store.myshopify.com), not a "
                "guessed or partial one."
            )
        if status:
            return f"HTTP {status} error talking to Shopify: {text}"
        return f"Network error talking to Shopify: {text}"

    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Could not reach Shopify (network/DNS issue): {text}"

    if isinstance(exc, requests.exceptions.Timeout):
        return f"Request to Shopify timed out: {text}"

    if isinstance(exc, KeyError):
        return (
            f"Missing required environment variable/secret: {exc} -- check "
            f"it's set in .env locally or in the repo's Actions secrets."
        )

    if "shop_not_permitted" in text:
        return (
            "Shopify client-credentials grant rejected -- the app and "
            "store aren't in the same Shopify organization."
        )

    if "ACCESS_DENIED" in text or "SHOP_INACTIVE" in text:
        return f"Shopify denied the request outright (not a transient error): {text}"

    if "MAX_COST_EXCEEDED" in text:
        return f"A single Shopify query exceeded the max cost limit: {text}"

    if "still failing after" in text and "retries" in text:
        return f"Shopify kept throttling requests past the retry limit: {text}"

    if "cannot affect row a second time" in text:
        return f"Postgres duplicate-key conflict during upsert: {text}"

    if "PGRST" in text or "relation" in text and "does not exist" in text:
        return f"Supabase/Postgres schema error (possibly a missing migration): {text}"

    return f"{type(exc).__name__}: {text}"


def main():
    source = get_data_source()
    supabase = get_supabase_client()
    is_live = os.environ.get("MODE", "demo") == "live"
    full_sync = os.environ.get("FULL_SYNC", "false").lower() == "true"

    # Capture the "as of" time before pulling anything, and use *this* run's
    # start (minus a small safety buffer) as the new watermark -- not
    # whatever time the run happens to finish at, which could otherwise
    # miss records that changed while this run was still in progress.
    sync_started_at = datetime.now(timezone.utc)

    updated_since = None
    if is_live and not full_sync:
        updated_since = _get_last_synced_at(supabase)

    if is_live:
        mode_desc = f"incremental, since {updated_since}" if updated_since else "full"
        print(f"Running sync using {type(source).__name__} ({mode_desc})...")
    else:
        print(f"Running sync using {type(source).__name__}...")

    try:
        # Order matters: customers and products must exist before
        # orders/line_items reference them via foreign key.
        sync_customers(source, supabase, updated_since)
        sync_products(source, supabase, updated_since)
        sync_orders(source, supabase, updated_since)
    except Exception as exc:
        # Printed (not raised as a new exception) so the original traceback
        # -- still useful for debugging -- keeps printing normally right
        # after this. Re-raising preserves the non-zero exit code that
        # tells GitHub Actions (and anyone running this by hand) the run
        # failed.
        print(f"SYNC_FAILURE_REASON: {_describe_failure(exc)}")
        raise

    if is_live:
        # 5-minute overlap buffer: guards against clock skew between this
        # machine and Shopify, and against a record that finished writing
        # just as this run started but wasn't visible to the query yet.
        # Small, safe amount of re-fetched overlap next run rather than a
        # risk of silently skipping something.
        watermark = (sync_started_at - timedelta(minutes=5)).isoformat()
        _set_last_synced_at(supabase, watermark)

    print("Sync complete.")


if __name__ == "__main__":
    main()
