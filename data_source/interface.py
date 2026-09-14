"""
Defines the contract every data source must implement.

The sync scripts only ever call these three methods. They don't know
or care whether the data came from a local JSON file or a live
Shopify GraphQL API call — that's the whole point of this interface.
Swapping DemoDataSource for LiveShopifyDataSource requires no changes
anywhere else in the codebase.
"""

from abc import ABC, abstractmethod


class ShopifyDataSource(ABC):
    @abstractmethod
    def get_products(self, updated_since: str | None = None) -> list[dict]:
        """Return a list of raw product nodes (Shopify GraphQL shape).

        updated_since: an ISO-8601 timestamp. When given, implementations
        that support it should return only records updated at or after
        that time (for incremental syncs). Implementations that don't
        support filtering (e.g. static demo data) may ignore it and
        always return everything.
        """
        raise NotImplementedError

    @abstractmethod
    def get_customers(self, updated_since: str | None = None) -> list[dict]:
        """Return a list of raw customer nodes (Shopify GraphQL shape).
        See get_products for what updated_since does."""
        raise NotImplementedError

    @abstractmethod
    def get_orders(self, updated_since: str | None = None) -> list[dict]:
        """Return a list of raw order nodes (Shopify GraphQL shape), each
        including nested customer reference and line items.
        See get_products for what updated_since does."""
        raise NotImplementedError
