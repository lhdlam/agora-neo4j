"""
Embedder — wraps fastembed (ONNX Runtime, no PyTorch required).
Model: sentence-transformers/paraphrase-multilingual-mpnet-base-v2 — multilingual, 768 dims.
Works on macOS Intel, Apple Silicon, Linux, Windows.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

from src.config import settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding

logger = logging.getLogger(__name__)


class Embedder:
    """Lazy-loading wrapper for the fastembed TextEmbedding model."""

    def __init__(self) -> None:
        self._model: TextEmbedding | None = None

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            logger.info(
                "Loading embedding model '%s'…  (first run downloads ~500MB)",
                settings.EMBEDDING_MODEL,
            )
            try:
                import warnings

                from fastembed import TextEmbedding

                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message=".*mean pooling.*", category=UserWarning
                    )
                    self._model = TextEmbedding(
                        model_name=settings.EMBEDDING_MODEL,
                        # providers: ["CUDAExecutionProvider"] when EMBEDDING_DEVICE="cuda"
                        providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
                        if settings.EMBEDDING_DEVICE.lower() == "cuda"
                        else ["CPUExecutionProvider"],
                    )
                logger.info("Model loaded successfully on device '%s'.", settings.EMBEDDING_DEVICE)
            except ImportError as exc:
                raise RuntimeError(
                    "fastembed is not installed. Run: pip install fastembed"
                ) from exc
        return self._model

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns a list of floats."""
        gen = self.model.embed([text])
        try:
            first = next(iter(gen))
        except StopIteration:
            raise RuntimeError("Embedder returned no vectors for the input text.") from None
        return [float(x) for x in first]

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Embed a list of texts. Returns list of float vectors."""
        results = self.model.embed(texts, batch_size=batch_size)
        # numpy .tolist() is significantly faster than a manual float() list comprehension
        return [
            vec.tolist() if hasattr(vec, "tolist") else [float(x) for x in vec] for vec in results
        ]


@functools.lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Return the process-wide Embedder singleton (thread-safe via lru_cache)."""
    return Embedder()
