def _report(p, edge):
    return next(r for r in p.reports if r.edge == edge)


def test_every_edge_is_gated(pipeline):
    edges = {r.edge for r in pipeline.reports}
    assert "seed->documentsdb.products" in edges
    assert "documentsdb.products->vectorsdb.product_vectors" in edges
    assert "tablesdb.carts->postgresql.orders" in edges
    assert "tablesdb+postgresql->mysql.crm_customers" in edges
    assert "mysql.crm_customers->tablesdb.users" in edges


def test_bad_seed_rows_never_land(pipeline):
    s = pipeline.stores
    assert "SKU-0099" not in {p["sku"] for p in s.documents.read("products")}
    assert "u_dex" not in {u["user_id"] for u in s.tables.read("users")}
    assert "c_005" not in {c["cart_id"] for c in s.tables.read("carts")}


def test_checkout_writes_orders_and_payments(pipeline):
    s = pipeline.stores
    orders = s.postgres.read("orders")
    assert len(orders) == 4
    assert sum(o["total_cents"] for o in orders) == 12900 + 2 * 1800 + 8900 + 3 * 2200
    assert len(s.postgres.read("payments")) == 4
    assert {c["status"] for c in s.tables.read("carts")} == {"checked_out"}


def test_crm_gets_lifetime_value(pipeline):
    crm = {r["cust_id"]: r for r in pipeline.stores.mysql.read("crm_customers")}
    assert crm["u_ana"]["lifetime_cents"] == 12900 + 3600


def test_crm_drift_is_quarantined_not_synced(pipeline):
    users = {u["user_id"]: u for u in pipeline.stores.tables.read("users")}
    # Ben's drifted CRM row (bad email, unknown segment) must not overwrite TablesDB
    assert users["u_ben"]["email"] == "ben@example.com"
    assert users["u_ben"]["tier"] == "vip"
    # Eve's clean CRM-only row flows back
    assert users["u_eve"]["tier"] == "guest"
    drift = [q for q in pipeline.quarantine if q.edge == "mysql.crm_customers(read)"]
    assert len(drift) == 1 and drift[0].record["cust_id"] == "u_ben"


def test_semantic_product_search(pipeline):
    hits = pipeline.search_products("waterproof jacket for rain")
    assert hits[0]["metadata"]["sku"] == "SKU-0001"


def test_rerun_is_idempotent(pipeline):
    before = len(pipeline.stores.postgres.read("orders"))
    pipeline.checkout()  # no open carts left
    assert len(pipeline.stores.postgres.read("orders")) == before
