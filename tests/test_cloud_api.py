import importlib.util
import json
from pathlib import Path

from nmb_five import cloud_api
from nmb_five.cloud_api import MemoryChecks, StorefrontAPI
from nmb_five.contract_map import ContractMap
from nmb_five.stores import local_stores

BAD = {"cust_id": "u_zed", "cust_email": "ZED@EXAMPLE", "customer_name": "Zed", "lifetime_cents": -5,
       "segment": "Platinum"}
GOOD = {"order_id": "o_c_demo1", "user_id": "u_ana", "sku": "SKU-0001", "quantity": 1, "total_cents": 12900,
        "status": "paid"}


def _api():
    s = local_stores()
    from nmb_five.sync import Pipeline

    p = Pipeline(s).run_all()
    ContractMap(p.gate, s.vectors, s.embedder).index_contracts()
    return StorefrontAPI(s, MemoryChecks(), mode="local")


def test_state_and_search():
    api = _api()
    code, st = api.route("GET", "/api/state", {}, None)
    assert code == 200 and len(st["stores"]) == 5 and len(st["edges"]) == 9
    assert any(c["a"] == "cart.status" for c in st["conflicts"])
    assert "order_id" in st["suggestion"]["yaml"]
    code, hits = api.route("GET", "/api/search", {"q": "waterproof jacket for rain"}, None)
    assert hits[0]["sku"] == "SKU-0001"


def test_public_check_is_sandboxed_and_rate_limited(monkeypatch):
    api = _api()
    before = {e["name"]: e["count"] for s in api.state()["stores"] for e in s["entities"]}
    assert api.route("POST", "/api/check", {}, {"contract": "order", "record": GOOD}, "1.1.1.1")[1]["passed"]
    code, r = api.route("POST", "/api/check", {}, {"contract": "crm_customer", "record": BAD}, "1.1.1.1")
    assert code == 200 and not r["passed"] and r["explain"]
    api._cache.clear()
    st = api.state()
    assert st["quarantine"][-1]["edge"].startswith("public live check")
    assert {e["name"]: e["count"] for s in st["stores"] for e in s["entities"]} == before  # no store writes
    for _ in range(cloud_api.PER_IP_PER_MIN):
        code, _r = api.route("POST", "/api/check", {}, {"contract": "order", "record": GOOD}, "1.1.1.1")
    assert code == 429
    assert api.route("POST", "/api/check", {}, {"contract": "order", "record": GOOD}, "2.2.2.2")[0] == 200
    assert api.route("POST", "/api/check", {}, {"contract": "nope", "record": {}}, "3.3.3.3")[0] == 400
    big = {"x": "a" * 5000}
    assert api.route("POST", "/api/check", {}, {"contract": "order", "record": big}, "3.3.3.3")[0] == 413
    assert api.route("POST", "/api/reset", {}, {}, "3.3.3.3")[0] == 404  # no destructive endpoints


def test_function_entrypoint_cors(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "fnmain", Path(__file__).resolve().parent.parent / "functions/storefront/src/main.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._API = _api()
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://site.example")

    class Res:
        def text(self, body, status=200, headers=None):
            return status, body, headers or {}

        def json(self, obj, status=200, headers=None):
            return status, json.dumps(obj), headers or {}

    class Ctx:
        def __init__(self, method, path, origin, body=""):
            self.res = Res()
            self.req = type("R", (), {"method": method, "path": path, "query": {}, "body_text": body,
                                      "headers": {"origin": origin, "x-forwarded-for": "9.9.9.9"}})()

        def error(self, msg):
            pass

    st, body, h = m.main(Ctx("GET", "/api/state", "https://site.example"))
    assert st == 200 and h["Access-Control-Allow-Origin"] == "https://site.example" and json.loads(body)["edges"]
    st, _, h = m.main(Ctx("GET", "/api/state", "https://evil.example"))
    assert "Access-Control-Allow-Origin" not in h
    st, body, _ = m.main(Ctx("POST", "/api/check", "https://site.example",
                             json.dumps({"contract": "crm_customer", "record": BAD})))
    assert st == 200 and json.loads(body)["passed"] is False
