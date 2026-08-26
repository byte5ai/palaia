"""A deterministic embedder for tests that need vectors but not a model.

Hashed bag-of-words: each token increments one dimension, the vector is L2
normalized. That makes cosine similarity a lexical-overlap measure — enough to
prove the plumbing (pending → ready, KNN returns the right note, fusion runs,
vectors survive a reindex) without downloading 130 MB and burning 437 ms per
note. Semantic quality is measured separately, against the real model, in
``test_hybrid_relevance.py``.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class StubEmbedder:
    """:class:`~palaia_hub.index.Embedder` with no model behind it."""

    def __init__(self, dim: int = 64, name: str = "stub/hashed-bow") -> None:
        self._dim = dim
        self._name = name
        self.calls = 0
        self.embedded: list[str] = []

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return self._name

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        self.embedded.extend(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in _TOKEN_RE.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[digest[0] % self._dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]
