"""``python -m nmb_five demo|serve [--mode local|appwrite]``"""

from __future__ import annotations

import argparse
import json

from .contract_map import ContractMap
from .seed import NEW_FEED_SAMPLE
from .stores import build
from .sync import Pipeline


def demo(mode: str = "local") -> dict:
    p = Pipeline(build(mode)).run_all()
    cmap = ContractMap(p.gate, p.stores.vectors, p.stores.embedder)
    cmap.index_contracts()
    cmap.index_quarantine(p.quarantine)
    return {
        "edges": [r.__dict__ for r in p.reports],
        "quarantined": [{"edge": q.edge, "contract": q.contract, "violations": q.violations} for q in p.quarantine],
        "search_rain_jacket": [h["metadata"]["sku"] for h in p.search_products("waterproof jacket for rain")],
        "similar_to_order": cmap.similar_contracts("order"),
        "conflicts": cmap.conflicts(),
        "suggest_refunds": cmap.suggest_for_feed("refund", NEW_FEED_SAMPLE),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nmb-five")
    ap.add_argument("command", choices=["demo", "serve"])
    ap.add_argument("--mode", choices=["local", "appwrite"], default="local")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    if args.command == "serve":
        from .web import serve
        serve(args.mode, args.host, args.port)
        return 0
    out = demo(args.mode)
    draft = out["suggest_refunds"].pop("draft_yaml")
    print(json.dumps(out, indent=2, default=str))
    print("\n# Suggested contract for the new 'refund' feed\n" + draft)
    return 0
