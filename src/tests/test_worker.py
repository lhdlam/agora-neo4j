"""Tests for src/worker.py — verifies main() wires worker service + starts consumer."""

from unittest.mock import MagicMock, patch


class TestWorkerMain:
    def test_main_creates_worker_service_and_starts_consumer(self):
        """Covers worker.py lines 39–44: main() wires up services and calls consumer.start()."""
        mock_worker_service = MagicMock()
        mock_consumer_instance = MagicMock()

        with (
            patch(
                "src.worker.make_worker_service", return_value=mock_worker_service
            ) as mock_factory,
            patch(
                "src.worker.KafkaCommandConsumer", return_value=mock_consumer_instance
            ) as mock_consumer_cls,
        ):
            from src.worker import main

            main()

        mock_factory.assert_called_once()
        mock_consumer_cls.assert_called_once_with(handler=mock_worker_service.handle)
        mock_consumer_instance.start.assert_called_once()

    def test_main_passes_handle_method_as_handler(self):
        """Verifies that the worker service's handle method is used as the consumer handler."""
        mock_worker_service = MagicMock()
        mock_consumer_instance = MagicMock()

        with (
            patch("src.worker.make_worker_service", return_value=mock_worker_service),
            patch(
                "src.worker.KafkaCommandConsumer", return_value=mock_consumer_instance
            ) as mock_consumer_cls,
        ):
            from src.worker import main

            main()

        _, kwargs = mock_consumer_cls.call_args
        assert kwargs["handler"] is mock_worker_service.handle
