import yaml
from contractgate import Contract

from nmb_five.contract_map import ENTITY
from nmb_five.seed import NEW_FEED_SAMPLE


def test_map_holds_contracts_and_failures(pipeline, cmap):
    docs = pipeline.stores.vectors.read(ENTITY)
    kinds = [d["metadata"]["kind"] for d in docs]
    assert kinds.count("contract") == len(pipeline.gate.names)
    assert kinds.count("quarantine") == len(pipeline.quarantine) > 0


def test_similar_contracts_excludes_self(cmap):
    sims = cmap.similar_contracts("order")
    assert sims and all(s["contract"] != "order" for s in sims)
    assert {"payment", "cart"} & {s["contract"] for s in sims}


def test_conflicts_found(cmap):
    pairs = {(c["a"], c["b"]) for c in cmap.conflicts()}
    assert ("cart.status", "order.status") in pairs


def test_explain_quarantined_record(pipeline, cmap):
    q = next(q for q in pipeline.quarantine if q.contract == "user")
    names = [h["contract"] for h in cmap.explain(q)]
    assert "user" in names


def test_suggest_contract_for_new_feed(cmap):
    s = cmap.suggest_for_feed("refund", NEW_FEED_SAMPLE)
    assert s["nearest"][0]["contract"] in {"order", "payment"}
    draft = yaml.safe_load(s["draft_yaml"])
    fields = {e["name"]: e for e in draft["ontology"]["entities"]}
    assert fields["order_id"]["pattern"].startswith("^o_")  # borrowed from the order contract
    compiled = Contract.from_yaml(s["draft_yaml"]).compile()
    assert all(compiled.validate(r).passed for r in NEW_FEED_SAMPLE)
