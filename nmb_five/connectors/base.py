"""Connector interface shared by all five stores.

A connector moves records in and out of one store. ``entity`` is the
table / collection name. Vector stores also implement ``nearest``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence


class NotConfigured(RuntimeError):
    """Raised when an Appwrite connector is used without credentials."""


class Connector(ABC):
    #: one of tablesdb, documentsdb, vectorsdb, postgresql, mysql
    store_type: str = ""
    #: the DataContractGate contract enforced on writes to each entity
    contracts: Dict[str, str] = {}

    @abstractmethod
    def read(self, entity: str, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def upsert(self, entity: str, records: Sequence[Dict[str, Any]], key: str) -> int: ...

    def nearest(self, entity: str, vector: Sequence[float], k: int = 3,
                where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError(f"{self.store_type} is not a vector store")

    def close(self) -> None:  # pragma: no cover - optional
        pass
