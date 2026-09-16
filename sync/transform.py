"""
Transform raw Shopify-shaped nodes (nested JSON) into flat dicts matching
the actual Supabase table columns: customers, products, product_variants,
product_images, orders, order_line_items, order_shipping_lines,
order_line_item_tax_lines, order_shipping_line_tax_lines.

This is the one place that has to know about both shapes -- everything
upstream (data sources) and downstream (the DB client) stays simple.

PII note: the GraphQL queries in data_source/live_shopify_source.py never
request name, email, phone, or street-address fields in the first place --
so there's nothing identifying to strip here. Geography is kept at
country/province/city only (from defaultAddress / shippingAddress), never
street address or postal code.
"""


def extract_numeric_id(gid: str) -> int:
    """Shopify GraphQL IDs look like 'gid://shopify/Product/101' -- pull
    out just the numeric part to use as our primary key."""
    return int(gid.rstrip("/").split("/")[-1])


def _money(price_set: dict | None) -> float | None:
    """Pull shopMoney.amount out of a Shopify MoneyBag, if present."""
    if not price_set:
        return None
    amount = (price_set.get("shopMoney") or {}).get("amount")
    return float(amount) if amount is not None else None


def _sum_discount_allocations(allocations: list[dict] | None) -> float:
    """Sum a LineItem's discountAllocations into a single total_discount
    figure. Deliberately NOT reading LineItem.totalDiscountSet -- per
    Shopify's own docs that field "doesn't include order-level discounts",
    so a discount code or automatic discount applied to the whole order
    (as opposed to one entered directly on a specific line) never shows up
    there, and it silently reads 0.00 on a genuinely discounted line.
    discountAllocations is the complete list of discounts apportioned to
    this line regardless of where the discount was applied, so summing it
    is the correct total. An order with no discount at all simply has an
    empty list here, which sums to 0.0 -- same result as before for the
    common case, just correct now for the discounted one too."""
    if not allocations:
        return 0.0
    total = 0.0
    for allocation in allocations:
        amount = ((allocation.get("allocatedAmountSet") or {}).get("shopMoney") or {}).get("amount")
        if amount is not None:
            total += float(amount)
    # Round to cents: summing several string-decimal amounts as floats can
    # otherwise leave a value like 3.8999999999999995 that's cosmetically
    # wrong (though the numeric(12,2) column would round it on write anyway).
    return round(total, 2)


def _map_tax_lines(tax_lines: list[dict] | None) -> list[dict]:
    """Map Shopify's raw TaxLine nodes (title, rate, ratePercentage,
    priceSet, source, channelLiable) into flat dicts with the common
    columns shared by order_line_item_tax_lines and
    order_shipping_line_tax_lines -- same TaxLine shape appears on both
    LineItem and ShippingLine, just attached to a different parent, so one
    mapper covers both. The caller adds whichever foreign key column
    (line_item_id / order_id) applies for its parent.

    Deliberately NOT reading Order.taxLines/currentTaxLines here -- that's
    the order-level aggregate this schema already captures as
    orders.total_tax. This only handles the per-line/per-shipping
    breakdown that a single order-level number collapses away, which is
    the actual gap: Shopify only ever showed one order-level tax total
    before this, even though it always had the real per-line rates.
    """
    rows = []
    for tax_line in tax_lines or []:
        rows.append({
            "title": tax_line.get("title"),
            "rate": float(tax_line["rate"]) if tax_line.get("rate") is not None else None,
            "rate_percentage": float(tax_line["ratePercentage"])
            if tax_line.get("ratePercentage") is not None
            else None,
            "amount": _money(tax_line.get("priceSet")),
            "source": tax_line.get("source"),
            "channel_liable": tax_line.get("channelLiable"),
        })
    return rows


def _prorate_for_current_quantity(discount: float, quantity: int, current_quantity: int) -> float:
    """Scale a line's total discount down to reflect only its still-active
    (non-refunded, non-removed) quantity.

    Why this is needed: LineItem.discountAllocations includes discounts
    allocated to refunded/removed units (per Shopify's own docs), but every
    other financial field this schema reads at the order level
    (orders.total_discounts, total_price, subtotal_price, ...) comes from
    Shopify's current*Set fields, which already net refunds/edits out. So
    without this adjustment, a partially or fully refunded line keeps
    reporting its full original discount forever, while the order-level
    total it's supposed to add up to has already dropped -- this is
    exactly what production order #66678 showed: order-level
    total_discounts read 0.00 after a refund, while the line's raw
    discountAllocations sum still read its original, pre-refund value.

    quantity is the line's original ordered quantity (including refunded/
    removed units); current_quantity is what's left after refunds/removals
    (Shopify's own distinction: LineItem.quantity vs LineItem.currentQuantity).
    This assumes the discount was distributed evenly per unit across the
    line, which holds for ordinary percentage/fixed discounts -- a
    non-uniform discount (e.g. a tiered "buy 2 get 1 free" applied
    asymmetrically across units) could prorate slightly differently than
    Shopify's own internal accounting, but there's no Shopify field that
    exposes an exact current-discount amount directly to check against."""
    if quantity <= 0:
        return 0.0
    current_quantity = max(0, min(current_quantity, quantity))
    return round(discount * current_quantity / quantity, 2)


def transform_customer(node: dict) -> dict:
    address = node.get("defaultAddress") or {}
    marketing = node.get("defaultEmailAddress") or {}

    return {
        "id": extract_numeric_id(node["id"]),
        "state": node.get("state"),
        "verified_email": node.get("verifiedEmail"),
        "accepts_marketing": marketing.get("marketingState") == "SUBSCRIBED"
        if marketing.get("marketingState") is not None
        else None,
        "tax_exempt": node.get("taxExempt"),
        "currency": node.get("amountSpent", {}).get("currencyCode"),
        "orders_count": int(node["numberOfOrders"]) if node.get("numberOfOrders") is not None else None,
        "total_spent": float(node["amountSpent"]["amount"]) if node.get("amountSpent") else None,
        "tags": node.get("tags") or [],
        "customer_locale": node.get("locale"),
        "country": address.get("country"),
        "province": address.get("province"),
        "city": address.get("city"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
    }


def transform_product(node: dict) -> dict:
    # package_type comes from a custom metafield, if present at all --
    # this mirrors the real inconsistent-vendor-data pattern: some
    # products simply won't have it.
    package_type = None
    for edge in node.get("metafields", {}).get("edges", []):
        mf = edge["node"]
        if mf["key"] == "package_type":
            package_type = mf["value"]
            break

    return {
        "id": extract_numeric_id(node["id"]),
        "title": node["title"],
        "body_html": node.get("descriptionHtml"),
        "vendor": node.get("vendor"),
        "product_type": node.get("productType"),
        "handle": node.get("handle"),
        "status": node.get("status"),
        "tags": node.get("tags") or [],
        "package_type": package_type,
        "published_at": node.get("publishedAt"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
    }


def transform_variants(node: dict, product_id: int) -> list[dict]:
    rows = []
    for edge in node.get("variants", {}).get("edges", []):
        v = edge["node"]
        # weight/weightUnit/requiresShipping live on the variant's
        # InventoryItem in the Admin API, not directly on ProductVariant.
        inventory_item = v.get("inventoryItem") or {}
        weight = (inventory_item.get("measurement") or {}).get("weight") or {}
        rows.append({
            "id": extract_numeric_id(v["id"]),
            "product_id": product_id,
            "title": v.get("title"),
            "sku": v.get("sku"),
            "barcode": v.get("barcode"),
            "price": float(v["price"]) if v.get("price") is not None else None,
            "compare_at_price": float(v["compareAtPrice"]) if v.get("compareAtPrice") is not None else None,
            "inventory_quantity": v.get("inventoryQuantity"),
            "weight": weight.get("value"),
            "weight_unit": weight.get("unit"),
            "requires_shipping": inventory_item.get("requiresShipping"),
            "taxable": v.get("taxable"),
            "position": v.get("position"),
            "created_at": v.get("createdAt"),
            "updated_at": v.get("updatedAt"),
        })
    return rows


def transform_images(node: dict, product_id: int) -> list[dict]:
    rows = []
    for position, edge in enumerate(node.get("images", {}).get("edges", []), start=1):
        img = edge["node"]
        rows.append({
            "id": extract_numeric_id(img["id"]),
            "product_id": product_id,
            "src": img.get("src"),
            "alt": img.get("altText"),
            "position": position,  # Shopify's Image type doesn't expose position directly;
                                    # edges are already returned in display order.
        })
    return rows


def transform_order(node: dict) -> tuple[dict, list[dict], list[dict]]:
    """Returns (order_row, line_item_rows, line_item_tax_line_rows) -- an
    order, its line items, and each line item's own tax lines all arrive
    nested in one node, so they're unpacked together."""
    customer = node.get("customer")
    shipping_addr = node.get("shippingAddress") or {}
    shipping_line = node.get("shippingLine") or {}

    order_row = {
        "id": extract_numeric_id(node["id"]),
        "customer_id": extract_numeric_id(customer["id"]) if customer else None,
        "order_number": node["name"],
        "currency": (node.get("currentTotalPriceSet") or {}).get("shopMoney", {}).get("currencyCode"),
        "financial_status": node.get("displayFinancialStatus"),
        "fulfillment_status": node.get("displayFulfillmentStatus"),
        "total_price": _money(node.get("currentTotalPriceSet")),
        "subtotal_price": _money(node.get("currentSubtotalPriceSet")),
        "total_tax": _money(node.get("currentTotalTaxSet")),
        "total_discounts": _money(node.get("currentTotalDiscountsSet")),
        "total_shipping": _money(node.get("currentShippingPriceSet")),
        "source_name": node.get("sourceName"),
        "tags": node.get("tags") or [],
        "discount_codes": node.get("discountCodes") or [],
        "shipping_country": shipping_addr.get("country"),
        "shipping_province": shipping_addr.get("province"),
        "shipping_city": shipping_addr.get("city"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "processed_at": node.get("processedAt"),
        "cancelled_at": node.get("cancelledAt"),
        "cancel_reason": node.get("cancelReason"),
        "closed_at": node.get("closedAt"),
    }

    line_item_rows = []
    line_item_tax_line_rows = []
    for edge in node["lineItems"]["edges"]:
        li = edge["node"]
        product = li.get("product")
        variant = li.get("variant")
        quantity = li["quantity"]
        # Falls back to quantity (i.e. "nothing refunded") if currentQuantity
        # is ever missing, e.g. an older cached response shaped before this
        # field was added to the query -- never divides by a smaller number
        # than what's actually there.
        current_quantity = li.get("currentQuantity", quantity)
        raw_discount = _sum_discount_allocations(li.get("discountAllocations"))
        line_item_id = extract_numeric_id(li["id"])
        line_item_rows.append({
            "id": line_item_id,
            "order_id": extract_numeric_id(node["id"]),
            "product_id": extract_numeric_id(product["id"]) if product else None,
            "variant_id": extract_numeric_id(variant["id"]) if variant else None,
            "title": li["title"],
            "sku": li.get("sku"),
            "quantity": quantity,
            "price": _money(li.get("originalUnitPriceSet")),
            "total_discount": _prorate_for_current_quantity(raw_discount, quantity, current_quantity),
            "fulfillment_status": li.get("fulfillmentStatus"),
        })
        for tax_row in _map_tax_lines(li.get("taxLines")):
            tax_row["line_item_id"] = line_item_id
            line_item_tax_line_rows.append(tax_row)

    return order_row, line_item_rows, line_item_tax_line_rows


def transform_shipping_line(node: dict) -> dict | None:
    shipping_line = node.get("shippingLine")
    if not shipping_line:
        return None
    return {
        "order_id": extract_numeric_id(node["id"]),
        "title": shipping_line.get("title"),
        "price": _money(shipping_line.get("originalPriceSet")),
        "code": shipping_line.get("code"),
    }


def transform_shipping_line_tax_lines(node: dict) -> list[dict]:
    """Returns the order's shipping-line tax lines, keyed by order_id.

    Keyed by order_id rather than order_shipping_lines' own id on purpose:
    that id is a synthetic `generated always as identity` column that gets
    a fresh value every sync (order_shipping_lines is deleted and
    reinserted per order, never upserted -- see sync/sync_all.py), so a
    child table FK'd to it would go stale the moment a new id was
    assigned. order_id is stable, and today's query only ever returns one
    shipping line per order (Order.shippingLine, the singular deprecated
    field -- not the shippingLines connection), so it's already
    effectively a 1:1 key here.
    """
    shipping_line = node.get("shippingLine")
    if not shipping_line:
        return []
    order_id = extract_numeric_id(node["id"])
    rows = _map_tax_lines(shipping_line.get("taxLines"))
    for row in rows:
        row["order_id"] = order_id
    return rows
