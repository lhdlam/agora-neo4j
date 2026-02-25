"""
Kafka command consumer — runs inside the agora-worker container.

Subscribes to ``listing.commands``, deserialises each message into a
``CommandMessage``, calls the provided handler, then commits the offset.

Error handling strategy:

* **Infrastructure errors** (ES/network down): do NOT commit the offset.
  Kafka will redeliver the message on the next poll after a backoff sleep.
  The worker is self-healing — it recovers automatically when infra comes back.

* **Bad-message errors** (validation, missing fields): route to the DLQ and
  commit the offset.  Retrying a corrupt message will never succeed.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import signal
import time
from typing import Any

from src.config import settings
from src.domain.models import CommandMessage

logger = logging.getLogger(__name__)

# Exceptions that indicate transient infrastructure failures (resolved at runtime).
# On these we do NOT commit the offset — Kafka will redeliver after backoff.
_INFRA_ERRORS: tuple[type[Exception], ...] = (
    OSError,  # ECONNREFUSED, ETIMEDOUT, etc.
    TimeoutError,
)


class KafkaCommandConsumer:
    """
    Blocking Kafka consumer loop for processing ``CommandMessage`` records.

    Usage::

        consumer = KafkaCommandConsumer(handler=worker_service.handle)
        consumer.start()   # blocks; handles SIGTERM/SIGINT cleanly

    Args:
        handler:       Callable that receives a ``CommandMessage`` and processes it.
        poll_timeout:  Seconds to block waiting for new messages (default 1.0).
        retry_backoff: Seconds to sleep after an infrastructure error (default 5.0).
    """

    def __init__(
        self,
        handler: Callable[[CommandMessage], None],
        poll_timeout: float = 1.0,
        retry_backoff: float = 5.0,
    ) -> None:
        self._handler = handler
        self._poll_timeout = poll_timeout
        self._retry_backoff = retry_backoff
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the blocking consume loop. Exits on SIGTERM / SIGINT."""
        try:
            from elastic_transport import ConnectionError as _ESConnectionError  # noqa: PLC0415
            from kafka import KafkaConsumer as _KafkaConsumer  # noqa: PLC0415
            from kafka import KafkaProducer as _KafkaProducer  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("kafka-python-ng or elasticsearch is not installed.") from exc

        # Extend the infra-error tuple with ES transport errors, available at runtime.
        infra_errors = (*_INFRA_ERRORS, _ESConnectionError)

        consumer = _KafkaConsumer(
            settings.KAFKA_TOPIC_COMMANDS,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,  # manual commit after successful processing
            max_poll_records=settings.KAFKA_MAX_POLL_RECORDS,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )

        dlq_producer = _KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
        )

        self._running = True
        self._setup_signal_handlers()

        logger.info(
            "Worker started — listening on topic '%s' (group=%s)",
            settings.KAFKA_TOPIC_COMMANDS,
            settings.KAFKA_CONSUMER_GROUP,
        )

        try:
            while self._running:
                records = consumer.poll(timeout_ms=int(self._poll_timeout * 1000))
                if not records:
                    continue
                for _tp, messages in records.items():
                    for message in messages:
                        self._process(message, consumer, dlq_producer, infra_errors)
        finally:
            consumer.close()
            dlq_producer.flush(timeout=5)
            dlq_producer.close(timeout=5)
            logger.info("Worker stopped.")

    # ── Per-message processing ─────────────────────────────────────────────────

    def _process(
        self,
        message: Any,
        consumer: Any,
        dlq_producer: Any,
        infra_errors: tuple[type[Exception], ...] = _INFRA_ERRORS,
    ) -> None:
        """
        Process one Kafka message.

        * Success            → commit offset.
        * Infrastructure err → log warning + sleep (no commit → Kafka retries).
        * Bad-message err    → send to DLQ + commit (retry would never succeed).
        """
        raw: dict[str, Any] = message.value
        try:
            cmd = CommandMessage.model_validate(raw)
            logger.info(
                "Processing command action=%s request_id=%s offset=%d",
                cmd.action,
                cmd.request_id,
                message.offset,
            )
            self._handler(cmd)
            consumer.commit()
            logger.info("Command %s committed (offset=%d)", cmd.request_id, message.offset)

        except infra_errors as exc:
            # Transient infra failure (ES down, network blip, etc.).
            # Do NOT commit → Kafka will redeliver this offset after backoff.
            logger.warning(
                "Infrastructure error at offset=%d — backing off %.0fs before retry: %s",
                message.offset,
                self._retry_backoff,
                exc,
            )
            if self._running:
                time.sleep(self._retry_backoff)

        except Exception as exc:
            # Bad message (invalid payload, schema error, business logic error).
            # Retrying won't help → route to DLQ and commit so we move on.
            logger.exception(
                "Bad-message error at offset=%d — routing to DLQ",
                message.offset,
            )
            self._send_to_dlq(dlq_producer, raw, str(exc))
            consumer.commit()

    @staticmethod
    def _send_to_dlq(producer: Any, original: dict[str, Any], error: str) -> None:
        """Forward a failed message to the dead-letter-queue topic."""
        try:
            producer.send(
                settings.KAFKA_TOPIC_DLQ,
                value={"original": original, "error": error, "ts": time.time()},
            )
        except Exception:
            # DLQ failure is a last-ditch effort — log and move on.
            logger.exception("DLQ send failed")

    # ── Signal handling ────────────────────────────────────────────────────────

    def _setup_signal_handlers(self) -> None:
        """Register SIGTERM / SIGINT so the consumer loop exits cleanly."""

        def _stop(signum: int, frame: Any) -> None:  # noqa: ANN401
            logger.info("Signal %d received — stopping worker…", signum)
            self._running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
