import json
from pathlib import Path

from .interface import ShopifyDataSource

DEMO_DATA_DIR = Path(__file__).parent.parent / "demo_data"


class DemoDataSource(ShopifyDataSource):
    """Reads pre-saved JSON files shaped exactly like Shopify's GraphQL
    Admin API responses. Used for local development, demos, and the
    public/portfolio version of this repo — no real Shopify credentials
    or network access required.
    """

    def get_products(self, updated_since: str | None = None) -> list[dict]:
        # updated_since is ignored -- the demo dataset is a small static
        # fixture, so there's nothing to filter and every call returns
        # everything, same as a full sync.
        data = self._load("products_response.json")
        return [edge["node"] for edge in data["data"]["products"]["edges"]]

    def get_customers(self, updated_since: str | None = None) -> list[dict]:
        data = self._load("customers_response.json")
        return [edge["node"] for edge in data["data"]["customers"]["edges"]]

    def get_orders(self, updated_since: str | None = None) -> list[dict]:
        data = self._load("orders_response.json")
        return [edge["node"] for edge in data["data"]["orders"]["edges"]]

    def _load(self, filename: str) -> dict:
        path = DEMO_DATA_DIR / filename
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
