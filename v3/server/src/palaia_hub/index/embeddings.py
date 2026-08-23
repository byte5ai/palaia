"""Chunking and local embeddings.

**Why everything here is off the write path.** SPEC-003 Q4 measured 437 ms to
embed one note against 0.6 ms to FTS-index it — a factor of ~700. Embedding
synchronously would turn a sub-10 ms note write into a half-second one, so
the write path stops at "chunks written, state pending" and a background
worker drains the backlog (see :class:`~.service.VaultIndex`). That is a
hard constraint from the spike, not a preference.

**Chunking.** Notes are split on blank lines into ~``max_chars`` windows with
a small overlap, so an observation list and the paragraph introducing it tend
to land in the same chunk. Each chunk carries a content fingerprint: on
re-index, a chunk whose fingerprint is unchanged keeps its vector, so editing
one paragraph of a long note re-embeds one chunk instead of the note.

**Model choice** is config (:class:`EmbeddingConfig`). The default was picked
by benchmark, not by reputation — run ``python -m palaia_hub.index.bench`` to
reproduce the comparison.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .models import fingerprint

logger = logging.getLogger("palaia_hub.index.embeddings")

#: Default local model, chosen by measurement rather than reputation — the
#: SPEC-003 follow-up the spike asked for ("investigate ... a smaller/faster
#: model before committing to bge-small-en-v1.5 as *the* default").
#: :mod:`palaia_hub.index.bench` on the golden vault, 4 vCPUs, 45 chunks:
#:
#: =================================== ======== ============
#: model                               batch    ms/chunk
#: =================================== ======== ============
#: sentence-transformers/all-MiniLM-L6-v2   8    **15.6**
#: sentence-transformers/all-MiniLM-L6-v2  32      17.7
#: BAAI/bge-small-en-v1.5                   8     152.8
#: BAAI/bge-small-en-v1.5                  32     224.0
#: =================================== ======== ============
#:
#: ~10x faster at the same 384 dimensions, so the index schema is unaffected
#: by the choice and a deployment that prefers bge-small only has to set
#: ``model`` and re-embed. FTS on the same corpus: 0.013 ms/chunk — three
#: orders of magnitude cheaper, which is why embedding is async, full stop.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

#: Texts per ``embed()`` call, and chunks claimed per worker transaction. 8 was
#: the measured optimum on 4 vCPUs (above); bigger batches lost ~12% there,
#: probably to thread oversubscription, so re-run the benchmark before raising
#: it on very different hardware.
DEFAULT_BATCH_SIZE = 8

#: Chunk sizing. ~1200 characters is roughly 250-300 tokens, comfortably
#: inside the 512-token window of both candidate models.
DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 120


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """How this index embeds — or that it does not."""

    enabled: bool = True
    model: str = DEFAULT_MODEL
    batch_size: int = DEFAULT_BATCH_SIZE
    max_chars: int = DEFAULT_MAX_CHARS
    overlap_chars: int = DEFAULT_OVERLAP_CHARS
    threads: int | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    """One embedding unit of a note."""

    seq: int
    text: str
    fingerprint: str


class Embedder(Protocol):
    """Minimal embedding interface — a list of texts in, vectors out.

    A protocol rather than a class so tests can substitute a deterministic
    stub (embedding a real model in a unit test would dominate its runtime)
    and so a future remote embedder is a drop-in.
    """

    @property
    def dim(self) -> int:
        """Vector dimension."""
        ...

    @property
    def name(self) -> str:
        """Model identifier, stored in the index's ``meta`` table."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts``, returning one vector per input, in order."""
        ...


class FastEmbedEmbedder:
    """:class:`Embedder` backed by fastembed's local ONNX models.

    Construction loads the model (and downloads it on first use), which the
    spike measured at ~0.6 s warm — so it happens on the background worker's
    first batch, never on a query or a write.
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self._config = config or EmbeddingConfig()
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - optional extra
            raise EmbedderUnavailableError(
                f"fastembed is not installed ({exc}). Fix: install the "
                f"'embeddings' extra (uv sync installs it for this workspace), "
                f"or run with embeddings disabled — search degrades to FTS."
            ) from exc
        kwargs: dict[str, object] = {"model_name": self._config.model}
        if self._config.threads is not None:
            kwargs["threads"] = self._config.threads
        try:
            self._model = TextEmbedding(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - fastembed raises broadly
            raise EmbedderUnavailableError(
                f"could not load embedding model {self._config.model!r}: {exc}. "
                f"Fix: check the model name, or the network/cache for its "
                f"first download. Search stays available as FTS-only."
            ) from exc
        self._dim = len(self.embed(["dimension probe"])[0])

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return self._config.model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.embed(list(texts), batch_size=self._config.batch_size)
        return [[float(value) for value in vector] for vector in vectors]


class EmbedderUnavailableError(RuntimeError):
    """No embedder could be built — the index runs FTS-only and says so."""


def build_embedder(config: EmbeddingConfig) -> Embedder:
    """Construct the configured embedder (currently: fastembed only)."""
    return FastEmbedEmbedder(config)


# --------------------------------------------------------------------- chunking


def embeddable_text(title: str, body: str, observations: Sequence[str]) -> str:
    """The text an embedding sees for one note.

    Title first (it is the strongest short signal), then the body, then the
    observation lines — which the spike's ``entity_text`` did too, and which
    matters because an observation's fact is often nowhere else in the prose.
    """
    parts = [title.strip(), body.strip()]
    parts.extend(text.strip() for text in observations)
    return "\n".join(part for part in parts if part)


def chunk_text(
    text: str, *, max_chars: int = DEFAULT_MAX_CHARS, overlap_chars: int = DEFAULT_OVERLAP_CHARS
) -> list[Chunk]:
    """Split ``text`` into chunks, preferring paragraph boundaries.

    Paragraphs are packed greedily into ``max_chars`` windows. ``overlap_chars``
    applies only where a *single* paragraph exceeds the window and has to be
    hard-split mid-text: there the next piece repeats the tail of the previous
    one, so a phrase straddling the cut survives in at least one chunk.
    """
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [Chunk(0, normalized, fingerprint(normalized))]

    step = max(1, max_chars - max(0, overlap_chars))
    units: list[str] = []
    for raw in normalized.split("\n\n"):
        para = raw.strip()
        while len(para) > max_chars:
            units.append(para[:max_chars])
            para = para[step:].strip()
        if para:
            units.append(para)

    windows: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            windows.append(current)
        current = unit
    if current:
        windows.append(current)

    return [Chunk(seq, window, fingerprint(window)) for seq, window in enumerate(windows)]


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MAX_CHARS",
    "DEFAULT_MODEL",
    "DEFAULT_OVERLAP_CHARS",
    "Chunk",
    "EmbedderUnavailableError",
    "EmbeddingConfig",
    "Embedder",
    "FastEmbedEmbedder",
    "build_embedder",
    "chunk_text",
    "embeddable_text",
]
