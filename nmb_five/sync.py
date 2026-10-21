"""Sync jobs: every edge where data moves between stores goes through
DataContractGate. Passing records are written; failures are kept in a
quarantine list and later embedded into the VectorsDB contract map.

Edges
  seed       -> DocumentsDB.products          (product)
  seed       -> TablesDB.users / carts        (user, cart)
  DocumentsDB.products -> VectorsDB.product_vectors   (product_embedding)
  TablesDB.carts + DocumentsDB.products -> PostgreSQL.orders / payments (order, payment)
  PostgreSQL.orders + TablesDB.users -> MySQL.crm_customers           (crm_customer)
  MySQL.crm_customers (drifted) -> TablesDB.users                     (user)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from . import seed
from .gate import Gate, QuarantinedRecord
from .stores import Stores

TIER_FROM_SEGMENT = {"NEW": "guest", "REGULAR": "member", "VIP": "vip"}
SEGMENT_FROM_TIER = {v: k for k, v in TIER_FROM_SEGMENT.items()}


@dataclass
class EdgeReport:
    edge: str
    contract: str
    passed: int
    quarantined: int


@dataclass
class Pipeline:
    stores: Stores
    gate: Gate = field(default_factory=Gate)
    quarantine: List[QuarantinedRecord] = field(default_factory=list)
    reports: List[EdgeReport] = field(default_factory=list)

    def _gate(self, contract: str, records: List[Dict[str, Any]], edge: str) -> List[Dict[str, Any]]:
        res = self.gate.check(contract, records, edge=edge)
        self.quarantine.extend(res.quarantined)
        self.reports.append(EdgeReport(edge, contract, len(res.passed), len(res.quarantined)))
        return res.passed

    # -- jobs -------------------------------------------------------------
    def load_seed(self) -> None:
        s = self.stores
        s.documents.upsert("products", self._gate("product", seed.PRODUCTS, "seed->documentsdb.products"), "sku")
        s.tables.upsert("users", self._gate("user", seed.USERS, "seed->tablesdb.users"), "user_id")
        s.tables.upsert("carts", self._gate("cart", seed.CARTS, "seed->tablesdb.carts"), "cart_id")
        s.tables.upsert("settings", seed.SETTINGS, "key")

    def catalog_to_vectors(self) -> None:
        s = self.stores
        products = s.documents.read("products")
        texts = [f"{p['title']}. {p['description']} {' '.join(p.get('tags', []) or [])}" for p in products]
        vecs = s.embedder.embed(texts) if texts else []
        docs = [{"embeddings": v, "metadata": {"sku": p["sku"], "title": p["title"], "category": p["category"]}}
                for p, v in zip(products, vecs)]
        ok = self._gate("product_embedding", docs, "documentsdb.products->vectorsdb.product_vectors")
        for d in ok:
            d["id"] = d["metadata"]["sku"]
        s.vectors.upsert("product_vectors", ok, key="id")

    def checkout(self) -> None:
        s = self.stores
        prices = {p["sku"]: p["price_cents"] for p in s.documents.read("products")}
        carts = s.tables.read("carts", {"status": "open"})
        orders, payments = [], []
        for c in carts:
            price = prices.get(c["sku"])
            orders.append({"order_id": f"o_{c['cart_id']}", "user_id": c["user_id"], "sku": c["sku"],
                           "quantity": c["quantity"], "total_cents": (price or 0) * c["quantity"], "status": "paid"})
        ok_orders = self._gate("order", orders, "tablesdb.carts->postgresql.orders")
        s.postgres.upsert("orders", ok_orders, "order_id")
        for o in ok_orders:
            payments.append({"payment_id": "p_" + o["order_id"][2:], "order_id": o["order_id"],
                             "amount_cents": o["total_cents"], "currency": "USD", "method": "card"})
        s.postgres.upsert("payments", self._gate("payment", payments, "postgresql.orders->postgresql.payments"),
                          "payment_id")
        done = {o["order_id"][2:] for o in ok_orders}
        s.tables.upsert("carts", [dict(c, status="checked_out") for c in carts if c["cart_id"] in done], "cart_id")

    def orders_to_crm(self) -> None:
        s = self.stores
        totals: Dict[str, int] = {}
        for o in s.postgres.read("orders"):
            totals[o["user_id"]] = totals.get(o["user_id"], 0) + int(o["total_cents"])
        rows = [{"cust_id": u["user_id"], "cust_email": u["email"], "customer_name": u["full_name"],
                 "lifetime_cents": totals.get(u["user_id"], 0), "segment": SEGMENT_FROM_TIER[u["tier"]]}
                for u in s.tables.read("users")]
        s.mysql.upsert("crm_customers", self._gate("crm_customer", rows, "tablesdb+postgresql->mysql.crm_customers"),
                       "cust_id")

    def simulate_crm_drift(self) -> None:
        """The legacy CRM app writes directly to MySQL, bypassing the gate."""
        self.stores.mysql.upsert("crm_customers", seed.CRM_DRIFT, "cust_id")

    def crm_to_users(self) -> None:
        s = self.stores
        crm = s.mysql.read("crm_customers")
        # Gate the CRM's own shape first, then the mapped TablesDB shape.
        good = self._gate("crm_customer", crm, "mysql.crm_customers(read)")
        mapped = [{"user_id": r["cust_id"], "email": r["cust_email"], "full_name": r["customer_name"],
                   "tier": TIER_FROM_SEGMENT.get(r["segment"], r["segment"])} for r in good]
        s.tables.upsert("users", self._gate("user", mapped, "mysql.crm_customers->tablesdb.users"), "user_id")

    def run_all(self) -> "Pipeline":
        self.load_seed()
        self.catalog_to_vectors()
        self.checkout()
        self.orders_to_crm()
        self.simulate_crm_drift()
        self.crm_to_users()
        return self

    # -- storefront helpers ----------------------------------------------
    def search_products(self, text: str, k: int = 3) -> List[Dict[str, Any]]:
        vec = self.stores.embedder.embed([text])[0]
        return self.stores.vectors.nearest("product_vectors", vec, k=k)
