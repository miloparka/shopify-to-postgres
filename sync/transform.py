"""
Transform raw Shopify-shaped nodes (nested JSON) into flat dicts matching
the actual Supabase table columns: customers, products, product_variants,
product_images, orders, order_line_items, order_shipping_lines.

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


def transform_order(node: dict) -> tuple[dict, list[dict]]:
    """Returns (order_row, line_item_rows) -- an order and its line items
    arrive nested in one node, so they're unpacked together."""
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
    for edge in node["lineItems"]["edges"]:
        li = edge["node"]
        product = li.get("product")
        variant = li.get("variant")
        line_item_rows.append({
            "id": extract_numeric_id(li["id"]),
            "order_id": extract_numeric_id(node["id"]),
            "product_id": extract_numeric_id(product["id"]) if product else None,
            "variant_id": extract_numeric_id(variant["id"]) if variant else None,
            "title": li["title"],
            "sku": li.get("sku"),
            "quantity": li["quantity"],
            "price": _money(li.get("originalUnitPriceSet")),
            "total_discount": _money(li.get("totalDiscountSet")),
            "fulfillment_status": li.get("fulfillmentStatus"),
        })

    return order_row, line_item_rows


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
