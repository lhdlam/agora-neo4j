"""
Kafka producer — optional event bus integration.
Gracefully degrades when Kafka is disabled or unreachable.
"""

from __future__ import annotations

import atexit
from datetime import UTC, datetime
import functools
import json
import logging
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


class _KafkaProducer:
    """
    Thin wrapper around KafkaProducer with lazy initialization and graceful
    degradation.  Use the module-level ``emit_event()`` function; do not
    instantiate this class directly.
    """

    def __init__(self) -> None:
        self._producer: Any = None  # KafkaProducer is a lazy import — Any is intentional
        self._connected: bool = False

    def _get_producer(self) -> Any:
        """Return a lazily-initialized KafkaProducer, or None if unavailable."""
        if not settings.KAFKA_ENABLED:
            return None

        if self._connected:
            return self._producer

        try:
            from kafka import KafkaProducer

            self._producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=3,
            )
            self._connected = True
            logger.info("Kafka producer connected to %s", settings.KAFKA_BOOTSTRAP_SERVERS)
        except Exception as exc:
            # Kafka failure must never block the happy path — log and continue.
            logger.warning("Kafka unavailable – events will not be emitted. Reason: %s", exc)
            # Do NOT set self._connected = True so the next call retries.

        return self._producer

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        Publish an event to the configured Kafka topic.
        Does nothing silently if Kafka is disabled or unavailable.
        """
        producer = self._get_producer()
        if producer is None:
            return
        try:
            producer.send(
                settings.KAFKA_TOPIC_LISTING,
                value={
                    "event": event_type,
                    "ts": datetime.now(UTC).isoformat(),
                    **payload,
                },
            )
            # Do NOT flush() here — flushing after every event blocks the caller.
            # Events are flushed in batch on process shutdown via shutdown().
        except Exception as exc:
            logger.warning("Failed to emit Kafka event '%s': %s", event_type, exc)

    def send_command(self, action: str, payload: dict[str, Any]) -> int:
        """
        Send a command message to the ``listing.commands`` topic.

        Blocks until the broker acknowledges the record (up to 10 s) so the
        caller receives the partition offset for user feedback.

        Returns:
            The Kafka partition offset of the produced record.

        Raises:
            RuntimeError: If Kafka is disabled, unavailable, or the send times out.
        """
        if not settings.KAFKA_ENABLED:
            raise RuntimeError(
                "KAFKA_WRITE_MODE is enabled but KAFKA_ENABLED=false. "
                "Set KAFKA_ENABLED=true and ensure the broker is reachable."
            )
        producer = self._get_producer()
        if producer is None:
            raise RuntimeError(
                "Kafka producer unavailable — broker unreachable. "
                "Check KAFKA_BOOTSTRAP_SERVERS and broker status."
            )
        try:
            from src.domain.models import CommandAction, CommandMessage  # noqa: PLC0415

            msg = CommandMessage(action=CommandAction(action), payload=payload)
            future = producer.send(
                settings.KAFKA_TOPIC_COMMANDS,
                value=msg.model_dump(mode="json"),
            )
            metadata = future.get(timeout=10)  # block for ack — returns RecordMetadata
            logger.info(
                "Command '%s' queued → topic=%s partition=%d offset=%d request_id=%s",
                action,
                metadata.topic,
                metadata.partition,
                metadata.offset,
                msg.request_id,
            )
            return int(metadata.offset)
        except Exception as exc:
            raise RuntimeError(f"Failed to send command '{action}' to Kafka: {exc}") from exc

    def shutdown(self) -> None:
        """Flush and close the Kafka producer on process exit."""
        if self._producer is not None:
            try:
                self._producer.flush(timeout=10)
                self._producer.close(timeout=5)
            except Exception as exc:
                logger.warning("Error during Kafka producer shutdown: %s", exc)


@functools.lru_cache(maxsize=1)
def _get_kafka_producer() -> _KafkaProducer:
    """Return the process-wide _KafkaProducer singleton."""
    producer = _KafkaProducer()
    atexit.register(producer.shutdown)
    return producer


def emit_event(event_type: str, payload: dict[str, Any]) -> None:
    """
    Publish an event to the configured Kafka topic.
    Does nothing silently if Kafka is disabled or unavailable.
    """
    _get_kafka_producer().emit(event_type, payload)


def send_command(action: str, payload: dict[str, Any]) -> int:
    """
    Send a command to the ``listing.commands`` Kafka topic.

    Blocks for broker ack and returns the partition offset.
    Raises ``RuntimeError`` if Kafka is unavailable.
    """
    return _get_kafka_producer().send_command(action, payload)
