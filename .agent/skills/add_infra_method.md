---
name: add_infra_method
description: >
  Add a new method to ESClient, the embedder, or Kafka producer.
  Use this skill when the task requires a new Elasticsearch query type,
  a new embedding operation, or a new Kafka event.
---

# Skill: Add an Infrastructure Method

## When to use
- New Elasticsearch query (e.g., aggregation, scroll, update-by-query).
- New embedder operation (e.g., batch embed with progress).
- New Kafka event type.
- Adding a new singleton helper function.

## Architecture constraint

> Infrastructure lives in `src/infrastructure/` and may **only** import from:
> - `src/domain/` (models, enums)
> - `src/config` (settings)
> - Third-party libraries (elasticsearch, fastembed, kafka)
>
> Infrastructure must **never** import from `src/commands/` or `src/services/`.

---

## ESClient: adding a new query method

File: `src/infrastructure/es_client.py`

> Before adding, query Neo4j to see existing methods and avoid duplication:
> ```cypher
> MATCH (m:Component)-[:DEFINED_IN]->(c:Component)
> WHERE c.name CONTAINS "ESClient"
> RETURN m.name, m.signature, m.docstring
> ORDER BY m.line_number
> ```

### Step 1 — Add method to `ESClient`

```python
def new_query_method(
    self,
    param: str,
    *,
    keyword_only_param: int = 10,
) -> list[dict[str, Any]]:
    """
    One-line description.

    Args:
        param:               Description.
        keyword_only_param:  Description (keyword-only for safety).

    Returns:
        List of raw ES document dicts with `_score` attached.
    """
    # Always call ensure_index first if writing to the index
    # self.ensure_index()  ← only for write operations

    query: dict[str, Any] = {
        # build your ES query here
    }

    resp = self.client.search(
        index=settings.ES_INDEX,
        query=query,
        size=keyword_only_param,
        source=True,
    )
    return [{**hit["_source"], "_score": hit["_score"]} for hit in resp["hits"]["hits"]]
```

### Step 2 — Filter builder (reuse existing helper)

```python
# _build_filters() handles: status=active, listing_type, category, max_price, geo_distance
filters = self._build_filters(
    listing_type="sell",   # or None for both
    category=category,
    max_price=budget,
    lat=lat,
    lon=lon,
    radius=radius,
)
```

### Step 3 — Common ES query patterns

**Term filter:**
```python
{"term": {"status": "active"}}
{"term": {"type": "sell"}}
{"term": {"category": "dien-tu"}}
```

**Range filter:**
```python
{"range": {"price": {"lte": 30_000_000}}}
{"range": {"created_at": {"gte": "now-30d"}}}
```

**Aggregation:**
```python
resp = self.client.search(
    index=settings.ES_INDEX,
    aggs={"by_category": {"terms": {"field": "category", "size": 20}}},
    size=0,  # don't return hits, only aggregation
)
buckets = resp["aggregations"]["by_category"]["buckets"]
```

**Update by query:**
```python
self.client.update_by_query(
    index=settings.ES_INDEX,
    query={"term": {"id": listing_id}},
    script={"source": "ctx._source.status = params.status", "params": {"status": "closed"}},
)
```

---

## Embedder: adding a new operation

File: `src/infrastructure/embedder.py`

### Existing API

```python
from src.infrastructure.embedder import get_embedder

embedder = get_embedder()
vectors = embedder.embed(["text1", "text2"])   # returns list[list[float]]
```

### Adding a method

```python
# In TextEmbedder class:
def embed_with_progress(
    self,
    texts: list[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[list[float]]:
    """Embed texts in batches, calling on_progress(done, total) after each batch."""
    results: list[list[float]] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        results.extend(self.embed(batch))
        if on_progress:
            on_progress(min(i + batch_size, len(texts)), len(texts))
    return results
```

---

## Kafka: adding a new event type

File: `src/infrastructure/kafka_producer.py`

### Existing pattern

Events are published as JSON. The topic is `settings.KAFKA_TOPIC_LISTING`.

```python
def publish_new_event(self, listing_id: str, event_type: str, data: dict[str, Any]) -> None:
    """
    Publish a new event type.

    Never raises — Kafka failures are logged and swallowed.
    """
    if not settings.KAFKA_ENABLED:
        return
    try:
        payload = {
            "event": event_type,
            "listing_id": listing_id,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._producer.send(settings.KAFKA_TOPIC_LISTING, payload)
        logger.debug("Kafka event published: %s id=%s", event_type, listing_id)
    except Exception as exc:  # noqa: BLE001 — intentional catch-all; Kafka must not block
        logger.warning("Kafka publish failed: %s", exc)
```

> ⚠️ Kafka errors must **never** propagate — always catch and log only.

---

## Testing infrastructure methods

Always mock the underlying client:

```python
from unittest.mock import MagicMock
from src.infrastructure.es_client import ESClient


def test_new_query_method():
    mock_es = MagicMock()
    mock_es.search.return_value = {
        "hits": {
            "hits": [
                {"_source": {"id": "1", "title": "Test"}, "_score": 0.9}
            ]
        }
    }
    client = ESClient()
    client._client = mock_es
    client._index_ensured = True

    results = client.new_query_method("some-param")

    assert len(results) == 1
    assert results[0]["id"] == "1"
    assert results[0]["_score"] == 0.9
    mock_es.search.assert_called_once()
```

---

## Singleton pattern reminder

All infrastructure components use `functools.lru_cache(maxsize=1)`:

```python
@functools.lru_cache(maxsize=1)
def get_es_client() -> ESClient:
    return ESClient()

@functools.lru_cache(maxsize=1)
def get_embedder() -> TextEmbedder:
    return TextEmbedder()
```

In tests, mock the **function** (`patch("src.infrastructure.es_client.get_es_client")`), not the class, to avoid creating a real singleton.
