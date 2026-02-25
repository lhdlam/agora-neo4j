"""
EmbedderPort — abstract interface for text embedding.

Any concrete adapter (fastembed, OpenAI, sentence-transformers, …) must
satisfy this structural protocol.  The interface is intentionally minimal:
services only need ``embed`` for single strings and ``embed_batch`` for bulk.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedderPort(Protocol):
    """Convert text into dense float vectors."""

    def embed(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Returns:
            A list of floats with length equal to the model's output dimension.
        """
        ...  # pragma: no cover

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """
        Embed a list of texts efficiently.

        Args:
            texts:      Input strings to embed.
            batch_size: Number of texts to process per GPU/CPU batch.

        Returns:
            A list of float vectors in the same order as ``texts``.
        """
        ...  # pragma: no cover
