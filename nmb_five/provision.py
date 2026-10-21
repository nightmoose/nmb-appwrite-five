"""Create the TablesDB tables, DocumentsDB collection and VectorsDB
collections the demo needs. Idempotent: existing resources are kept.

    python -m nmb_five.provision
"""

from __future__ import annotations

import time

from appwrite.enums.tables_db_index_type import TablesDBIndexType
from appwrite.enums.vectors_db_index_type import VectorsDBIndexType
from appwrite.exception import AppwriteException
from appwrite.services.documents_db import DocumentsDB
from appwrite.services.tables_db import TablesDB
from appwrite.services.vectors_db import VectorsDB

from .connectors.appwrite import _env, appwrite_client, load_dotenv

VECTOR_DIM = 768

# table -> [(column, kind, size)]
TABLES = {
    "users": [("user_id", "varchar", 64), ("email", "varchar", 254), ("full_name", "varchar", 120),
              ("tier", "varchar", 16)],
    "carts": [("cart_id", "varchar", 64), ("user_id", "varchar", 64), ("sku", "varchar", 16),
              ("quantity", "integer", None), ("status", "varchar", 16)],
    "settings": [("key", "varchar", 64), ("value", "varchar", 256)],
    # Sandbox for the public live check (rate limited, pruned; see cloud_api.py).
    "public_checks": [("ip_hash", "varchar", 32), ("contract", "varchar", 64), ("passed", "varchar", 3),
                      ("record", "varchar", 2000), ("violations", "varchar", 2000)],
}
TABLE_INDEXES = {"carts": [("status_idx", ["status"])], "public_checks": [("ip_idx", ["ip_hash"]),
                                                                           ("passed_idx", ["passed"])]}
DOC_COLLECTIONS = ["products"]
VECTOR_COLLECTIONS = ["product_vectors", "contract_map"]


def _exists(e: AppwriteException) -> bool:
    return getattr(e, "code", None) == 409 or "already exists" in str(e).lower()


def _try(fn, label):
    try:
        fn()
        print(f"created {label}")
    except AppwriteException as e:
        if _exists(e):
            print(f"exists  {label}")
        else:
            raise


def _wait_columns(t: TablesDB, db: str, table: str, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        cols = t.list_columns(database_id=db, table_id=table)
        cols = cols.model_dump() if hasattr(cols, "model_dump") else cols
        states = [getattr(c.get("status"), "value", c.get("status")) for c in cols.get("columns", [])]
        if states and all(s == "available" for s in states):
            return
        if any(s == "failed" for s in states):
            raise RuntimeError(f"column creation failed on {table}: {states}")
        time.sleep(2)
    raise TimeoutError(f"columns on {table} not available after {timeout}s")


def provision() -> None:
    load_dotenv()
    c = appwrite_client()
    t, d, v = TablesDB(c), DocumentsDB(c), VectorsDB(c)
    tdb, ddb, vdb = _env("APPWRITE_TABLESDB_ID"), _env("APPWRITE_DOCUMENTSDB_ID"), _env("APPWRITE_VECTORSDB_ID")

    for table, cols in TABLES.items():
        _try(lambda: t.create_table(database_id=tdb, table_id=table, name=table), f"tablesdb.{table}")
        for key, kind, size in cols:
            if kind == "integer":
                fn = lambda: t.create_integer_column(database_id=tdb, table_id=table, key=key, required=False)
            else:
                fn = lambda: t.create_varchar_column(database_id=tdb, table_id=table, key=key, size=size, required=False)
            _try(fn, f"tablesdb.{table}.{key}")
        _wait_columns(t, tdb, table)
        for ikey, icols in TABLE_INDEXES.get(table, []):
            _try(lambda: t.create_index(database_id=tdb, table_id=table, key=ikey, type=TablesDBIndexType.KEY,
                                        columns=icols), f"tablesdb.{table}#{ikey}")

    for coll in DOC_COLLECTIONS:
        _try(lambda: d.create_collection(database_id=ddb, collection_id=coll, name=coll), f"documentsdb.{coll}")

    for coll in VECTOR_COLLECTIONS:
        _try(lambda: v.create_collection(database_id=vdb, collection_id=coll, name=coll, dimension=VECTOR_DIM),
             f"vectorsdb.{coll}")
        _try(lambda: v.create_index(database_id=vdb, collection_id=coll, key="embeddings_cosine",
                                    type=VectorsDBIndexType.HNSW_COSINE, attributes=["embeddings"]),
             f"vectorsdb.{coll}#embeddings_cosine")


if __name__ == "__main__":
    provision()
