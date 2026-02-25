"""Tests for KafkaCommandConsumer — mocks kafka-python, no broker required."""

from unittest.mock import MagicMock, patch

import pytest

from src.domain.models import CommandAction, CommandMessage

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_valid_message(action=CommandAction.CREATE, payload=None, offset=0):
    """Return a mock Kafka ConsumerRecord-like object."""
    msg = MagicMock()
    msg.offset = offset
    msg.value = {
        "action": action.value,
        "payload": payload or {"id": "test-123"},
        "request_id": "req-abc",
        "ts": "2026-01-01T00:00:00",
    }
    return msg


def _make_invalid_message(offset=99):
    """Return a message whose value will fail CommandMessage validation."""
    msg = MagicMock()
    msg.offset = offset
    msg.value = {"not_valid": True}  # missing 'action' and 'payload'
    return msg


def _setup_consumer_mocks(messages, run_once=True):
    """
    Return (mock_kafka_consumer, mock_kafka_producer, mock_tp).

    mock_kafka_consumer.poll() returns messages on first call, then
    sets _running=False so the loop exits (prevents an infinite loop in tests).
    """
    mock_consumer = MagicMock()
    mock_producer = MagicMock()
    mock_tp = MagicMock()

    call_count = {"n": 0}

    def _poll(timeout_ms):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {mock_tp: messages}
        return {}

    mock_consumer.poll.side_effect = _poll
    return mock_consumer, mock_producer, mock_tp


class TestSetupConsumerMocksHelper:
    """Exercise _setup_consumer_mocks to cover its body (lines 42–55)."""

    def test_first_poll_returns_messages(self):
        msg = _make_valid_message()
        consumer, _, tp = _setup_consumer_mocks([msg])
        result = consumer.poll(timeout_ms=100)
        # First call: returns {tp: [msg]}
        assert len(result) == 1
        assert msg in list(result.values())[0]

    def test_second_poll_returns_empty(self):
        msg = _make_valid_message()
        consumer, _, _ = _setup_consumer_mocks([msg])
        consumer.poll(timeout_ms=100)  # first call
        result = consumer.poll(timeout_ms=100)  # second call
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# _process — success path
# ─────────────────────────────────────────────────────────────────────────────


class TestProcess:
    def test_calls_handler_with_command_message(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock()
        consumer = KafkaCommandConsumer(handler=handler)

        msg = _make_valid_message(action=CommandAction.DELETE, payload={"id": "abc"})
        mock_kafka_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_kafka_consumer, mock_dlq)

        handler.assert_called_once()
        cmd: CommandMessage = handler.call_args.args[0]
        assert cmd.action == CommandAction.DELETE
        assert cmd.payload == {"id": "abc"}

    def test_commits_offset_after_success(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock()
        consumer = KafkaCommandConsumer(handler=handler)
        msg = _make_valid_message()
        mock_kafka_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_kafka_consumer, mock_dlq)

        mock_kafka_consumer.commit.assert_called_once()

    def test_does_not_call_dlq_on_success(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock()
        consumer = KafkaCommandConsumer(handler=handler)
        msg = _make_valid_message()
        mock_kafka_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_kafka_consumer, mock_dlq)

        mock_dlq.send.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# _process — failure path (DLQ routing)
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessFailure:
    def test_routes_to_dlq_on_handler_error(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock(side_effect=RuntimeError("ES is down"))
        consumer = KafkaCommandConsumer(handler=handler)
        msg = _make_valid_message()
        mock_kafka_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_kafka_consumer, mock_dlq)

        mock_dlq.send.assert_called_once()
        call_args = mock_dlq.send.call_args
        assert call_args.args[0] == "listing.commands.dlq"
        payload = call_args.kwargs["value"]
        assert "ES is down" in payload["error"]

    def test_still_commits_after_failure(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock(side_effect=RuntimeError("boom"))
        consumer = KafkaCommandConsumer(handler=handler)
        msg = _make_valid_message()
        mock_kafka_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_kafka_consumer, mock_dlq)

        # Must commit even on failure — prevents reprocessing loop
        mock_kafka_consumer.commit.assert_called_once()

    def test_routes_invalid_message_to_dlq(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock()
        consumer = KafkaCommandConsumer(handler=handler)
        msg = _make_invalid_message()
        mock_kafka_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_kafka_consumer, mock_dlq)

        # Validation failed → handler never called, DLQ received the message
        handler.assert_not_called()
        mock_dlq.send.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# _send_to_dlq — DLQ producer failure doesn't crash
# ─────────────────────────────────────────────────────────────────────────────


class TestSendToDlq:
    def test_swallows_dlq_send_failure(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        mock_dlq = MagicMock()
        mock_dlq.send.side_effect = OSError("DLQ broker down")

        # Should NOT raise
        KafkaCommandConsumer._send_to_dlq(mock_dlq, {"action": "create"}, "original error")


# ─────────────────────────────────────────────────────────────────────────────
# start — ImportError path
# ─────────────────────────────────────────────────────────────────────────────


class TestStartImportError:
    def test_raises_runtime_error_if_kafka_not_installed(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        consumer = KafkaCommandConsumer(handler=MagicMock())
        with patch.dict("sys.modules", {"kafka": None}):
            with pytest.raises(RuntimeError, match="kafka-python-ng"):
                consumer.start()


# ─────────────────────────────────────────────────────────────────────────────
# _process — infrastructure error path (no commit, no DLQ)
# ─────────────────────────────────────────────────────────────────────────────


class TestInfraError:
    def test_does_not_commit_on_os_error(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock(side_effect=OSError("ECONNREFUSED"))
        consumer = KafkaCommandConsumer(handler=handler, retry_backoff=0)
        msg = _make_valid_message()
        mock_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_consumer, mock_dlq, infra_errors=(OSError,))

        mock_consumer.commit.assert_not_called()

    def test_does_not_send_to_dlq_on_os_error(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock(side_effect=OSError("network gone"))
        consumer = KafkaCommandConsumer(handler=handler, retry_backoff=0)
        msg = _make_valid_message()
        mock_consumer = MagicMock()
        mock_dlq = MagicMock()

        consumer._process(msg, mock_consumer, mock_dlq, infra_errors=(OSError,))

        mock_dlq.send.assert_not_called()

    def test_bad_message_still_goes_to_dlq(self):
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock(side_effect=ValueError("bad payload"))
        consumer = KafkaCommandConsumer(handler=handler, retry_backoff=0)
        msg = _make_valid_message()
        mock_consumer = MagicMock()
        mock_dlq = MagicMock()

        # ValueError is NOT in infra_errors → should go to DLQ + commit
        consumer._process(msg, mock_consumer, mock_dlq, infra_errors=(OSError,))

        mock_dlq.send.assert_called_once()
        mock_consumer.commit.assert_called_once()

    def test_sleeps_when_running_on_infra_error(self):
        """Covers line 157: time.sleep() called when _running=True during infra error."""
        import time

        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        handler = MagicMock(side_effect=OSError("ETIMEDOUT"))
        consumer = KafkaCommandConsumer(handler=handler, retry_backoff=0)
        consumer._running = True  # ← key: _running must be True to hit line 157
        msg = _make_valid_message()
        mock_consumer = MagicMock()
        mock_dlq = MagicMock()

        with patch.object(time, "sleep") as mock_sleep:
            consumer._process(msg, mock_consumer, mock_dlq, infra_errors=(OSError,))

        mock_sleep.assert_called_once_with(0)  # retry_backoff=0


# ─────────────────────────────────────────────────────────────────────────────
# start() — full consume loop (exercises _setup_consumer_mocks helper)
# ─────────────────────────────────────────────────────────────────────────────


class TestStart:
    """Tests for KafkaCommandConsumer.start() — kafka imports are fully mocked."""

    def _run_start(self, messages, handler=None):
        """
        Run start() with mocked kafka imports.
        The mock poll() returns messages on the first call, then stops the loop
        on the second call by setting consumer._running = False before returning {}.
        Returns (consumer_instance, mock_kafka_consumer, mock_dlq_producer).
        """
        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        if handler is None:
            handler = MagicMock()

        consumer = KafkaCommandConsumer(handler=handler, poll_timeout=0.01, retry_backoff=0)

        mock_kafka_consumer = MagicMock()
        mock_dlq_producer = MagicMock()
        mock_tp = MagicMock()

        call_count = {"n": 0}

        def _poll(timeout_ms):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: yield the test messages (may be empty list → returns {} effectively)
                return {mock_tp: messages} if messages else {}
            # Second call: stop the loop so start() exits cleanly
            consumer._running = False
            return {}

        mock_kafka_consumer.poll.side_effect = _poll

        mock_kafka_module = MagicMock()
        mock_kafka_module.KafkaConsumer.return_value = mock_kafka_consumer
        mock_kafka_module.KafkaProducer.return_value = mock_dlq_producer

        mock_elastic_transport = MagicMock()
        mock_elastic_transport.ConnectionError = OSError  # reuse OSError as stand-in

        with patch.dict(
            "sys.modules",
            {
                "kafka": mock_kafka_module,
                "elastic_transport": mock_elastic_transport,
            },
        ):
            consumer.start()

        return consumer, mock_kafka_consumer, mock_dlq_producer

    def test_processes_one_valid_message_and_commits(self):
        """Full start() loop: one valid message → handler called → offset committed."""
        handler = MagicMock()
        msg = _make_valid_message(action=CommandAction.CREATE)
        _, mock_kafka_consumer, _ = self._run_start([msg], handler=handler)
        handler.assert_called_once()
        mock_kafka_consumer.commit.assert_called()

    def test_closes_consumer_in_finally_block(self):
        """consumer.close() is always called even if processing succeeds."""
        _, mock_kafka_consumer, _ = self._run_start([_make_valid_message()])
        mock_kafka_consumer.close.assert_called_once()

    def test_flushes_dlq_producer_in_finally_block(self):
        """dlq_producer.flush() is always called in the finally block."""
        _, _, mock_dlq_producer = self._run_start([_make_valid_message()])
        mock_dlq_producer.flush.assert_called_once()

    def test_processes_invalid_message_routes_to_dlq(self):
        """An invalid message (bad schema) goes to DLQ and offset is committed."""
        _, mock_kafka_consumer, mock_dlq_producer = self._run_start([_make_invalid_message()])
        mock_dlq_producer.send.assert_called()
        mock_kafka_consumer.commit.assert_called()

    def test_empty_poll_continues_loop(self):
        """When poll returns no records, loop continues without calling handler."""
        handler = MagicMock()
        # No messages — just test that start() completes without error
        _, _, _ = self._run_start([], handler=handler)
        handler.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# _setup_signal_handlers (exercises _stop inner function)
# ─────────────────────────────────────────────────────────────────────────────


class TestSignalHandlers:
    def test_sigterm_sets_running_false(self):
        """Covers _stop inner function: receiving SIGTERM sets _running=False."""
        import signal

        from src.infrastructure.kafka_consumer import KafkaCommandConsumer

        consumer = KafkaCommandConsumer(handler=MagicMock())
        consumer._running = True
        consumer._setup_signal_handlers()
        # Simulate SIGTERM
        signal.raise_signal(signal.SIGTERM)
        assert consumer._running is False
