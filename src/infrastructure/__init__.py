"""Infrastructure layer — external system adapters (Elasticsearch, Embedder, Kafka)."""

from src.infrastructure.embedder import Embedder, get_embedder
from src.infrastructure.es_client import ESClient, get_es_client
from src.infrastructure.kafka_producer import emit_event

__all__ = [
    "ESClient",
    "get_es_client",
    "Embedder",
    "get_embedder",
    "emit_event",
]
