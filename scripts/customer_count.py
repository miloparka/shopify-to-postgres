"""
Quick, standalone exploration: asks Shopify directly for the total customer
count via the customersCount query, instead of paginating through every
customer record to find out (which is what the main sync does anyway, but
this is much cheaper if you just want the number).

Usage:
    python -m scripts.customer_count

Requires the same SHOPIFY_STORE_URL + (SHOPIFY_ACCESS_TOKEN or
SHOPIFY_CLIENT_ID/SHOPIFY_CLIENT_SECRET) in .env as the main sync.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

STORE_URL = os.environ["SHOPIFY_STORE_URL"]
ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

# customersCount defaults to capping out at 10,000 -- limit: null removes
# that cap so you get the real total, not just "at least 10000".
QUERY = """
{
  customersCount(limit: null) {
    count
    precision
  }
}
"""


def main():
    if not ACCESS_TOKEN:
        raise RuntimeError(
            "This quick script only supports the static SHOPIFY_ACCESS_TOKEN "
            "auth mode for simplicity -- set that in .env (or ask for the "
            "client-credentials version if you're using SHOPIFY_CLIENT_ID/SECRET)."
        )

    response = requests.post(
        f"https://{STORE_URL}/admin/api/2026-07/graphql.json",
        json={"query": QUERY},
        headers={
            "X-Shopify-Access-Token": ACCESS_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    if "errors" in payload:
        raise RuntimeError(f"Shopify GraphQL error: {payload['errors']}")

    result = payload["data"]["customersCount"]
    print(f"Total customers: {result['count']} ({result['precision']})")


if __name__ == "__main__":
    main()