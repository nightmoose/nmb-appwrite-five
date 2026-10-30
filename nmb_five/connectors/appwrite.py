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


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


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


_SYSTEM = {"id", "sequence", "collectionid", "tableid", "databaseid", "createdat", "updatedat", "permissions"}


def _strip_system(d: Any) -> Dict[str, Any]:
    """Return only user data. Typed SDK models (26.x) nest user fields
    under ``data``; raw REST JSON uses top-level fields plus ``$`` keys."""
    if not isinstance(d, dict):
        d = _dump(d)
    if isinstance(d.get("data"), dict):
        out = dict(d["data"])
        for k in ("$distance", "distance"):
            if k in d and d[k] is not None:
                out["$distance"] = d[k]
        if "$distance" not in out and "$distance" in out.get("metadata", {}):
            pass
        return out
    return {k: v for k, v in d.items() if (not k.startswith("$") or k == "$distance") and k not in _SYSTEM}


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
        # A 768-dim vector does not fit in a GET query string ("URI Too Long"),
        # so use create_query: the same listing, with queries in a POST body.
        q = [Query.vector_cosine("embeddings", list(vector)), Query.limit(k)]
        res = _dump(self.svc.create_query(database_id=self.db, collection_id=entity, queries=q))
        docs = [_strip_system(d) for d in res.get("documents", [])]
        if where:
            docs = [d for d in docs if all(d.get("metadata", {}).get(kk.split(".")[-1]) == vv for kk, vv in where.items())]
        return docs


class SQLApiConnector(Connector):
    """Native PostgreSQL / MySQL through Appwrite's SQL API over HTTPS
    (``Postgresql.create_execution`` / ``Mysql.create_execution``).

    Useful where outbound database ports are blocked; only port 443 is
    needed. One statement per call, values always passed as bindings.
    """

    def __init__(self, store_type: str, schema: Dict[str, str], contracts: Dict[str, str], client=None):
        from appwrite.services.mysql import Mysql
        from appwrite.services.postgresql import Postgresql

        self.store_type = store_type
        self.contracts = contracts
        c = client or appwrite_client()
        if store_type == "postgresql":
            self.svc, self.db, self.key_q = Postgresql(c), _env("APPWRITE_POSTGRES_ID"), '"'
        else:
            self.svc, self.db, self.key_q = Mysql(c), _env("APPWRITE_MYSQL_ID"), "`"
        self._cols: Dict[str, List[str]] = {}
        for ddl in schema.values():
            self.exec(ddl)

    def _ph(self, n: int) -> str:
        return f"${n}" if self.store_type == "postgresql" else "?"

    def exec(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        kw = {"bindings": list(params)} if params else {}
        res = _dump(self.svc.create_execution(database_id=self.db, sql=sql, **kw))
        if res.get("truncated"):
            raise RuntimeError("SQL API result truncated")
        return list(res.get("rows") or [])

    def columns(self, entity: str) -> List[str]:
        if entity not in self._cols:
            rows = self.exec(
                "SELECT column_name AS c FROM information_schema.columns WHERE table_name = "
                + self._ph(1) + " ORDER BY ordinal_position", [entity])
            self._cols[entity] = [r.get("c") or r.get("C") or r.get("COLUMN_NAME") for r in rows]
        return self._cols[entity]

    def read(self, entity, where=None):
        sql = f"SELECT * FROM {entity}"
        params: List[Any] = []
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = {self._ph(i + 1)}" for i, k in enumerate(where))
            params = list(where.values())
        return self.exec(sql, params)

    def upsert(self, entity, records, key):
        cols = self.columns(entity)
        for r in records:
            vals = [r.get(c) for c in cols]
            ph = ", ".join(self._ph(i + 1) for i in range(len(cols)))
            collist = ", ".join(cols)
            if self.store_type == "mysql":
                upd = ", ".join(f"{c}=VALUES({c})" for c in cols if c != key)
                sql = f"INSERT INTO {entity} ({collist}) VALUES ({ph}) ON DUPLICATE KEY UPDATE {upd}"
            else:
                upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
                sql = f"INSERT INTO {entity} ({collist}) VALUES ({ph}) ON CONFLICT ({key}) DO UPDATE SET {upd}"
            self.exec(sql, vals)
        return len(records)


def _sql_transport() -> str:
    return os.environ.get("APPWRITE_SQL_TRANSPORT", "api")


def PostgresConnector(schema: Dict[str, str]) -> Connector:
    """Managed PostgreSQL: orders + payments. SQL API by default, or a DSN (pg8000, BSD-3)."""
    contracts = {"orders": "order", "payments": "payment"}
    if _sql_transport() == "api":
        return SQLApiConnector("postgresql", schema, contracts)
    import pg8000.dbapi

    # postgresql://admin:...@db-...appwrite.center:5432/...?sslmode=require
    conn = pg8000.dbapi.connect(**_pg8000_kwargs(_env("APPWRITE_POSTGRES_DSN")))
    return SQLConnector("postgresql", schema, conn=conn, paramstyle="%s", dialect="postgres",
                        contracts=contracts)


def _pg8000_kwargs(dsn: str) -> Dict[str, Any]:
    """Turn a postgresql:// DSN into pg8000.dbapi.connect() keyword arguments."""
    import ssl
    from urllib.parse import parse_qs, unquote, urlparse

    u = urlparse(dsn)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError("APPWRITE_POSTGRES_DSN must start with postgresql://")
    q = {k: v[-1] for k, v in parse_qs(u.query).items()}
    kw: Dict[str, Any] = {
        "user": unquote(u.username or ""),
        "password": unquote(u.password or "") or None,
        "host": u.hostname or "localhost",
        "port": u.port or 5432,
        "database": unquote(u.path.lstrip("/")) or None,
    }
    if q.get("sslmode", "require") != "disable":
        kw["ssl_context"] = ssl.create_default_context()
    return kw


def MySQLConnector(schema: Dict[str, str]) -> Connector:
    """Managed MySQL: the legacy CRM. SQL API by default, or PyMySQL over TLS."""
    if _sql_transport() == "api":
        return SQLApiConnector("mysql", schema, {"crm_customers": "crm_customer"})
    import pymysql

    conn = pymysql.connect(host=_env("APPWRITE_MYSQL_HOST"), port=int(os.environ.get("APPWRITE_MYSQL_PORT", "3306")), user=_env("APPWRITE_MYSQL_USER"),
                           password=_env("APPWRITE_MYSQL_PASSWORD"), database=_env("APPWRITE_MYSQL_DATABASE"),
                           ssl={"ssl": {}})
    return SQLConnector("mysql", schema, conn=conn, paramstyle="%s", dialect="mysql",
                        contracts={"crm_customers": "crm_customer"})
