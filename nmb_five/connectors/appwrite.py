"""Appwrite Cloud connectors (one per database type).

These are the real-store implementations of the ``Connector`` interface.
They import the Appwrite SDK / SQL drivers lazily so local mode and the
tests never need them. Configuration comes from environment variables
(see ``.env.example``). Nothing here has been exercised against a live
Appwrite project yet; signatures follow the ``appwrite`` Python SDK 26.x
and the docs linked in docs/appwrite-notes.md.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence

from .base import Connector, NotConfigured
from .local import SQLConnector

_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]")


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise NotConfigured(f"missing environment variable {name}")
    return val


def appwrite_client():
    try:
        from appwrite.client import Client
    except ImportError as e:  # pragma: no cover
        raise NotConfigured("pip install 'nmb-five[appwrite]'") from e
    c = Client()
    c.set_endpoint(_env("APPWRITE_ENDPOINT"))  # e.g. https://<REGION>.cloud.appwrite.io/v1
    c.set_project(_env("APPWRITE_PROJECT_ID"))
    c.set_key(_env("APPWRITE_API_KEY"))
    return c


def _dump(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "to_dict"):
        if hasattr(obj, attr):
            return getattr(obj, attr)()
    return dict(obj)


def _row_id(value: Any) -> str:
    # Appwrite IDs: up to 36 chars, a-z A-Z 0-9 . - _ , no leading special char.
    return _SAFE_ID.sub("_", str(value))[:36]


def _strip_system(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if not k.startswith("$") or k == "$distance"}


class TablesDBConnector(Connector):
    """TablesDB: users, carts, settings. Entity = table ID."""

    store_type = "tablesdb"
    contracts = {"users": "user", "carts": "cart"}

    def __init__(self, client=None, database_id: Optional[str] = None):
        from appwrite.services.tables_db import TablesDB

        self.svc = TablesDB(client or appwrite_client())
        self.db = database_id or _env("APPWRITE_TABLESDB_ID")

    def read(self, entity, where=None):
        from appwrite.query import Query

        q = [Query.equal(k, v) for k, v in (where or {}).items()] + [Query.limit(500)]
        res = _dump(self.svc.list_rows(database_id=self.db, table_id=entity, queries=q))
        return [_strip_system(r) for r in res.get("rows", [])]

    def upsert(self, entity, records, key):
        for r in records:
            self.svc.upsert_row(database_id=self.db, table_id=entity, row_id=_row_id(r[key]), data=r)
        return len(records)


class DocumentsDBConnector(Connector):
    """DocumentsDB (beta): schemaless product catalog. Entity = collection ID."""

    store_type = "documentsdb"
    contracts = {"products": "product"}

    def __init__(self, client=None, database_id: Optional[str] = None):
        from appwrite.services.documents_db import DocumentsDB

        self.svc = DocumentsDB(client or appwrite_client())
        self.db = database_id or _env("APPWRITE_DOCUMENTSDB_ID")

    def read(self, entity, where=None):
        from appwrite.query import Query

        q = [Query.equal(k, v) for k, v in (where or {}).items()] + [Query.limit(500)]
        res = _dump(self.svc.list_documents(database_id=self.db, collection_id=entity, queries=q))
        return [_strip_system(d) for d in res.get("documents", [])]

    def upsert(self, entity, records, key):
        for r in records:
            self.svc.upsert_document(database_id=self.db, collection_id=entity, document_id=_row_id(r[key]), data=r)
        return len(records)


class VectorsDBConnector(Connector):
    """VectorsDB (beta): fixed-shape docs {embeddings, metadata}. Entity = collection ID.

    Similarity search uses Query.vector_cosine and needs an hnsw_cosine index
    on ``embeddings`` for speed (small collections work without one).
    """

    store_type = "vectorsdb"
    contracts = {"product_vectors": "product_embedding", "contract_map": "contract_map_entry"}

    def __init__(self, client=None, database_id: Optional[str] = None):
        from appwrite.services.vectors_db import VectorsDB

        self.svc = VectorsDB(client or appwrite_client())
        self.db = database_id or _env("APPWRITE_VECTORSDB_ID")

    def read(self, entity, where=None):
        from appwrite.query import Query

        q = [Query.equal(f"metadata.{k}" if "." not in k and k not in ("embeddings",) else k, v)
             for k, v in (where or {}).items()] + [Query.limit(500)]
        res = _dump(self.svc.list_documents(database_id=self.db, collection_id=entity, queries=q))
        return [_strip_system(d) for d in res.get("documents", [])]

    def upsert(self, entity, records, key):
        for r in records:
            doc_id = r.get("id") or r["metadata"][key.split(".")[-1]]
            self.svc.upsert_document(database_id=self.db, collection_id=entity, document_id=_row_id(doc_id),
                                     data={"embeddings": r["embeddings"], "metadata": r["metadata"]})
        return len(records)

    def nearest(self, entity, vector, k=3, where=None):
        from appwrite.query import Query

        # UNVERIFIED: filtering on metadata sub-keys alongside a vector query.
        q = [Query.vector_cosine("embeddings", list(vector)), Query.limit(k)]
        res = _dump(self.svc.list_documents(database_id=self.db, collection_id=entity, queries=q))
        docs = [_strip_system(d) for d in res.get("documents", [])]
        if where:
            docs = [d for d in docs if all(d.get("metadata", {}).get(kk.split(".")[-1]) == vv for kk, vv in where.items())]
        return docs


def PostgresConnector(schema: Dict[str, str]) -> SQLConnector:
    """Managed PostgreSQL: orders + payments, over a plain DSN (psycopg 3)."""
    import psycopg

    conn = psycopg.connect(_env("APPWRITE_POSTGRES_DSN"))  # postgresql://admin:...@db-...appwrite.center/...?sslmode=require
    c = SQLConnector("postgresql", schema, conn=conn, paramstyle="%s", dialect="postgres",
                     contracts={"orders": "order", "payments": "payment"})
    return c


def MySQLConnector(schema: Dict[str, str]) -> SQLConnector:
    """Managed MySQL: the legacy CRM, over host/user/password (PyMySQL, TLS)."""
    import pymysql

    conn = pymysql.connect(host=_env("APPWRITE_MYSQL_HOST"), user=_env("APPWRITE_MYSQL_USER"),
                           password=_env("APPWRITE_MYSQL_PASSWORD"), database=_env("APPWRITE_MYSQL_DATABASE"),
                           ssl={"ssl": {}})
    return SQLConnector("mysql", schema, conn=conn, paramstyle="%s", dialect="mysql",
                        contracts={"crm_customers": "crm_customer"})
