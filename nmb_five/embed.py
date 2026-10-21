"""Embeddings.

Local mode uses a deterministic hashed bag-of-words vector so tests need
no network. Appwrite mode uses the Appwrite Embeddings service
(``createTextEmbeddings``, default model nomic-embed-text, 768 dims).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import List, Sequence

LOCAL_DIM = 128
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> List[str]:
    toks = _TOKEN.findall(text.lower())
    # split snake_case already handled by regex; add bigrams for a bit of order
    return toks + [a + "_" + b for a, b in zip(toks, toks[1:])]


def local_embed(text: str, dim: int = LOCAL_DIM) -> List[float]:
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "big")
        vec[h % dim] += 1.0 if (h >> 63) & 1 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return 1.0 - dot / (na * nb)


class LocalEmbedder:
    dimension = LOCAL_DIM

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return [local_embed(t) for t in texts]


class AppwriteEmbedder:
    """Uses Appwrite's Embeddings service. Requires an API key with embeddings.write."""

    dimension = 768

    def __init__(self, client):
        from appwrite.services.embeddings import Embeddings  # lazy

        self._svc = Embeddings(client)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        res = self._svc.create_text_embeddings(texts=list(texts))
        data = res if isinstance(res, dict) else res.to_dict() if hasattr(res, "to_dict") else res.model_dump()
        return [e["embedding"] for e in data["embeddings"]]
