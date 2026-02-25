"""Tests for Embedder — fastembed mocked, no model download required."""

from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.embedder import Embedder

# ─────────────────────────────────────────────────────────────────────────────
# Helpers: build a fake fastembed module
# ─────────────────────────────────────────────────────────────────────────────


def _fake_fastembed(vectors=None):
    """Return a sys.modules-compatible fake fastembed module."""
    if vectors is None:
        vectors = [[0.1] * 768]

    mock_model = MagicMock()
    mock_model.embed.return_value = iter(vectors)

    mock_module = ModuleType("fastembed")
    mock_module.TextEmbedding = MagicMock(return_value=mock_model)
    return mock_module, mock_model


# ─────────────────────────────────────────────────────────────────────────────
# Embedder.model (lazy loading)
# ─────────────────────────────────────────────────────────────────────────────


class TestEmbedderModelProperty:
    def test_loads_model_on_first_access(self):
        fake_mod, mock_model_instance = _fake_fastembed()
        with patch.dict("sys.modules", {"fastembed": fake_mod}):
            embedder = Embedder()
            _ = embedder.model
        fake_mod.TextEmbedding.assert_called_once()

    def test_cached_after_first_load(self):
        fake_mod, _ = _fake_fastembed()
        with patch.dict("sys.modules", {"fastembed": fake_mod}):
            embedder = Embedder()
            _ = embedder.model
            _ = embedder.model  # second access
        # TextEmbedding constructor called only once
        assert fake_mod.TextEmbedding.call_count == 1

    def test_raises_runtime_error_when_fastembed_missing(self):
        embedder = Embedder()
        with patch.dict("sys.modules", {"fastembed": None}):
            with pytest.raises(RuntimeError, match="fastembed is not installed"):
                _ = embedder.model

    def test_uses_cpu_provider_by_default(self):
        fake_mod, _ = _fake_fastembed()
        with (
            patch.dict("sys.modules", {"fastembed": fake_mod}),
            patch("src.infrastructure.embedder.settings") as mock_settings,
        ):
            mock_settings.EMBEDDING_MODEL = "test-model"
            mock_settings.EMBEDDING_DEVICE = "cpu"
            embedder = Embedder()
            _ = embedder.model
        call_kwargs = fake_mod.TextEmbedding.call_args.kwargs
        assert "CPUExecutionProvider" in call_kwargs["providers"]
        assert "CUDAExecutionProvider" not in call_kwargs["providers"]

    def test_uses_cuda_provider_when_device_is_cuda(self):
        fake_mod, _ = _fake_fastembed()
        with (
            patch.dict("sys.modules", {"fastembed": fake_mod}),
            patch("src.infrastructure.embedder.settings") as mock_settings,
        ):
            mock_settings.EMBEDDING_MODEL = "test-model"
            mock_settings.EMBEDDING_DEVICE = "cuda"
            embedder = Embedder()
            _ = embedder.model
        call_kwargs = fake_mod.TextEmbedding.call_args.kwargs
        assert "CUDAExecutionProvider" in call_kwargs["providers"]


# ─────────────────────────────────────────────────────────────────────────────
# Embedder.embed
# ─────────────────────────────────────────────────────────────────────────────


class TestEmbedderEmbed:
    def _make_embedder_with_model(self, vectors=None):
        """Return an Embedder whose model is already set to a mock."""
        fake_mod, mock_model = _fake_fastembed(vectors)
        embedder = Embedder()
        embedder._model = mock_model
        return embedder, mock_model

    def test_returns_list_of_floats(self):
        vec = [0.1, 0.2, 0.3] * 256  # 768 dims
        embedder, mock_model = self._make_embedder_with_model([vec])
        mock_model.embed.return_value = iter([vec])
        result = embedder.embed("test text")
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)
        assert len(result) == 768

    def test_calls_model_embed_with_list(self):
        embedder, mock_model = self._make_embedder_with_model([[0.0] * 768])
        mock_model.embed.return_value = iter([[0.0] * 768])
        embedder.embed("hello")
        mock_model.embed.assert_called_once_with(["hello"])

    def test_raises_when_model_returns_empty(self):
        embedder, mock_model = self._make_embedder_with_model([])
        mock_model.embed.return_value = iter([])  # empty generator
        with pytest.raises(RuntimeError, match="no vectors"):
            embedder.embed("empty")


# ─────────────────────────────────────────────────────────────────────────────
# Embedder.embed_batch
# ─────────────────────────────────────────────────────────────────────────────


class TestEmbedderEmbedBatch:
    def _make_embedder_with_model(self, vectors):
        fake_mod, mock_model = _fake_fastembed(vectors)
        embedder = Embedder()
        embedder._model = mock_model
        return embedder, mock_model

    def test_returns_list_of_vectors(self):
        vecs = [[0.1] * 768, [0.2] * 768]
        embedder, mock_model = self._make_embedder_with_model(vecs)
        mock_model.embed.return_value = iter(vecs)
        result = embedder.embed_batch(["text1", "text2"])
        assert len(result) == 2
        assert len(result[0]) == 768

    def test_uses_tolist_when_available(self):
        """Numpy-like arrays with .tolist() should use the fast path."""
        mock_vec = MagicMock()
        mock_vec.tolist.return_value = [0.5] * 768

        embedder, mock_model = self._make_embedder_with_model([mock_vec])
        mock_model.embed.return_value = iter([mock_vec])

        result = embedder.embed_batch(["text"])
        mock_vec.tolist.assert_called_once()
        assert result[0] == [0.5] * 768

    def test_falls_back_to_float_conversion(self):
        """Objects without .tolist() use manual float() conversion."""
        raw = [1, 2, 3]  # plain list — no .tolist() attribute

        embedder, mock_model = self._make_embedder_with_model([raw])
        mock_model.embed.return_value = iter([raw])

        result = embedder.embed_batch(["text"])
        assert result == [[1.0, 2.0, 3.0]]

    def test_passes_batch_size_to_model(self):
        vecs = [[0.1] * 768]
        embedder, mock_model = self._make_embedder_with_model(vecs)
        mock_model.embed.return_value = iter(vecs)
        embedder.embed_batch(["text"], batch_size=16)
        mock_model.embed.assert_called_once_with(["text"], batch_size=16)


# ─────────────────────────────────────────────────────────────────────────────
# get_embedder singleton (line 78)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetEmbedderSingleton:
    def test_returns_embedder_instance(self):
        """Covers line 78 of embedder.py: get_embedder() returns an Embedder."""
        from src.infrastructure.embedder import Embedder, get_embedder

        result = get_embedder()
        assert isinstance(result, Embedder)

    def test_returns_same_instance_on_repeated_calls(self):
        """lru_cache(maxsize=1) guarantees singleton behaviour."""
        from src.infrastructure.embedder import get_embedder

        first = get_embedder()
        second = get_embedder()
        assert first is second
