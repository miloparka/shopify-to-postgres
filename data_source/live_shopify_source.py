import os
import time

import requests

from .interface import ShopifyDataSource

# Operational note: by default `orders(...)` only returns orders from the
# last 60 days. Older orders require the `read_all_orders` scope (approved
# per-app by Shopify) or, for point-of-sale "quick sale" orders,
# `read_marketplace_orders` / `read_quick_sale` depending on order type --
# see Shopify's Orders access scopes docs if a full historical backfill is
# ever needed.
#
# Each query takes a $cursor variable for pagination (see _paginate below).
# Top-level connections use first: 50 per page; nested connections
# (variants, images, lineItems) are still capped at a single page each --
# fine for this store's catalog size, but if any product/order ever has
# more than 50 variants/images/line items, those would need their own
# nested pagination too.

PRODUCTS_QUERY = """
query Products($cursor: String, $query: String) {
  products(first: 50, after: $cursor, sortKey: ID, query: $query) {
    edges {
      node {
        id
        title
        descriptionHtml
        vendor
        productType
        handle
        status
        tags
        publishedAt
        createdAt
        updatedAt
        variants(first: 50) {
          edges {
            node {
              id
              title
              sku
              barcode
              price
              compareAtPrice
              inventoryQuantity
              taxable
              position
              inventoryItem {
                requiresShipping
                measurement {
                  weight {
                    value
                    unit
                  }
                }
              }
              createdAt
              updatedAt
            }
          }
        }
        images(first: 20) {
          edges {
            node {
              id
              src
              altText
            }
          }
        }
        metafields(first: 10, namespace: "custom") {
          edges { node { namespace key value } }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

CUSTOMERS_QUERY = """
query Customers($cursor: String, $query: String) {
  customers(first: 50, after: $cursor, sortKey: ID, query: $query) {
    edges {
      node {
        id
        state
        verifiedEmail
        taxExempt
        numberOfOrders
        amountSpent { amount currencyCode }
        tags
        locale
        defaultEmailAddress { marketingState }
        defaultAddress { country province city }
        createdAt
        updatedAt
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ORDERS_QUERY = """
query Orders($cursor: String, $query: String) {
  orders(first: 50, after: $cursor, sortKey: ID, query: $query) {
    edges {
      node {
        id
        name
        createdAt
        updatedAt
        processedAt
        cancelledAt
        cancelReason
        closedAt
        displayFinancialStatus
        displayFulfillmentStatus
        sourceName
        tags
        discountCodes
        currentTotalPriceSet { shopMoney { amount currencyCode } }
        currentSubtotalPriceSet { shopMoney { amount } }
        currentTotalTaxSet { shopMoney { amount } }
        currentTotalDiscountsSet { shopMoney { amount } }
        currentShippingPriceSet { shopMoney { amount } }
        shippingLine { title code originalPriceSet { shopMoney { amount } } }
        shippingAddress { country province city }
        customer { id }
        lineItems(first: 20) {
          edges {
            node {
              id
              title
              sku
              quantity
              currentQuantity
              fulfillmentStatus
              originalUnitPriceSet { shopMoney { amount } }
              discountAllocations { allocatedAmountSet { shopMoney { amount } } }
              product { id }
              variant { id }
            }
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class LiveShopifyDataSource(ShopifyDataSource):
    """Queries Shopify's real GraphQL Admin API. Requires SHOPIFY_STORE_URL
    and SHOPIFY_ACCESS_TOKEN environment variables to be set. This is what
    the company's production sync uses -- never run against your personal
    demo project.

    Paginates through every resource (cursor-based, via pageInfo) rather
    than fetching a single page, and backs off automatically when Shopify's
    GraphQL cost-based rate limiter throttles a request.
    """

    def __init__(self, max_retries: int = 5, request_timeout: int = 30):
        self.store_url = os.environ["SHOPIFY_STORE_URL"]  # e.g. your-store.myshopify.com
        # Two ways to authenticate, picked automatically based on what's set
        # in the environment:
        #   1. SHOPIFY_ACCESS_TOKEN -- a static, pre-generated token. This is
        #      what a legacy custom app (Settings > Apps and sales channels >
        #      Develop apps > Build legacy custom apps) hands you directly at
        #      install time -- no OAuth involved, never expires on its own.
        #   2. SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET -- a Dev Dashboard
        #      app's credentials, used with the client credentials grant
        #      (https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant).
        #      This only works when the app and the store are in the same
        #      Shopify organization (no merchant install/OAuth redirect
        #      needed), and the resulting token expires after 24 hours, so
        #      it's fetched fresh and cached here rather than stored in .env.
        self.access_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        self.client_id = os.environ.get("SHOPIFY_CLIENT_ID")
        self.client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
        if not self.access_token and not (self.client_id and self.client_secret):
            raise RuntimeError(
                "Set either SHOPIFY_ACCESS_TOKEN (legacy custom app) or both "
                "SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET (Dev Dashboard "
                "app, client credentials grant) in the environment."
            )
        self._client_credentials_token: str | None = None
        self._client_credentials_expires_at: float = 0.0

        # 2024-10 is retired: Shopify supports each API version for ~1 year
        # (4 quarterly releases) after launch, and 2024-10 launched Oct 2024.
        # 2026-07 is the current version per shopify.dev's Admin API reference
        # as of this writing -- confirm it's still current when you deploy,
        # since Shopify releases a new version every quarter.
        self.endpoint = f"https://{self.store_url}/admin/api/2026-07/graphql.json"
        self.max_retries = max_retries
        self.request_timeout = request_timeout

    def _get_access_token(self) -> str:
        """Return a valid Admin API access token, fetching/refreshing one
        via the client credentials grant if that's the auth mode in use."""
        if self.access_token:
            return self.access_token

        # Refresh a minute before actual expiry to avoid a request landing
        # right on the boundary.
        if self._client_credentials_token and time.time() < self._client_credentials_expires_at - 60:
            return self._client_credentials_token

        response = requests.post(
            f"https://{self.store_url}/admin/oauth/access_token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.request_timeout,
        )
        if not response.ok:
            raise RuntimeError(
                f"Client credentials grant failed ({response.status_code}): "
                f"{response.text} -- if this is 'shop_not_permitted', the app "
                f"and store aren't in the same Shopify organization; see "
                f"shopify.dev's client-credentials-grant troubleshooting."
            )
        payload = response.json()
        self._client_credentials_token = payload["access_token"]
        self._client_credentials_expires_at = time.time() + payload["expires_in"]
        return self._client_credentials_token

    def get_products(self, updated_since: str | None = None) -> list[dict]:
        return self._paginate(PRODUCTS_QUERY, "products", updated_since)

    def get_customers(self, updated_since: str | None = None) -> list[dict]:
        return self._paginate(CUSTOMERS_QUERY, "customers", updated_since)

    def get_orders(self, updated_since: str | None = None) -> list[dict]:
        return self._paginate(ORDERS_QUERY, "orders", updated_since)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    @staticmethod
    def _search_query_for(updated_since: str | None) -> str | None:
        """Build Shopify's search-query-string filter for `updated_since`.

        Shopify's `query:` connection argument takes a search DSL, not a
        GraphQL variable of its own -- `updated_at:>'<ISO8601 timestamp>'`
        filters a connection down to records touched at or after that
        time. Passing None (the default, full-sync case) leaves the
        connection unfiltered.
        """
        if not updated_since:
            return None
        return f"updated_at:>'{updated_since}'"

    def _paginate(
        self, query: str, root_field: str, updated_since: str | None = None
    ) -> list[dict]:
        """Follow pageInfo.hasNextPage/endCursor until Shopify reports no
        more pages, collecting every node from every page into one list.
        When updated_since is given, only records changed at or after
        that time are fetched -- see _search_query_for.
        """
        nodes: list[dict] = []
        cursor = None
        page = 0
        search_query = self._search_query_for(updated_since)

        while True:
            data = self._run_query(query, {"cursor": cursor, "query": search_query})
            connection = data[root_field]
            nodes.extend(edge["node"] for edge in connection["edges"])
            page += 1
            print(f"  ...{root_field}: fetched page {page} ({len(nodes)} so far)")

            page_info = connection["pageInfo"]
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info["endCursor"]

        return nodes

    # ------------------------------------------------------------------
    # Request + rate-limit handling
    # ------------------------------------------------------------------

    def _run_query(self, query: str, variables: dict | None = None) -> dict:
        """Run one GraphQL request, retrying with backoff on the errors that
        are actually transient, and failing fast on the ones that aren't.

        Per shopify.dev's Admin API reference, the GraphQL Admin API mostly
        signals rate limiting and other failures with HTTP 200 plus an
        `errors` array (not a 4xx/5xx status), each carrying an
        `extensions.code`:
          - THROTTLED           -- the cost-based rate limit bucket is empty.
                                    Retryable: wait for it to refill, using
                                    extensions.cost.throttleStatus.
          - MAX_COST_EXCEEDED    -- this *single* query costs more than the
                                    max per-query budget (1000 points). Not
                                    retryable by waiting -- the query itself
                                    needs a smaller page size (`first: N`).
          - INTERNAL_SERVER_ERROR -- transient failure on Shopify's side.
                                    Worth a short retry.
          - ACCESS_DENIED / SHOP_INACTIVE -- not retryable at all; surface
                                    immediately so it isn't mistaken for a
                                    transient blip.
        A plain HTTP 429 is handled too, as a defensive fallback, even
        though the docs indicate GraphQL requests don't normally return it.
        """
        variables = variables or {}
        backoff = 1.0

        for attempt in range(1, self.max_retries + 1):
            response = requests.post(
                self.endpoint,
                json={"query": query, "variables": variables},
                headers={
                    "X-Shopify-Access-Token": self._get_access_token(),
                    "Content-Type": "application/json",
                },
                timeout=self.request_timeout,
            )

            if response.status_code == 429:
                self._sleep_for_retry(response.headers.get("Retry-After"), backoff, attempt)
                backoff *= 2
                continue

            response.raise_for_status()
            payload = response.json()
            errors = payload.get("errors")

            if errors:
                codes = {(error.get("extensions") or {}).get("code") for error in errors}

                if "THROTTLED" in codes:
                    wait_seconds = self._throttle_wait_seconds(payload, default=backoff)
                    self._sleep_for_retry(wait_seconds, backoff, attempt)
                    backoff *= 2
                    continue

                if "MAX_COST_EXCEEDED" in codes:
                    raise RuntimeError(
                        f"Shopify GraphQL error: query cost exceeds the single-query max "
                        f"cost limit -- lower the page size (first: N) in this query rather "
                        f"than retrying: {errors}"
                    )

                if "INTERNAL_SERVER_ERROR" in codes and attempt < self.max_retries:
                    self._sleep_for_retry(backoff, backoff, attempt)
                    backoff *= 2
                    continue

                raise RuntimeError(f"Shopify GraphQL error: {errors}")

            return payload["data"]

        raise RuntimeError(
            f"Shopify GraphQL query still failing after {self.max_retries} retries -- "
            "consider lowering page size (first: N) or spacing out sync runs."
        )

    @staticmethod
    def _throttle_wait_seconds(payload: dict, default: float) -> float:
        """Shopify's GraphQL responses include an `extensions.cost` block
        with the current throttle bucket status. Use it to wait exactly as
        long as needed for the bucket to refill, instead of guessing."""
        cost = (payload.get("extensions") or {}).get("cost") or {}
        throttle_status = cost.get("throttleStatus") or {}
        requested_cost = cost.get("requestedQueryCost")
        available = throttle_status.get("currentlyAvailable")
        restore_rate = throttle_status.get("restoreRate")

        if requested_cost is not None and available is not None and restore_rate:
            deficit = requested_cost - available
            if deficit > 0:
                return max(deficit / restore_rate, 0.5)

        return default

    @staticmethod
    def _sleep_for_retry(retry_after, backoff: float, attempt: int) -> None:
        try:
            wait_seconds = float(retry_after) if retry_after is not None else backoff
        except (TypeError, ValueError):
            wait_seconds = backoff
        print(f"  Shopify rate limit hit (attempt {attempt}) -- waiting {wait_seconds:.1f}s...")
        time.sleep(wait_seconds)