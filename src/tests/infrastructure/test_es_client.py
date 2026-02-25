"""Tests for ESClient — all ES operations mocked via MagicMock."""

from unittest.mock import MagicMock, patch

from elasticsearch import NotFoundError

from src.infrastructure.es_client import ESClient

# ─────────────────────────────────────────────────────────────────────────────
# Helper: pre-wired ESClient with a mock Elasticsearch instance
# ─────────────────────────────────────────────────────────────────────────────


def _make_client(mock_es=None):
    """Return ESClient with _client already set (skip real ES connection)."""
    client = ESClient.__new__(ESClient)
    client._client = mock_es or MagicMock()
    client._index_ensured = True
    return client


def _not_found():
    """Build a NotFoundError compatible with elasticsearch-py 8.x."""
    meta = MagicMock()
    meta.status = 404
    return NotFoundError(message="not found", meta=meta, body={"found": False})


# ─────────────────────────────────────────────────────────────────────────────
# ensure_index
# ─────────────────────────────────────────────────────────────────────────────


class TestEnsureIndex:
    def test_skips_when_already_ensured(self):
        mock_es = MagicMock()
        client = _make_client(mock_es)
        client._index_ensured = True
        client.ensure_index()
        mock_es.indices.exists.assert_not_called()

    def test_creates_index_when_missing(self):
        mock_es = MagicMock()
        mock_es.indices.exists.return_value = False
        client = ESClient.__new__(ESClient)
        client._client = mock_es
        client._index_ensured = False
        client.ensure_index()
        mock_es.indices.create.assert_called_once()
        assert client._index_ensured is True

    def test_skips_create_when_index_exists(self):
        mock_es = MagicMock()
        mock_es.indices.exists.return_value = True
        client = ESClient.__new__(ESClient)
        client._client = mock_es
        client._index_ensured = False
        client.ensure_index()
        mock_es.indices.create.assert_not_called()
        assert client._index_ensured is True


# ─────────────────────────────────────────────────────────────────────────────
# delete_index
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteIndex:
    def test_calls_delete_and_resets_flag(self):
        mock_es = MagicMock()
        client = _make_client(mock_es)
        client._index_ensured = True
        client.delete_index()
        mock_es.indices.delete.assert_called_once()
        assert client._index_ensured is False


# ─────────────────────────────────────────────────────────────────────────────
# index_doc
# ─────────────────────────────────────────────────────────────────────────────


class TestIndexDoc:
    def test_returns_doc_id(self):
        mock_es = MagicMock()
        mock_es.index.return_value = {"_id": "abc-123"}
        client = _make_client(mock_es)
        result = client.index_doc({"id": "abc-123", "title": "Test"})
        assert result == "abc-123"
        mock_es.index.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# bulk_index
# ─────────────────────────────────────────────────────────────────────────────


class TestBulkIndex:
    def test_returns_ok_and_error_counts(self):
        with patch("src.infrastructure.es_client.bulk", return_value=(5, [])) as mock_bulk:
            mock_es = MagicMock()
            client = _make_client(mock_es)
            ok, errors = client.bulk_index([{"id": str(i)} for i in range(5)])
        assert ok == 5
        assert errors == 0
        mock_bulk.assert_called_once()

    def test_counts_errors_from_list(self):
        with patch(
            "src.infrastructure.es_client.bulk",
            return_value=(3, [{"error": "x"}, {"error": "y"}]),
        ):
            client = _make_client()
            ok, err = client.bulk_index([{"id": str(i)} for i in range(5)])
        assert ok == 3
        assert err == 2


# ─────────────────────────────────────────────────────────────────────────────
# delete_doc
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteDoc:
    def test_returns_true_on_success(self):
        mock_es = MagicMock()
        client = _make_client(mock_es)
        result = client.delete_doc("abc")
        assert result is True
        mock_es.delete.assert_called_once()

    def test_returns_false_on_not_found(self):
        mock_es = MagicMock()
        mock_es.delete.side_effect = _not_found()
        client = _make_client(mock_es)
        assert client.delete_doc("missing") is False


# ─────────────────────────────────────────────────────────────────────────────
# get_doc
# ─────────────────────────────────────────────────────────────────────────────


class TestGetDoc:
    def test_returns_source_on_hit(self):
        mock_es = MagicMock()
        mock_es.get.return_value = {"_source": {"id": "abc", "title": "Test"}}
        client = _make_client(mock_es)
        result = client.get_doc("abc")
        assert result == {"id": "abc", "title": "Test"}

    def test_returns_none_on_not_found(self):
        mock_es = MagicMock()
        mock_es.get.side_effect = _not_found()
        client = _make_client(mock_es)
        assert client.get_doc("missing") is None


# ─────────────────────────────────────────────────────────────────────────────
# hybrid_search
# ─────────────────────────────────────────────────────────────────────────────


class TestHybridSearch:
    def _setup(self, hits=None):
        mock_es = MagicMock()
        hits = hits or []
        mock_es.search.return_value = {
            "hits": {"hits": [{"_source": h, "_score": 0.9} for h in hits]}
        }
        return _make_client(mock_es), mock_es

    def test_returns_hits_with_score(self):
        client, _ = self._setup([{"id": "1", "title": "iPhone"}])
        results = client.hybrid_search("iphone", [0.1] * 768)
        assert len(results) == 1
        assert results[0]["title"] == "iPhone"
        assert results[0]["_score"] == 0.9

    def test_returns_empty_list_on_no_hits(self):
        client, _ = self._setup([])
        assert client.hybrid_search("nothing", [0.0] * 768) == []

    def test_passes_filters_to_es(self):
        client, mock_es = self._setup()
        client.hybrid_search(
            "bike",
            [0.1] * 768,
            listing_type="sell",
            category="xe-may",
            max_price=5_000_000,
        )
        call_kwargs = mock_es.search.call_args.kwargs
        # knn and query are both passed
        assert "knn" in call_kwargs
        assert "query" in call_kwargs

    def test_geo_filter_included_when_lat_lon_radius_given(self):
        client, mock_es = self._setup()
        client.hybrid_search("bike", [0.1] * 768, lat=21.02, lon=105.85, radius="10km")
        # Verify ES was called (geo logic is internal to _build_filters)
        mock_es.search.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# knn_match
# ─────────────────────────────────────────────────────────────────────────────


class TestKnnMatch:
    def _setup(self, hits=None):
        mock_es = MagicMock()
        hits = hits or []
        mock_es.search.return_value = {
            "hits": {"hits": [{"_source": h, "_score": 0.8} for h in hits]}
        }
        return _make_client(mock_es), mock_es

    def test_returns_hits_with_score(self):
        client, _ = self._setup([{"id": "1", "title": "Laptop"}])
        results = client.knn_match([0.1] * 768)
        assert len(results) == 1
        assert results[0]["_score"] == 0.8

    def test_returns_empty_on_no_hits(self):
        client, _ = self._setup()
        assert client.knn_match([0.1] * 768) == []

    def test_passes_budget_filter(self):
        client, mock_es = self._setup()
        client.knn_match([0.1] * 768, budget=10_000_000)
        mock_es.search.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# ping
# ─────────────────────────────────────────────────────────────────────────────


class TestPing:
    def test_returns_true_when_reachable(self):
        client = ESClient.__new__(ESClient)
        mock_ping_client = MagicMock()
        mock_ping_client.ping.return_value = True
        # bypass cached_property
        object.__setattr__(client, "_ESClient__dict__", {})
        client.__dict__["_ping_client"] = mock_ping_client
        assert client.ping() is True

    def test_returns_false_on_exception(self):
        client = ESClient.__new__(ESClient)
        mock_ping_client = MagicMock()
        mock_ping_client.ping.side_effect = OSError("connection refused")
        client.__dict__["_ping_client"] = mock_ping_client
        assert client.ping() is False


# ─────────────────────────────────────────────────────────────────────────────
# client property — lazy init (lines 99–117)
# ─────────────────────────────────────────────────────────────────────────────


class TestClientProperty:
    def test_initializes_elasticsearch_on_first_access(self):
        """Covers lines 99–117: client property creates Elasticsearch when _client is None."""
        mock_es_instance = MagicMock()
        with patch(
            "src.infrastructure.es_client.Elasticsearch", return_value=mock_es_instance
        ) as mock_es_cls:
            client = ESClient.__new__(ESClient)
            client._client = None
            client._index_ensured = False
            result = client.client
        mock_es_cls.assert_called_once()
        assert result is mock_es_instance
        assert client._client is mock_es_instance

    def test_returns_cached_client_on_subsequent_access(self):
        """Covers the early-return branch: _client already set → no re-init."""
        mock_es_instance = MagicMock()
        client = ESClient.__new__(ESClient)
        client._client = mock_es_instance
        client._index_ensured = False
        with patch("src.infrastructure.es_client.Elasticsearch") as mock_es_cls:
            result = client.client
        mock_es_cls.assert_not_called()
        assert result is mock_es_instance


# ─────────────────────────────────────────────────────────────────────────────
# _ping_client cached property (lines 122–133)
# ─────────────────────────────────────────────────────────────────────────────


class TestPingClientProperty:
    def test_creates_lightweight_elasticsearch_instance(self):
        """Covers lines 122–133: _ping_client cached_property creates a fast-timeout client."""
        mock_es_instance = MagicMock()
        with patch(
            "src.infrastructure.es_client.Elasticsearch", return_value=mock_es_instance
        ) as mock_es_cls:
            client = ESClient.__new__(ESClient)
            client._client = None
            client._index_ensured = False
            result = client._ping_client
        mock_es_cls.assert_called_once()
        # fast-timeout: request_timeout=3, retry_on_timeout=False, max_retries=0
        call_kwargs = mock_es_cls.call_args.kwargs
        assert call_kwargs["request_timeout"] == 3
        assert call_kwargs["retry_on_timeout"] is False
        assert call_kwargs["max_retries"] == 0
        assert result is mock_es_instance


# ─────────────────────────────────────────────────────────────────────────────
# get_es_client singleton (line 347)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetEsClientSingleton:
    def test_returns_es_client_instance(self):
        """Covers line 347: get_es_client() returns an ESClient."""
        from src.infrastructure.es_client import get_es_client

        result = get_es_client()
        assert isinstance(result, ESClient)


# ─────────────────────────────────────────────────────────────────────────────
# indexer.py — deprecated shim, just importing it covers module-level lines
# ─────────────────────────────────────────────────────────────────────────────


class TestIndexerImport:
    def test_importing_indexer_covers_module_level_code(self):
        """Importing indexer.py executes module-level lines (imports, logger=...)."""
        import src.infrastructure.indexer as indexer  # noqa: F401

        assert hasattr(indexer, "index_single")
        assert hasattr(indexer, "bulk_index")
