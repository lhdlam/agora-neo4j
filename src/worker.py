"""
Agora Worker — standalone Kafka consumer process.

Runs inside the ``agora-worker`` Docker container.
Listens on the ``listing.commands`` topic and delegates to ``WorkerService``.

Usage (Docker)::

    docker compose -f infrastructure/docker-compose.worker.yml up

Usage (local dev with Kafka running)::

    KAFKA_WRITE_MODE=true KAFKA_ENABLED=true python -m src.worker

The process exits cleanly on SIGTERM / SIGINT (sent by Docker on stop).
"""

from __future__ import annotations

import logging
import sys

from src.infrastructure.kafka_consumer import KafkaCommandConsumer
from src.services.factories import make_worker_service

# Configure logging for the worker process — structured, no Rich formatting.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
# Suppress kafka-python internal noise (connection retries, heartbeats, etc.)
for _noisy in ("kafka.conn", "kafka.client", "kafka.producer.sender"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    """Wire up services and start the blocking consumer loop."""
    logger.info("Agora Worker starting…")
    worker_service = make_worker_service()
    consumer = KafkaCommandConsumer(handler=worker_service.handle)
    consumer.start()


if __name__ == "__main__":  # pragma: no cover
    main()
