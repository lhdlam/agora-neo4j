---
name: write_tests
description: >
  Write or fix pytest tests for any layer (domain, service, command, infrastructure).
  Covers DI-based fakes pattern, mock factories, and coverage requirements.
  Use this skill whenever the task involves creating or fixing test files.
---

# Skill: Write or Fix Tests

## When to use
- Creating new test files for any module.
- Adding test cases to existing test files.
- Fixing failing tests after a code change.
- Increasing coverage to meet the 80% threshold.

## Test structure

```
src/tests/
├── conftest.py                        # shared fixtures (currently minimal)
├── commands/
│   ├── test_delete_cmd.py
│   ├── test_import_cmd.py
│   ├── test_match_cmd.py
│   ├── test_post_cmd.py
│   └── test_search_cmd.py
├── domain/
│   ├── test_embed_text.py
│   └── test_models.py
├── infrastructure/
│   └── test_serializers.py
└── services/
    ├── test_listing_service.py
    ├── test_match_service.py
    └── test_search_service.py
```

> `testpaths = ["src/tests"]` in `pyproject.toml`.

---

## Naming conventions (enforced by pytest config)

| Item | Pattern |
|------|---------|
| File | `test_*.py` |
| Class | `Test*` |
| Function | `test_*` |

---

## ✅ Preferred: DI-based Fake pattern (for services)

Services accept ports via constructor — inject fakes directly, no `@patch` needed:

```python
"""Tests for ListingService — infrastructure replaced by in-memory fakes."""
# No type annotations required in tests (ruff ignores ANN in tests/)
from src.services.listing_service import ListingService
from src.domain.models import Listing, ListingType, Category


class FakeStore:
    def __init__(self):
        self.docs = {}

    def ensure_index(self): pass
    def index_doc(self, doc): self.docs[doc["id"]] = doc; return doc["id"]
    def bulk_index(self, docs): [self.docs.update({d["id"]: d}) for d in docs]; return len(docs), 0
    def get_doc(self, id): return self.docs.get(id)
    def delete_doc(self, id): return self.docs.pop(id, None) is not None


class FakeEmbedder:
    def embed(self, text): return [0.1] * 768
    def embed_batch(self, texts, batch_size=32): return [[0.1] * 768 for _ in texts]


class FakeEventBus:
    def __init__(self): self.events = []
    def emit(self, event_type, payload): self.events.append((event_type, payload))


def _make_service(**kwargs):
    return ListingService(
        store=kwargs.get("store") or FakeStore(),
        embedder=kwargs.get("embedder") or FakeEmbedder(),
        event_bus=kwargs.get("event_bus") or FakeEventBus(),
    )


class TestListingServicePost:
    def test_post_returns_doc_id(self):
        store = FakeStore()
        svc = _make_service(store=store)
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        doc_id = svc.post(listing)
        assert doc_id == listing.id
        assert doc_id in store.docs

    def test_post_does_not_mutate_listing(self):
        svc = _make_service()
        listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
        original_embedding = listing.embedding
        svc.post(listing)
        assert listing.embedding == original_embedding  # still None
```

**Key rules:**
- `FakeStore`, `FakeEmbedder`, `FakeEventBus` satisfy ports via structural subtyping.
- **Prefer fixtures from `conftest.py`**: use `fake_store`, `fake_embedder`, `fake_event_bus` pytest fixtures directly in test functions instead of defining inline — reduces boilerplate.
- Keep fakes inline only for one-off overrides (e.g., a store that always raises).
- Do NOT call `make_listing_service()` / `make_search_service()` from tests.

---

## CLI command tests (patch the factory, not the class)

Commands use `make_<svc>_service()` from `src.commands.<cmd>`. Patch there:

```python
from click.testing import CliRunner
from unittest.mock import MagicMock, patch
from src.cli import cli


def _mock_es_ok():
    m = MagicMock()
    m.ping.return_value = True
    return m


class TestSearchCommand:
    def test_search_displays_results(self):
        mock_svc = MagicMock()
        mock_svc.search.return_value = [{"id": "1", "title": "iPhone", "_score": 0.9}]
        with (
            patch("src.commands.search_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.search_cmd.make_search_service", return_value=mock_svc),
        ):
            result = CliRunner().invoke(cli, ["search", "iphone"])
        assert result.exit_code == 0
        assert "iPhone" in result.output

    def test_es_unreachable_exits_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with patch("src.commands.search_cmd.get_es_client", return_value=mock_es):
            result = CliRunner().invoke(cli, ["search", "iphone"])
        assert result.exit_code == 3
```

**Patch path formula:** `src.commands.<module_name>.make_<svc>_service`
| Command file | Patch prefix |
|---|---|
| `src/commands/post.py` | `src.commands.post.` |
| `src/commands/search_cmd.py` | `src.commands.search_cmd.` |
| `src/commands/match_cmd.py` | `src.commands.match_cmd.` |
| `src/commands/import_cmd.py` | `src.commands.import_cmd.` |
| `src/commands/delete_cmd.py` | `src.commands.delete_cmd.` |

---

## Domain model tests

```python
from src.domain.models import Listing, ListingType, Category, GeoLocation, SellerInfo
from src.infrastructure.serializers import listing_to_es_doc  # NOT listing.to_es_doc()

def test_listing_defaults():
    listing = Listing(type=ListingType.SELL, title="Test", category=Category.KHAC)
    assert listing.status.value == "active"
    assert listing.country == "VN"
    assert listing.embedding is None

def test_listing_to_es_doc_excludes_embedding_when_none():
    listing = Listing(type=ListingType.SELL, title="T", category=Category.KHAC)
    doc = listing_to_es_doc(listing)  # NOT listing.to_es_doc()
    assert "embedding" not in doc

def test_listing_to_es_doc_geo_format():
    listing = Listing(
        type=ListingType.SELL, title="T", category=Category.KHAC,
        geo_location=GeoLocation(lat=21.0, lon=105.0),
    )
    doc = listing_to_es_doc(listing)  # NOT listing.to_es_doc()
    assert doc["geo_location"] == {"lat": 21.0, "lon": 105.0}
```

> ⚠️ `listing.to_es_doc()` was **removed** from the domain model. Always use `listing_to_es_doc(listing)` from `src.infrastructure.serializers`.

---

## Infrastructure tests

Mock the underlying `Elasticsearch` client:

```python
from unittest.mock import MagicMock
from src.infrastructure.es_client import ESClient


class TestESClient:
    def _make_client(self, mock_es):
        client = ESClient.__new__(ESClient)
        client._client = mock_es
        client._index_ensured = True
        return client

    def test_get_doc_returns_none_on_not_found(self):
        from elasticsearch import NotFoundError
        mock_es = MagicMock()
        mock_es.get.side_effect = NotFoundError(404, "Not found", {"_id": "x"})
        client = self._make_client(mock_es)
        assert client.get_doc("missing") is None

    def test_get_doc_returns_source(self):
        mock_es = MagicMock()
        mock_es.get.return_value = {"_source": {"id": "abc", "title": "Test"}}
        client = self._make_client(mock_es)
        assert client.get_doc("abc") == {"id": "abc", "title": "Test"}
```

---

## Coverage rules

```bash
make test   # pytest with --cov=src --cov-report=term-missing
```

- Minimum: **80%** overall (`fail_under = 80` in `pyproject.toml`).
- When adding new code, aim for 90%+ on that module.
- Mark untestable lines with `# pragma: no cover`.

---

## Anti-patterns to avoid

- ❌ `@patch("src.services.listing_service.get_es_client")` — services no longer call singletons internally. Use DI fakes instead.
- ❌ `listing.to_es_doc()` — method removed; use `listing_to_es_doc(listing)` from serializers.
- ❌ `ListingService()` / `SearchService()` with no args — constructors require ports now.
- ❌ Patching `src.commands.commands.ListingService` — commands.py is the legacy file; patch the new module paths listed above.
- ❌ Using `monkeypatch` from pytest — use `unittest.mock.patch` instead.
- ❌ `import fastembed` or `import elasticsearch` in tests — always mock or use fakes.
