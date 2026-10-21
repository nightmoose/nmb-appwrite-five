"""Local stand-ins so the whole demo runs with no Appwrite credentials.

* ``MemoryConnector`` stands in for TablesDB, DocumentsDB and VectorsDB.
* ``SQLConnector`` runs real SQL against sqlite (default) or any DB-API
  connection, standing in for Managed PostgreSQL and Managed MySQL.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from ..embed import cosine_distance
from .base import Connector


def _match(rec: Dict[str, Any], where: Optional[Dict[str, Any]]) -> bool:
    if not where:
        return True
    for k, v in where.items():
        cur: Any = rec
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur != v:
            return False
    return True


class MemoryConnector(Connector):
    def __init__(self, store_type: str, contracts: Optional[Dict[str, str]] = None):
        self.store_type = store_type
        self.contracts = contracts or {}
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def read(self, entity, where=None):
        return [copy.deepcopy(r) for r in self._data.get(entity, {}).values() if _match(r, where)]

    def upsert(self, entity, records, key):
        bucket = self._data.setdefault(entity, {})
        for r in records:
            bucket[str(r[key])] = copy.deepcopy(r)
        return len(records)

    def nearest(self, entity, vector, k=3, where=None):
        if self.store_type != "vectorsdb":
            return super().nearest(entity, vector, k, where)
        scored = []
        for r in self._data.get(entity, {}).values():
            if _match(r, where):
                d = dict(copy.deepcopy(r))
                d["$distance"] = cosine_distance(vector, r["embeddings"])
                scored.append(d)
        scored.sort(key=lambda d: d["$distance"])
        return scored[:k]


class SQLConnector(Connector):
    """Generic SQL connector. Schemas are created from ``schema`` DDL.

    Columns ending in ``_json`` are JSON-encoded transparently.
    ``paramstyle`` is "?" for sqlite, "%s" for psycopg / PyMySQL.
    """

    def __init__(self, store_type: str, schema: Dict[str, str], contracts: Optional[Dict[str, str]] = None,
                 conn=None, paramstyle: str = "?", dialect: str = "sqlite"):
        self.store_type = store_type
        self.contracts = contracts or {}
        self.conn = conn or sqlite3.connect(":memory:", check_same_thread=False)
        self.ph = paramstyle
        self.dialect = dialect
        cur = self.conn.cursor()
        for ddl in schema.values():
            cur.execute(ddl)
        self.conn.commit()

    def _columns(self, entity: str) -> List[str]:
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM {entity} WHERE 1=0")
        return [d[0] for d in cur.description]

    def read(self, entity, where=None):
        sql = f"SELECT * FROM {entity}"
        params: List[Any] = []
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = {self.ph}" for k in where)
            params = list(where.values())
        cur = self.conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            for c in cols:
                if c.endswith("_json") and isinstance(rec[c], str):
                    rec[c] = json.loads(rec[c])
            out.append(rec)
        return out

    def upsert(self, entity, records, key):
        if not records:
            return 0
        cols = self._columns(entity)
        cur = self.conn.cursor()
        for r in records:
            vals = [json.dumps(r.get(c)) if c.endswith("_json") else r.get(c) for c in cols]
            ph = ", ".join([self.ph] * len(cols))
            collist = ", ".join(cols)
            if self.dialect == "mysql":
                upd = ", ".join(f"{c}=VALUES({c})" for c in cols if c != key)
                sql = f"INSERT INTO {entity} ({collist}) VALUES ({ph}) ON DUPLICATE KEY UPDATE {upd}"
            else:  # sqlite + postgres
                upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
                sql = f"INSERT INTO {entity} ({collist}) VALUES ({ph}) ON CONFLICT ({key}) DO UPDATE SET {upd}"
            cur.execute(sql, vals)
        self.conn.commit()
        return len(records)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        cur = self.conn.cursor()
        cur.execute(sql, list(params))
        self.conn.commit()

    def close(self):
        self.conn.close()
