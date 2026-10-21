"""Public, read-mostly storefront API used by the Appwrite Function.

Every request is stateless (a function execution), so:

* store cards and row previews are read live from the five Appwrite stores;
* the nine gated edges and their quarantine are a replay of the demo
  pipeline in memory (same seed data the live pipeline wrote);
* the contract map (similar contracts, explain, suggestion, product search)
  queries VectorsDB live and never writes to it;
* the public live check only writes to a sandbox table (``public_checks``)
  that is rate limited and pruned. No other store is ever written.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .contract_map import ContractMap
from .gate import Gate, QuarantinedRecord
from .seed import NEW_FEED_SAMPLE
from .stores import Stores, local_stores
from .sync import Pipeline

STORE_INFO = [
    ("tables", "TablesDB", "app", ["users", "carts"], "Relational rows: users, carts, settings"),
    ("documents", "DocumentsDB", "catalog", ["products"], "Schemaless product catalog"),
    ("vectors", "VectorsDB", "vectors", ["product_vectors", "contract_map"], "Embeddings + contract relationship map"),
    ("postgres", "Managed PostgreSQL", "orders", ["orders", "payments"], "Orders and payments"),
    ("mysql", "Managed MySQL", "crm", ["crm_customers"], "Legacy CRM (drifts)"),
]

MAX_RECORD_BYTES = 4096
MAX_FIELDS = 40
PER_IP_PER_MIN = int(os.environ.get("NMB_RATE_PER_IP", "6"))
GLOBAL_PER_MIN = int(os.environ.get("NMB_RATE_GLOBAL", "60"))
KEEP_CHECKS = 200


def strip_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in rec.items() if not k.startswith("$") and k != "embeddings"}


# -- sandbox for public checks ---------------------------------------------
class MemoryChecks:
    """In-memory sandbox (tests, local)."""

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def add(self, row):
        self.rows.append(dict(row, ts=time.time()))

    def count_since(self, seconds, ip_hash=None):
        t = time.time() - seconds
        return sum(1 for r in self.rows if r["ts"] >= t and (ip_hash is None or r["ip_hash"] == ip_hash))

    def recent_failures(self, n=20):
        return [r for r in reversed(self.rows) if r["passed"] == "no"][:n]

    def prune(self, keep=KEEP_CHECKS):
        del self.rows[:-keep]


class TablesDBChecks:
    """Sandbox table ``public_checks`` in TablesDB (see provision.py)."""

    table = "public_checks"

    def __init__(self, client, database_id):
        from appwrite.services.tables_db import TablesDB

        self.t, self.db = TablesDB(client), database_id

    def _list(self, queries):
        res = self.t.list_rows(database_id=self.db, table_id=self.table, queries=queries)
        return res.model_dump() if hasattr(res, "model_dump") else res

    def add(self, row):
        from appwrite.id import ID

        self.t.create_row(database_id=self.db, table_id=self.table, row_id=ID.unique(), data=row)

    def count_since(self, seconds, ip_hash=None):
        from appwrite.query import Query

        since = time.strftime("%Y-%m-%dT%H:%M:%S.000+00:00", time.gmtime(time.time() - seconds))
        q = [Query.greater_than("$createdAt", since), Query.limit(1)]
        if ip_hash:
            q.append(Query.equal("ip_hash", ip_hash))
        return int(self._list(q).get("total", 0))

    def recent_failures(self, n=20):
        from appwrite.query import Query

        res = self._list([Query.equal("passed", "no"), Query.order_desc("$createdAt"), Query.limit(n)])
        out = []
        for r in res.get("rows", []):
            d = r.get("data") if isinstance(r.get("data"), dict) else r
            out.append(d)
        return out

    def prune(self, keep=KEEP_CHECKS):
        from appwrite.query import Query

        res = self._list([Query.order_desc("$createdAt"), Query.offset(keep), Query.limit(50)])
        for r in res.get("rows", []):  # only ever deletes old sandbox rows
            self.t.delete_row(database_id=self.db, table_id=self.table, row_id=r.get("id") or r.get("$id"))


# -- API -------------------------------------------------------------------
class StorefrontAPI:
    def __init__(self, stores: Stores, checks, mode: str = "appwrite", cache_ttl: float = 60.0):
        self.stores, self.checks, self.mode, self.ttl = stores, checks, mode, cache_ttl
        self.gate = Gate()
        self.cmap = ContractMap(self.gate, stores.vectors, stores.embedder)
        replay = Pipeline(local_stores()).run_all()
        self.edges = [r.__dict__ for r in replay.reports]
        self.replay_quarantine = [{"edge": q.edge, "contract": q.contract, "record": q.record,
                                   "violations": q.violations} for q in replay.quarantine]
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def _cached(self, key: str, fn: Callable[[], Any]):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        val = fn()
        self._cache[key] = (time.time(), val)
        return val

    def _stores(self):
        out = []
        for attr, label, db_id, entities, blurb in STORE_INFO:
            conn = getattr(self.stores, attr)
            ents = []
            for e in entities:
                try:
                    rows = [strip_row(r) for r in conn.read(e)]
                    ents.append({"name": e, "count": len(rows), "rows": rows[:8]})
                except Exception as exc:  # store asleep or unreachable
                    ents.append({"name": e, "count": 0, "rows": [], "error": type(exc).__name__})
            out.append({"key": attr, "label": label, "db": db_id, "blurb": blurb, "entities": ents})
        return out

    def _map(self):
        sugg = self.cmap.suggest_for_feed("refund", NEW_FEED_SAMPLE)
        return {
            "similar": {n: self.cmap.similar_contracts(n) for n in ("order", "cart", "crm_customer")},
            "conflicts": self.cmap.conflicts(),
            "suggestion": {"feed": sugg["feed"], "nearest": sugg["nearest"], "yaml": sugg["draft_yaml"],
                           "samples": NEW_FEED_SAMPLE},
        }

    def _template(self, name):
        ex = {"string": "", "integer": 1, "float": 1.0, "number": 1.0, "boolean": True, "array": [], "object": {}}
        return {f["name"]: (f.get("enum") or [None])[0] or ex.get(f.get("type"), "")
                for f in self.gate.raw[name].get("ontology", {}).get("entities", [])}

    def state(self):
        public = []
        for r in self.checks.recent_failures(20):
            try:
                public.append({"edge": "public live check (sandbox)", "contract": r["contract"],
                               "record": json.loads(r.get("record") or "{}"),
                               "violations": json.loads(r.get("violations") or "[]")})
            except (ValueError, KeyError):
                continue
        return {
            "mode": self.mode,
            "stores": self._cached("stores", self._stores),
            "edges": self.edges,
            "quarantine": self.replay_quarantine + list(reversed(public)),
            "contracts": self.gate.names,
            "templates": {n: self._template(n) for n in self.gate.names},
            **self._cached("map", self._map),
        }

    def search(self, q: str):
        q = (q or "")[:200]
        vec = self.stores.embedder.embed([q or "jacket"])[0]
        hits = self.stores.vectors.nearest("product_vectors", vec, k=4)
        return [dict(h.get("metadata", {}), distance=h.get("$distance")) for h in hits]

    def check(self, contract: Any, record: Any, client_ip: str = ""):
        if contract not in self.gate.names or not isinstance(record, dict):
            return 400, {"error": "need a known contract and a record object"}
        raw = json.dumps(record, default=str)
        if len(raw) > MAX_RECORD_BYTES or len(record) > MAX_FIELDS:
            return 413, {"error": f"record too large (max {MAX_RECORD_BYTES} bytes, {MAX_FIELDS} fields)"}
        ip_hash = hashlib.sha256(("nmb5|" + (client_ip or "?")).encode()).hexdigest()[:32]
        if self.checks.count_since(60, ip_hash) >= PER_IP_PER_MIN or self.checks.count_since(60) >= GLOBAL_PER_MIN:
            return 429, {"error": "rate limited, try again in a minute"}
        res = self.gate.check(contract, [record], edge="public live check (sandbox)")
        passed = not res.quarantined
        viol = res.quarantined[0].violations if res.quarantined else []
        self.checks.add({"ip_hash": ip_hash, "contract": contract, "passed": "yes" if passed else "no",
                         "record": raw[:2000], "violations": json.dumps(viol)[:2000]})
        try:
            self.checks.prune()
        except Exception:
            pass
        if passed:
            return 200, {"passed": True, "violations": [], "note": "valid; sandbox only, nothing written to the stores"}
        explain = self.cmap.explain(QuarantinedRecord(contract, "public", record, viol))
        return 200, {"passed": False, "violations": viol, "explain": explain}

    def route(self, method: str, path: str, query: Dict[str, str], body: Any, client_ip: str = ""):
        path = "/" + path.strip("/")
        if method == "GET" and path in ("/api/state", "/state"):
            return 200, self.state()
        if method == "GET" and path in ("/api/search", "/search"):
            return 200, self.search(query.get("q", ""))
        if method == "POST" and path in ("/api/check", "/check"):
            body = body if isinstance(body, dict) else {}
            return self.check(body.get("contract"), body.get("record"), client_ip)
        if method == "GET" and path in ("/", "/api/health"):
            return 200, {"ok": True}
        return 404, {"error": "not found"}


def appwrite_api() -> StorefrontAPI:
    from .connectors.appwrite import _env, appwrite_client
    from .stores import appwrite_stores

    stores = appwrite_stores()
    return StorefrontAPI(stores, TablesDBChecks(appwrite_client(), _env("APPWRITE_TABLESDB_ID")))
