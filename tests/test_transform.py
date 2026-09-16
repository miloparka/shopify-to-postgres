"""
Regression tests for sync/transform.py's discount handling.

Context: order_line_items.total_discount was found to always read 0.00 in
production even on orders with a real discount, because the sync read
LineItem.totalDiscountSet -- which Shopify's own docs say "doesn't include
order-level discounts" (a discount code or automatic discount applied to
the whole order, as opposed to one entered directly on a line, never shows
up there). The fix sums LineItem.discountAllocations instead, which covers
discounts from any source. These tests pin that behavior down so it can't
silently regress back to the old (broken) field.
"""

import json
from pathlib import Path

from sync.transform import _sum_discount_allocations, transform_order

DEMO_DATA_DIR = Path(__file__).parent.parent / "demo_data"


def test_sum_discount_allocations_multiple():
    allocations = [
        {"allocatedAmountSet": {"shopMoney": {"amount": "2.76"}}},
        {"allocatedAmountSet": {"shopMoney": {"amount": "1.14"}}},
    ]
    assert _sum_discount_allocations(allocations) == 3.90


def test_sum_discount_allocations_empty_or_missing():
    assert _sum_discount_allocations([]) == 0.0
    assert _sum_discount_allocations(None) == 0.0


def test_transform_order_line_item_discount_from_order_level_code():
    """The exact bug scenario: an order-level discount code (not a
    per-line discount) should show up on each affected line item's
    total_discount, and the line items should sum back to the order's own
    total_discounts -- not read 0.00 like the old totalDiscountSet-based
    code did."""
    data = json.loads((DEMO_DATA_DIR / "orders_response.json").read_text())
    orders = {edge["node"]["name"]: edge["node"] for edge in data["data"]["orders"]["edges"]}

    node = orders["#1003"]  # has discountCodes: ["WELCOME10"]
    order_row, line_items, _ = transform_order(node)

    assert order_row["total_discounts"] == 5.90
    assert [li["total_discount"] for li in line_items] == [2.76, 1.56, 1.58]
    assert round(sum(li["total_discount"] for li in line_items), 2) == 5.90


def test_transform_order_line_item_discount_zero_when_undiscounted():
    data = json.loads((DEMO_DATA_DIR / "orders_response.json").read_text())
    orders = {edge["node"]["name"]: edge["node"] for edge in data["data"]["orders"]["edges"]}

    node = orders["#1001"]  # no discount code, no line-level discount
    order_row, line_items, _ = transform_order(node)

    assert order_row["total_discounts"] == 0.0
    assert all(li["total_discount"] == 0.0 for li in line_items)

    """Tests for sync/transform.py, focused on the per-line tax capture
(order_line_item_tax_lines / order_shipping_line_tax_lines) added on top
of the existing discount-allocation fix.

Run with: pytest
"""

from data_source.demo_source import DemoDataSource
from sync.transform import (
    _map_tax_lines,
    transform_order,
    transform_shipping_line_tax_lines,
)


# ----------------------------------------------------------------------------
# _map_tax_lines -- the shared TaxLine mapper
# ----------------------------------------------------------------------------

def test_map_tax_lines_maps_all_fields():
    raw = [{
        "title": "VAT",
        "rate": 0.255,
        "ratePercentage": 25.5,
        "priceSet": {"shopMoney": {"amount": "1.66"}},
        "source": "Shopify",
        "channelLiable": False,
    }]
    rows = _map_tax_lines(raw)
    assert rows == [{
        "title": "VAT",
        "rate": 0.255,
        "rate_percentage": 25.5,
        "amount": 1.66,
        "source": "Shopify",
        "channel_liable": False,
    }]


def test_map_tax_lines_handles_multiple_lines():
    raw = [
        {"title": "State VAT", "rate": 0.1, "ratePercentage": 10.0,
         "priceSet": {"shopMoney": {"amount": "1.00"}}, "source": "A", "channelLiable": None},
        {"title": "Local VAT", "rate": 0.02, "ratePercentage": 2.0,
         "priceSet": {"shopMoney": {"amount": "0.20"}}, "source": "B", "channelLiable": None},
    ]
    rows = _map_tax_lines(raw)
    assert len(rows) == 2
    assert rows[0]["title"] == "State VAT"
    assert rows[1]["title"] == "Local VAT"


def test_map_tax_lines_handles_none_and_empty():
    assert _map_tax_lines(None) == []
    assert _map_tax_lines([]) == []


def test_map_tax_lines_handles_missing_optional_fields():
    raw = [{"title": "VAT"}]  # no rate/ratePercentage/priceSet/source/channelLiable
    rows = _map_tax_lines(raw)
    assert rows == [{
        "title": "VAT",
        "rate": None,
        "rate_percentage": None,
        "amount": None,
        "source": None,
        "channel_liable": None,
    }]


# ----------------------------------------------------------------------------
# transform_order -- now returns (order_row, line_item_rows, tax_line_rows)
# ----------------------------------------------------------------------------

def _line_item_node(li_id, tax_lines=None):
    node = {
        "id": f"gid://shopify/LineItem/{li_id}",
        "title": "Test Item",
        "sku": "SKU1",
        "quantity": 1,
        "currentQuantity": 1,
        "originalUnitPriceSet": {"shopMoney": {"amount": "10.00"}},
        "discountAllocations": [],
        "product": {"id": "gid://shopify/Product/1"},
        "variant": {"id": "gid://shopify/ProductVariant/11"},
    }
    if tax_lines is not None:
        node["taxLines"] = tax_lines
    return {"node": node}


def _order_node(order_id, line_items, shipping_line=None):
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "name": f"#{order_id}",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "processedAt": "2026-01-01T00:00:00Z",
        "cancelledAt": None,
        "cancelReason": None,
        "closedAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "sourceName": "web",
        "tags": [],
        "discountCodes": [],
        "currentTotalPriceSet": {"shopMoney": {"amount": "10.00", "currencyCode": "EUR"}},
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "10.00"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00"}},
        "currentTotalDiscountsSet": {"shopMoney": {"amount": "0.00"}},
        "currentShippingPriceSet": {"shopMoney": {"amount": "0.00"}},
        "shippingLine": shipping_line,
        "shippingAddress": {"country": "Finland", "province": "Uusimaa", "city": "Helsinki"},
        "customer": {"id": "gid://shopify/Customer/1"},
        "lineItems": {"edges": line_items},
    }


def test_transform_order_returns_three_tuple_with_tax_lines():
    tax_lines = [{
        "title": "VAT", "rate": 0.135, "ratePercentage": 13.5,
        "priceSet": {"shopMoney": {"amount": "1.35"}},
        "source": "Shopify", "channelLiable": False,
    }]
    node = _order_node(999, [_line_item_node(9001, tax_lines=tax_lines)])

    order_row, line_item_rows, line_item_tax_line_rows = transform_order(node)

    assert order_row["id"] == 999
    assert len(line_item_rows) == 1
    assert line_item_rows[0]["id"] == 9001
    assert line_item_tax_line_rows == [{
        "title": "VAT",
        "rate": 0.135,
        "rate_percentage": 13.5,
        "amount": 1.35,
        "source": "Shopify",
        "channel_liable": False,
        "line_item_id": 9001,
    }]


def test_transform_order_line_item_without_tax_lines_key_produces_no_rows():
    node = _order_node(998, [_line_item_node(9002)])  # no taxLines key at all

    _, line_item_rows, line_item_tax_line_rows = transform_order(node)

    assert len(line_item_rows) == 1
    assert line_item_tax_line_rows == []


def test_transform_order_multiple_line_items_keep_tax_lines_separate():
    tax_a = [{"title": "VAT", "rate": 0.135, "ratePercentage": 13.5,
              "priceSet": {"shopMoney": {"amount": "0.24"}}, "source": "Shopify", "channelLiable": False}]
    tax_b = [{"title": "VAT", "rate": 0.255, "ratePercentage": 25.5,
              "priceSet": {"shopMoney": {"amount": "1.66"}}, "source": "Shopify", "channelLiable": False}]
    node = _order_node(997, [
        _line_item_node(9003, tax_lines=tax_a),
        _line_item_node(9004, tax_lines=tax_b),
    ])

    _, _, line_item_tax_line_rows = transform_order(node)

    by_line_item = {row["line_item_id"]: row for row in line_item_tax_line_rows}
    assert by_line_item[9003]["rate"] == 0.135
    assert by_line_item[9004]["rate"] == 0.255


# ----------------------------------------------------------------------------
# transform_shipping_line_tax_lines
# ----------------------------------------------------------------------------

def test_transform_shipping_line_tax_lines_keyed_by_order_id():
    shipping_line = {
        "title": "Standard Shipping",
        "code": "STANDARD",
        "originalPriceSet": {"shopMoney": {"amount": "3.00"}},
        "taxLines": [{
            "title": "VAT", "rate": 0.255, "ratePercentage": 25.5,
            "priceSet": {"shopMoney": {"amount": "0.77"}},
            "source": "Shopify", "channelLiable": False,
        }],
    }
    node = _order_node(201, [], shipping_line=shipping_line)

    rows = transform_shipping_line_tax_lines(node)

    assert rows == [{
        "title": "VAT",
        "rate": 0.255,
        "rate_percentage": 25.5,
        "amount": 0.77,
        "source": "Shopify",
        "channel_liable": False,
        "order_id": 201,
    }]


def test_transform_shipping_line_tax_lines_no_shipping_line():
    node = _order_node(202, [], shipping_line=None)
    assert transform_shipping_line_tax_lines(node) == []


def test_transform_shipping_line_tax_lines_free_shipping_no_tax():
    shipping_line = {
        "title": "Store Pickup",
        "code": "PICKUP",
        "originalPriceSet": {"shopMoney": {"amount": "0.00"}},
        "taxLines": [],
    }
    node = _order_node(204, [], shipping_line=shipping_line)
    assert transform_shipping_line_tax_lines(node) == []


def test_transform_shipping_line_tax_lines_missing_key_is_backward_compatible():
    # No "taxLines" key at all -- simulates a cached/older response shaped
    # before this field was added to the query.
    shipping_line = {
        "title": "Standard Shipping",
        "code": "STANDARD",
        "originalPriceSet": {"shopMoney": {"amount": "3.00"}},
    }
    node = _order_node(205, [], shipping_line=shipping_line)
    assert transform_shipping_line_tax_lines(node) == []


# ----------------------------------------------------------------------------
# Integration: the real demo fixture (demo_data/orders_response.json)
# ----------------------------------------------------------------------------

def test_demo_fixture_mixes_reduced_and_standard_rates_within_one_order():
    """Order #1002 mixes a standard-rated non-food item (board game) with
    reduced-rated food items, plus its own separately-rated shipping --
    exactly the breakdown a single order-level tax total can't represent."""
    source = DemoDataSource()
    orders = source.get_orders()
    order_202 = next(o for o in orders if o["name"] == "#1002")

    _, line_item_rows, tax_rows = transform_order(order_202)
    shipping_tax_rows = transform_shipping_line_tax_lines(order_202)

    tax_by_line_item_id = {row["line_item_id"]: row["rate"] for row in tax_rows}
    board_game = next(li for li in line_item_rows if li["title"] == "Family Board Game")
    oat_porridge = next(li for li in line_item_rows if li["title"] == "Oat Porridge 1kg")

    assert tax_by_line_item_id[board_game["id"]] == 0.255  # standard rate
    assert tax_by_line_item_id[oat_porridge["id"]] == 0.135  # reduced rate
    assert shipping_tax_rows[0]["rate"] == 0.255  # shipping taxed at the standard rate,
                                                    # independently of either line item


def test_demo_fixture_handles_order_with_no_captured_tax_lines():
    """Order #1005 has neither line-item nor shipping tax lines captured
    (simulating data from before this feature) -- must not crash, and
    must simply produce zero tax-line rows rather than raising."""
    source = DemoDataSource()
    orders = source.get_orders()
    order_205 = next(o for o in orders if o["name"] == "#1005")

    _, line_item_rows, tax_rows = transform_order(order_205)
    shipping_tax_rows = transform_shipping_line_tax_lines(order_205)

    assert len(line_item_rows) == 1
    assert tax_rows == []
    assert shipping_tax_rows == []


def test_demo_fixture_handles_free_shipping_with_no_tax_line():
    """Order #1004 (Store Pickup, price 0.00) has an explicit empty
    taxLines list on its shipping line -- a real, legitimate zero, not a
    missing-data gap."""
    source = DemoDataSource()
    orders = source.get_orders()
    order_204 = next(o for o in orders if o["name"] == "#1004")

    assert transform_shipping_line_tax_lines(order_204) == []
