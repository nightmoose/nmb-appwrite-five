import os

import pytest

from nmb_five.connectors import Connector, MemoryConnector, NotConfigured, SQLConnector
from nmb_five.embed import local_embed
from nmb_five.stores import MYSQL_SCHEMA, POSTGRES_SCHEMA, local_stores


def test_five_stores_one_interface():
    s = local_stores()
    types = [c.store_type for c in s.all()]
    assert types == ["tablesdb", "documentsdb", "vectorsdb", "postgresql", "mysql"]
    assert all(isinstance(c, Connector) for c in s.all())


def test_memory_upsert_and_filter():
    m = MemoryConnector("tablesdb")
    m.upsert("t", [{"id": "a", "x": 1}, {"id": "b", "x": 2}], "id")
    m.upsert("t", [{"id": "a", "x": 3}], "id")
    assert sorted(r["x"] for r in m.read("t")) == [2, 3]
    assert m.read("t", {"x": 2}) == [{"id": "b", "x": 2}]


def test_sql_upsert_roundtrip():
    pg = SQLConnector("postgresql", POSTGRES_SCHEMA)
    row = {"order_id": "o_1x1", "user_id": "u_ana", "sku": "SKU-0001", "quantity": 1, "total_cents": 5, "status": "paid"}
    pg.upsert("orders", [row], "order_id")
    pg.upsert("orders", [dict(row, status="refunded")], "order_id")
    assert pg.read("orders") == [dict(row, status="refunded")]
    my = SQLConnector("mysql", MYSQL_SCHEMA)
    assert my.read("crm_customers") == []


def test_vector_nearest_ranks_closest_first():
    v = MemoryConnector("vectorsdb")
    v.upsert("c", [{"id": "a", "embeddings": local_embed("red rain jacket"), "metadata": {}},
                   {"id": "b", "embeddings": local_embed("kitchen knife steel"), "metadata": {}}], "id")
    hits = v.nearest("c", local_embed("rain jacket"), k=2)
    assert hits[0]["id"] == "a"
    assert hits[0]["$distance"] <= hits[1]["$distance"]


def test_non_vector_store_refuses_nearest():
    with pytest.raises(NotImplementedError):
        MemoryConnector("tablesdb").nearest("x", [0.1])


def test_appwrite_connector_needs_credentials(monkeypatch):
    pytest.importorskip("appwrite")
    from nmb_five.connectors.appwrite import appwrite_client

    for k in ("APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID", "APPWRITE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(NotConfigured):
        appwrite_client()


@pytest.mark.skipif(not os.environ.get("APPWRITE_API_KEY"), reason="live Appwrite credentials not set")
def test_live_appwrite_smoke():  # pragma: no cover - runs only with real credentials
    from nmb_five.stores import appwrite_stores

    s = appwrite_stores()
    assert s.tables.read("settings") is not None
