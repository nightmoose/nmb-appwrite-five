"""Build the five stores, either local stand-ins or Appwrite Cloud."""

from __future__ import annotations

from dataclasses import dataclass

from .connectors import Connector, MemoryConnector, SQLConnector
from .embed import LocalEmbedder

# Same DDL works on sqlite, PostgreSQL and MySQL (IF NOT EXISTS, VARCHAR keys).
POSTGRES_SCHEMA = {
    "orders": "CREATE TABLE IF NOT EXISTS orders (order_id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64) NOT NULL,"
              " sku VARCHAR(16) NOT NULL, quantity INTEGER NOT NULL, total_cents INTEGER NOT NULL,"
              " status VARCHAR(16) NOT NULL)",
    "payments": "CREATE TABLE IF NOT EXISTS payments (payment_id VARCHAR(64) PRIMARY KEY, order_id VARCHAR(64) NOT NULL,"
                " amount_cents INTEGER NOT NULL, currency VARCHAR(3) NOT NULL, method VARCHAR(16) NOT NULL)",
}

# The legacy CRM: its own names, its own habits.
MYSQL_SCHEMA = {
    "crm_customers": "CREATE TABLE IF NOT EXISTS crm_customers (cust_id VARCHAR(64) PRIMARY KEY,"
                     " cust_email VARCHAR(254), customer_name VARCHAR(120), lifetime_cents INTEGER,"
                     " segment VARCHAR(16))",
}


@dataclass
class Stores:
    tables: Connector      # TablesDB: users, carts, settings
    documents: Connector   # DocumentsDB: products
    vectors: Connector     # VectorsDB: product_vectors, contract_map
    postgres: Connector    # Managed PostgreSQL: orders, payments
    mysql: Connector       # Managed MySQL: crm_customers
    embedder: object

    def all(self):
        return [self.tables, self.documents, self.vectors, self.postgres, self.mysql]


def local_stores() -> Stores:
    return Stores(
        tables=MemoryConnector("tablesdb", {"users": "user", "carts": "cart"}),
        documents=MemoryConnector("documentsdb", {"products": "product"}),
        vectors=MemoryConnector("vectorsdb", {"product_vectors": "product_embedding", "contract_map": "contract_map_entry"}),
        postgres=SQLConnector("postgresql", POSTGRES_SCHEMA, contracts={"orders": "order", "payments": "payment"}),
        mysql=SQLConnector("mysql", MYSQL_SCHEMA, contracts={"crm_customers": "crm_customer"}),
        embedder=LocalEmbedder(),
    )


def appwrite_stores() -> Stores:
    from .connectors.appwrite import (DocumentsDBConnector, MySQLConnector, PostgresConnector,
                                      TablesDBConnector, VectorsDBConnector, appwrite_client)
    from .embed import AppwriteEmbedder

    client = appwrite_client()
    return Stores(
        tables=TablesDBConnector(client),
        documents=DocumentsDBConnector(client),
        vectors=VectorsDBConnector(client),
        postgres=PostgresConnector(POSTGRES_SCHEMA),
        mysql=MySQLConnector(MYSQL_SCHEMA),
        embedder=AppwriteEmbedder(client),
    )


def build(mode: str = "local") -> Stores:
    return appwrite_stores() if mode == "appwrite" else local_stores()
