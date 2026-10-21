"""Contract relationship map, stored in VectorsDB.

Every contract and every quarantined failure is embedded and stored as a
VectorsDB document ``{embeddings, metadata: {kind, ref, text}}``. That
lets us:

* find contracts similar to a given contract,
* find contracts that *conflict* (same meaning, different rules),
* explain a quarantined record by its nearest contracts, and
* suggest a contract for a brand new feed from a few sample records.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Sequence

import yaml

from .gate import Gate, QuarantinedRecord

ENTITY = "contract_map"


def _fields(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(contract.get("ontology", {}).get("entities", []))


def _synonyms(contract: Dict[str, Any]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for g in contract.get("glossary", []) or []:
        out[g["field"]] = list(g.get("synonyms", []) or [])
    return out


def contract_text(contract: Dict[str, Any]) -> str:
    syn = _synonyms(contract)
    parts = [contract["name"].replace("_", " "), contract.get("description", "")]
    for f in _fields(contract):
        parts.append(f"{f['name']} {f.get('type', '')} " + " ".join(syn.get(f["name"], [])))
        for p in f.get("properties", []) or []:
            parts.append(f"{p['name']} {p.get('type', '')}")
    return " ".join(parts)


def record_text(fields: Sequence[str], extra: str = "") -> str:
    return " ".join(str(f) for f in fields) + (" " + extra if extra else "")


def _id(prefix: str, value: str) -> str:
    return prefix + hashlib.sha1(value.encode()).hexdigest()[:30]


class ContractMap:
    def __init__(self, gate: Gate, vectors, embedder):
        self.gate = gate
        self.vectors = vectors
        self.embedder = embedder

    # -- indexing ---------------------------------------------------------
    def _write(self, docs: List[Dict[str, Any]], edge: str) -> GateResultLike:
        res = self.gate.check("contract_map_entry", docs, edge=edge)
        self.vectors.upsert(ENTITY, res.passed, key="id")
        return res

    def index_contracts(self) -> int:
        names = self.gate.names
        texts = [contract_text(self.gate.raw[n]) for n in names]
        vecs = self.embedder.embed(texts)
        docs = [{"id": _id("k", n), "embeddings": v, "metadata": {"kind": "contract", "ref": n, "text": t}}
                for n, t, v in zip(names, texts, vecs)]
        return len(self._write(docs, "contracts->vectorsdb").passed)

    def index_quarantine(self, items: Sequence[QuarantinedRecord]) -> int:
        if not items:
            return 0
        texts = []
        for q in items:
            why = " ".join(f"{v['field']} {v['kind']}" for v in q.violations)
            texts.append(record_text(q.record.keys(), f"{q.contract} {q.edge} {why}"))
        vecs = self.embedder.embed(texts)
        docs = [{"id": _id("q", f"{q.edge}|{q.contract}|{sorted(q.record.items())!r}"), "embeddings": v,
                 "metadata": {"kind": "quarantine", "ref": q.contract, "text": t}}
                for q, t, v in zip(items, texts, vecs)]
        return len(self._write(docs, "quarantine->vectorsdb").passed)

    # -- queries ----------------------------------------------------------
    def _nearest_contracts(self, vector, k):
        hits = self.vectors.nearest(ENTITY, vector, k=k + 8, where={"metadata.kind": "contract"})
        return [{"contract": h["metadata"]["ref"], "distance": round(h["$distance"], 4)} for h in hits][:k]

    def similar_contracts(self, name: str, k: int = 3) -> List[Dict[str, Any]]:
        vec = self.embedder.embed([contract_text(self.gate.raw[name])])[0]
        return [h for h in self._nearest_contracts(vec, k + 1) if h["contract"] != name][:k]

    def explain(self, item: QuarantinedRecord, k: int = 3) -> List[Dict[str, Any]]:
        why = " ".join(f"{v['field']} {v['kind']}" for v in item.violations)
        vec = self.embedder.embed([record_text(item.record.keys(), why)])[0]
        return self._nearest_contracts(vec, k)

    def conflicts(self) -> List[Dict[str, Any]]:
        """Fields that mean the same thing (same name or glossary synonym)
        in two contracts but carry different rules."""
        by_concept: Dict[str, List[tuple]] = defaultdict(list)
        for name, c in self.gate.raw.items():
            syn = _synonyms(c)
            for f in _fields(c):
                concepts = {f["name"], *syn.get(f["name"], [])}
                for concept in concepts:
                    by_concept[concept].append((name, f))
        seen = set()
        out = []
        rule_keys = ("type", "pattern", "enum", "min", "max")
        for concept, pairs in by_concept.items():
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    (ca, fa), (cb, fb) = pairs[i], pairs[j]
                    if ca == cb:
                        continue
                    diffs = {k: (fa.get(k), fb.get(k)) for k in rule_keys if fa.get(k) != fb.get(k)}
                    if not diffs:
                        continue
                    key = tuple(sorted([(ca, fa["name"]), (cb, fb["name"])]))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"concept": concept, "a": f"{ca}.{fa['name']}", "b": f"{cb}.{fb['name']}",
                                "differences": diffs})
        return sorted(out, key=lambda d: (d["a"], d["b"]))

    def suggest_for_feed(self, feed_name: str, samples: Sequence[Dict[str, Any]], k: int = 3) -> Dict[str, Any]:
        keys: List[str] = []
        for s in samples:
            for key in s:
                if key not in keys:
                    keys.append(key)
        vec = self.embedder.embed([record_text(keys, feed_name.replace("_", " "))])[0]
        nearest = self._nearest_contracts(vec, k)
        draft = infer_contract(feed_name, samples, borrow_from=[self.gate.raw[n["contract"]] for n in nearest])
        return {"feed": feed_name, "nearest": nearest, "draft_yaml": yaml.safe_dump(draft, sort_keys=False)}


GateResultLike = Any


def _type_of(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "string"


def infer_contract(name: str, samples: Sequence[Dict[str, Any]], borrow_from: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Draft a contract from samples. Fields that also exist in a nearby
    contract borrow that contract's rules (pattern, enum, bounds)."""
    known: Dict[str, Dict[str, Any]] = {}
    for c in borrow_from:
        for f in _fields(c):
            known.setdefault(f["name"], f)
    keys: List[str] = []
    for s in samples:
        for key in s:
            if key not in keys:
                keys.append(key)
    entities = []
    for key in keys:
        vals = [s[key] for s in samples if key in s]
        ent: Dict[str, Any] = {"name": key, "type": _type_of(vals[0]), "required": len(vals) == len(samples)}
        if key in known and known[key].get("type") == ent["type"]:
            for rk in ("pattern", "enum", "min", "max", "min_length", "max_length"):
                if rk in known[key]:
                    ent[rk] = known[key][rk]
        elif ent["type"] == "string":
            distinct = sorted({str(v) for v in vals})
            if len(distinct) <= max(1, len(vals) // 2) or len(distinct) <= 3 and len(vals) > 3:
                ent["enum"] = distinct
        elif ent["type"] in ("integer", "number"):
            ent["min"] = 0 if min(vals) >= 0 else min(vals)
        entities.append(ent)
    return {"version": "1.0", "name": name, "description": f"Draft contract for {name} (suggested, review before use)",
            "ontology": {"entities": entities}}
