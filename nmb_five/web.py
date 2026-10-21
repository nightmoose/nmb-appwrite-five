"""Demo storefront UI: ``python -m nmb_five serve [--mode local|appwrite] [--port 8000]``.

Stdlib only. One page shows the five stores, every gated edge, the
quarantine, the VectorsDB contract map (conflicts + suggestions), and a
live DataContractGate check box.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

import yaml

from .contract_map import ContractMap
from .seed import NEW_FEED_SAMPLE
from .stores import build
from .sync import Pipeline

STATIC = Path(__file__).resolve().parent / "static"

STORE_INFO = [
    ("tables", "TablesDB", "app", ["users", "carts"], "Relational rows: users, carts, settings"),
    ("documents", "DocumentsDB", "catalog", ["products"], "Schemaless product catalog"),
    ("vectors", "VectorsDB", "vectors", ["product_vectors", "contract_map"], "Embeddings + contract relationship map"),
    ("postgres", "Managed PostgreSQL", "orders", ["orders", "payments"], "Orders and payments"),
    ("mysql", "Managed MySQL", "crm", ["crm_customers"], "Legacy CRM (drifts)"),
]


def _strip(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in rec.items():
        if k.startswith("$") or k == "embeddings":
            continue
        out[k] = v
    return out


class App:
    def __init__(self, mode: str = "local"):
        self.mode = mode
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.pipeline = Pipeline(build(self.mode)).run_all()
        self.cmap = ContractMap(self.pipeline.gate, self.pipeline.stores.vectors, self.pipeline.stores.embedder)
        self.cmap.index_contracts()
        self.cmap.index_quarantine(self.pipeline.quarantine)
        self.live_checks = 0

    def state(self) -> Dict[str, Any]:
        p, s = self.pipeline, self.pipeline.stores
        stores = []
        for attr, label, db_id, entities, blurb in STORE_INFO:
            conn = getattr(s, attr)
            ents = []
            for e in entities:
                try:
                    rows = [_strip(r) for r in conn.read(e)]
                except Exception as exc:  # pragma: no cover - live hiccups
                    rows, e = [], f"{e} (error: {type(exc).__name__})"
                ents.append({"name": e, "count": len(rows), "rows": rows[:8]})
            stores.append({"key": attr, "label": label, "db": db_id, "blurb": blurb, "entities": ents})
        sugg = self.cmap.suggest_for_feed("refund", NEW_FEED_SAMPLE)
        return {
            "mode": self.mode,
            "stores": stores,
            "edges": [r.__dict__ for r in p.reports],
            "quarantine": [{"edge": q.edge, "contract": q.contract, "record": q.record,
                            "violations": q.violations} for q in p.quarantine],
            "contracts": p.gate.names,
            "similar": {n: self.cmap.similar_contracts(n) for n in ("order", "cart", "crm_customer")},
            "conflicts": self.cmap.conflicts(),
            "suggestion": {"feed": sugg["feed"], "nearest": sugg["nearest"], "yaml": sugg["draft_yaml"],
                           "samples": NEW_FEED_SAMPLE},
            "templates": {n: self._template(n) for n in p.gate.names},
        }

    def _template(self, name: str) -> Dict[str, Any]:
        examples = {"string": "", "integer": 1, "float": 1.0, "boolean": True, "array": [], "object": {}}
        out = {}
        for f in self.pipeline.gate.raw[name].get("ontology", {}).get("entities", []):
            out[f["name"]] = (f.get("enum") or [None])[0] or examples.get(f.get("type"), "")
        return out

    def check(self, contract: str, record: Dict[str, Any]) -> Dict[str, Any]:
        res = self.pipeline.gate.check(contract, [record], edge="ui->live-check")
        self.live_checks += 1
        if res.quarantined:
            self.pipeline.quarantine.extend(res.quarantined)
            self.cmap.index_quarantine(res.quarantined)
            return {"passed": False, "violations": res.quarantined[0].violations,
                    "explain": self.cmap.explain(res.quarantined[0])}
        return {"passed": True, "violations": []}

    def search(self, q: str):
        return [h.get("metadata", {}) | {"distance": h.get("distance")} for h in self.pipeline.search_products(q, k=4)]


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/config.js":  # local: same-origin API
                return self._send(200, b"window.NMB_API = '';\n", "application/javascript")
            with app.lock:
                if u.path == "/api/state":
                    return self._json(app.state())
                if u.path == "/api/search":
                    return self._json(app.search(parse_qs(u.query).get("q", [""])[0]))
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            with app.lock:
                if self.path == "/api/check":
                    if body.get("contract") not in app.pipeline.gate.names or not isinstance(body.get("record"), dict):
                        return self._json({"error": "need contract + record object"}, 400)
                    return self._json(app.check(body["contract"], body["record"]))
                if self.path == "/api/reset":
                    app.reset()
                    return self._json({"ok": True})
            self._send(404, b"not found", "text/plain")

    return H


def serve(mode: str = "local", host: str = "127.0.0.1", port: int = 8000) -> None:
    app = App(mode)
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"nmb-five storefront ({mode}) on http://{host}:{port}")
    srv.serve_forever()
