import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from nmb_five.web import App, make_handler


def test_web_endpoints():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App("local")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert b"DataContractGate" in urllib.request.urlopen(base + "/").read()
        st = json.load(urllib.request.urlopen(base + "/api/state"))
        assert [s["label"] for s in st["stores"]] == ["TablesDB", "DocumentsDB", "VectorsDB",
                                                      "Managed PostgreSQL", "Managed MySQL"]
        assert all("error" not in e["name"] and e["count"] > 0 for s in st["stores"] for e in s["entities"])
        assert any(c["a"] == "cart.status" and c["b"] == "order.status" for c in st["conflicts"])
        assert "order_id" in st["suggestion"]["yaml"]
        n = len(st["quarantine"])

        def post(rec, contract):
            req = urllib.request.Request(base + "/api/check", json.dumps({"contract": contract, "record": rec}).encode())
            return json.load(urllib.request.urlopen(req))

        good = post({"order_id": "o_c_demo1", "user_id": "u_ana", "sku": "SKU-0001", "quantity": 1,
                     "total_cents": 12900, "status": "paid"}, "order")
        assert good["passed"], good
        bad = post({"cust_id": "u_zed", "cust_email": "ZED@EXAMPLE", "customer_name": "Zed",
                    "lifetime_cents": -5, "segment": "Platinum"}, "crm_customer")
        assert not bad["passed"] and bad["explain"]
        assert len(json.load(urllib.request.urlopen(base + "/api/state"))["quarantine"]) == n + 1
        hits = json.load(urllib.request.urlopen(base + "/api/search?q=rain+jacket"))
        assert hits[0]["sku"] == "SKU-0001"
    finally:
        srv.shutdown()
