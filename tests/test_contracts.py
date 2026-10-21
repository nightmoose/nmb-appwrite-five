from pathlib import Path

from contractgate import Contract

from nmb_five.gate import CONTRACTS_DIR, Gate


def test_every_contract_compiles():
    files = sorted(Path(CONTRACTS_DIR).glob("*.yaml"))
    assert len(files) >= 8
    for f in files:
        Contract.from_yaml(f.read_text()).compile()


def test_gate_splits_pass_and_quarantine():
    g = Gate()
    res = g.check("cart", [
        {"cart_id": "c_ok1", "user_id": "u_ana", "sku": "SKU-0001", "quantity": 2, "status": "open"},
        {"cart_id": "c_bad", "user_id": "u_ana", "sku": "nope", "quantity": 200, "status": "open"},
    ], edge="test")
    assert len(res.passed) == 1
    assert len(res.quarantined) == 1
    kinds = {v["field"] for v in res.quarantined[0].violations}
    assert {"sku", "quantity"} <= kinds
