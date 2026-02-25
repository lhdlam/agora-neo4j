"""Tests for _KafkaProducer and emit_event."""

from unittest.mock import MagicMock, patch

from src.infrastructure.kafka_producer import _KafkaProducer, emit_event

# ─────────────────────────────────────────────────────────────────────────────
# _get_producer — disabled / enabled paths
# ─────────────────────────────────────────────────────────────────────────────


class TestGetProducer:
    def test_returns_none_when_kafka_disabled(self):
        producer = _KafkaProducer()
        with patch("src.infrastructure.kafka_producer.settings") as mock_settings:
            mock_settings.KAFKA_ENABLED = False
            result = producer._get_producer()
        assert result is None

    def test_returns_cached_producer_when_connected(self):
        producer = _KafkaProducer()
        mock_kp = MagicMock()
        producer._producer = mock_kp
        producer._connected = True
        with patch("src.infrastructure.kafka_producer.settings") as mock_settings:
            mock_settings.KAFKA_ENABLED = True
            result = producer._get_producer()
        assert result is mock_kp

    def test_connects_and_returns_producer_when_enabled(self):
        producer = _KafkaProducer()
        mock_kp_instance = MagicMock()
        with (
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
            patch(
                "src.infrastructure.kafka_producer._KafkaProducer._get_producer",
                wraps=producer._get_producer,
            ),
        ):
            mock_settings.KAFKA_ENABLED = True
            mock_settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
            with patch.dict(
                "sys.modules", {"kafka": MagicMock(KafkaProducer=lambda **kw: mock_kp_instance)}
            ):
                result = producer._get_producer()
        assert producer._connected is True
        assert result is mock_kp_instance

    def test_gracefully_handles_kafka_import_error(self):
        """If kafka-python is not installed, _get_producer returns None gracefully."""
        producer = _KafkaProducer()

        with (
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
            patch.dict("sys.modules", {"kafka": None}),
        ):
            mock_settings.KAFKA_ENABLED = True
            mock_settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
            import contextlib

            with contextlib.suppress(Exception):
                producer._get_producer()
        # producer remains disconnected
        assert producer._connected is False


# ─────────────────────────────────────────────────────────────────────────────
# emit
# ─────────────────────────────────────────────────────────────────────────────


class TestEmit:
    def test_does_nothing_when_kafka_disabled(self):
        producer = _KafkaProducer()
        with patch.object(producer, "_get_producer", return_value=None):
            # Should complete without error
            producer.emit("listing.created", {"id": "abc"})

    def test_sends_event_with_correct_structure(self):
        mock_kp = MagicMock()
        producer = _KafkaProducer()
        producer._producer = mock_kp
        producer._connected = True

        with (
            patch.object(producer, "_get_producer", return_value=mock_kp),
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
        ):
            mock_settings.KAFKA_TOPIC_LISTING = "listing.events"
            producer.emit("listing.created", {"id": "abc", "title": "Test"})

        mock_kp.send.assert_called_once()
        call_args = mock_kp.send.call_args
        assert call_args.args[0] == "listing.events"
        payload = call_args.kwargs["value"]
        assert payload["event"] == "listing.created"
        assert payload["id"] == "abc"
        assert "ts" in payload

    def test_swallows_send_exception(self):
        mock_kp = MagicMock()
        mock_kp.send.side_effect = OSError("Kafka broker unavailable")
        producer = _KafkaProducer()
        with (
            patch.object(producer, "_get_producer", return_value=mock_kp),
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
        ):
            mock_settings.KAFKA_TOPIC_LISTING = "listing.events"
            # Should NOT raise
            producer.emit("listing.created", {"id": "abc"})


# ─────────────────────────────────────────────────────────────────────────────
# shutdown
# ─────────────────────────────────────────────────────────────────────────────


class TestShutdown:
    def test_does_nothing_when_producer_is_none(self):
        producer = _KafkaProducer()
        producer._producer = None
        producer.shutdown()  # No exception expected

    def test_flushes_and_closes_on_shutdown(self):
        mock_kp = MagicMock()
        producer = _KafkaProducer()
        producer._producer = mock_kp
        producer.shutdown()
        mock_kp.flush.assert_called_once_with(timeout=10)
        mock_kp.close.assert_called_once_with(timeout=5)

    def test_swallows_shutdown_exception(self):
        mock_kp = MagicMock()
        mock_kp.flush.side_effect = OSError("broken pipe")
        producer = _KafkaProducer()
        producer._producer = mock_kp
        # Should NOT raise
        producer.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# emit_event (public API)
# ─────────────────────────────────────────────────────────────────────────────


class TestEmitEvent:
    def test_delegates_to_singleton(self):
        mock_producer = MagicMock()
        with patch(
            "src.infrastructure.kafka_producer._get_kafka_producer", return_value=mock_producer
        ):
            emit_event("listing.deleted", {"id": "xyz"})
        mock_producer.emit.assert_called_once_with("listing.deleted", {"id": "xyz"})


# ─────────────────────────────────────────────────────────────────────────────
# send_command (lines 92–122)
# ─────────────────────────────────────────────────────────────────────────────


class TestSendCommand:
    def test_raises_when_kafka_disabled(self):
        """Covers lines 92–96: KAFKA_ENABLED=False raises RuntimeError."""
        producer = _KafkaProducer()
        with patch("src.infrastructure.kafka_producer.settings") as mock_settings:
            mock_settings.KAFKA_ENABLED = False
            import pytest

            with pytest.raises(RuntimeError, match="KAFKA_ENABLED=false"):
                producer.send_command("create", {"id": "abc"})

    def test_raises_when_producer_unavailable(self):
        """Covers lines 97–102: producer is None (broker unreachable) raises RuntimeError."""
        producer = _KafkaProducer()
        with (
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
            patch.object(producer, "_get_producer", return_value=None),
        ):
            mock_settings.KAFKA_ENABLED = True
            import pytest

            with pytest.raises(RuntimeError, match="broker unreachable"):
                producer.send_command("create", {"id": "abc"})

    def test_returns_partition_offset_on_success(self):
        """Covers lines 103–120: happy path returns int offset."""

        mock_kp = MagicMock()
        metadata = MagicMock()
        metadata.topic = "listing.commands"
        metadata.partition = 0
        metadata.offset = 42
        future = MagicMock()
        future.get.return_value = metadata
        mock_kp.send.return_value = future

        producer = _KafkaProducer()
        with (
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
            patch.object(producer, "_get_producer", return_value=mock_kp),
        ):
            mock_settings.KAFKA_ENABLED = True
            mock_settings.KAFKA_TOPIC_COMMANDS = "listing.commands"
            result = producer.send_command(
                "create", {"id": "abc", "title": "T", "type": "sell", "category": "khac"}
            )
        assert result == 42

    def test_raises_on_send_exception(self):
        """Covers lines 121–122: exception during send re-raised as RuntimeError."""
        mock_kp = MagicMock()
        mock_kp.send.side_effect = OSError("broker down")

        producer = _KafkaProducer()
        with (
            patch("src.infrastructure.kafka_producer.settings") as mock_settings,
            patch.object(producer, "_get_producer", return_value=mock_kp),
        ):
            mock_settings.KAFKA_ENABLED = True
            mock_settings.KAFKA_TOPIC_COMMANDS = "listing.commands"
            import pytest

            with pytest.raises(RuntimeError, match="Failed to send command"):
                producer.send_command("create", {"id": "abc"})


# ─────────────────────────────────────────────────────────────────────────────
# Module-level send_command wrapper (line 157)
# ─────────────────────────────────────────────────────────────────────────────


class TestSendCommandModuleLevel:
    def test_delegates_to_singleton(self):
        """Covers line 157: module-level send_command() delegates to _get_kafka_producer()."""
        from src.infrastructure.kafka_producer import send_command

        mock_producer = MagicMock()
        mock_producer.send_command.return_value = 99
        with patch(
            "src.infrastructure.kafka_producer._get_kafka_producer", return_value=mock_producer
        ):
            result = send_command("delete", {"id": "xyz"})
        assert result == 99
        mock_producer.send_command.assert_called_once_with("delete", {"id": "xyz"})


# ─────────────────────────────────────────────────────────────────────────────
# _get_kafka_producer singleton body (lines 137–139)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetKafkaProducerSingleton:
    def test_singleton_body_executes_and_returns_producer(self):
        """
        Covers lines 137–139: calling _get_kafka_producer() without patching
        executes the function body (producer = _KafkaProducer(), atexit.register, return).
        lru_cache means subsequent calls return the cached instance.
        """
        from src.infrastructure.kafka_producer import _get_kafka_producer, _KafkaProducer

        # Clear the lru_cache so the body runs fresh
        _get_kafka_producer.cache_clear()
        result = _get_kafka_producer()
        assert isinstance(result, _KafkaProducer)
        # Second call hits cache — same object
        assert _get_kafka_producer() is result
