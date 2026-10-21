"""DataContractGate at every edge.

Thin wrapper over the open-source ``contractgate`` Python SDK's local
validator. Every sync job calls ``Gate.check`` before writing to the
target store; failing records go to quarantine instead of the target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml
from contractgate import Contract

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


@dataclass
class QuarantinedRecord:
    contract: str
    edge: str
    record: Dict[str, Any]
    violations: List[Dict[str, str]]


@dataclass
class GateResult:
    passed: List[Dict[str, Any]] = field(default_factory=list)
    quarantined: List[QuarantinedRecord] = field(default_factory=list)


class Gate:
    def __init__(self, contracts_dir: Path = CONTRACTS_DIR):
        self.contracts_dir = Path(contracts_dir)
        self._compiled: Dict[str, Any] = {}
        self.raw: Dict[str, Dict[str, Any]] = {}
        for p in sorted(self.contracts_dir.glob("*.yaml")):
            text = p.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            self.raw[data["name"]] = data
            self._compiled[data["name"]] = Contract.from_yaml(text).compile()

    @property
    def names(self) -> List[str]:
        return sorted(self._compiled)

    def check(self, contract: str, records: Iterable[Dict[str, Any]], edge: str = "") -> GateResult:
        compiled = self._compiled[contract]
        out = GateResult()
        for rec in records:
            vr = compiled.validate(rec)
            if vr.passed:
                out.passed.append(rec)
            else:
                out.quarantined.append(
                    QuarantinedRecord(
                        contract=contract,
                        edge=edge,
                        record=rec,
                        violations=[
                            {"field": v.field, "kind": getattr(v.kind, "value", str(v.kind)), "message": v.message}
                            for v in vr.violations
                        ],
                    )
                )
        return out
