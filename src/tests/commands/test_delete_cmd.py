"""Tests for `agora delete` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli import cli


def _mock_es_ok() -> MagicMock:
    m = MagicMock()
    m.ping.return_value = True
    return m


class TestDeleteCommand:
    def test_delete_existing_listing_succeeds(self):
        runner = CliRunner()
        doc = {"id": "abc-123", "title": "iPhone 14"}
        mock_svc = MagicMock()
        mock_svc.get.return_value = doc
        mock_svc.delete.return_value = True
        with (
            patch("src.commands.delete_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.delete_cmd.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, ["delete", "--id", "abc-123", "--yes"])
        assert result.exit_code == 0, result.output
        assert "abc-123" in result.output

    def test_delete_not_found_exits_1(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.get.return_value = None
        with (
            patch("src.commands.delete_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.delete_cmd.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, ["delete", "--id", "missing-id", "--yes"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_delete_service_returns_false_exits_3(self):
        runner = CliRunner()
        doc = {"id": "abc-123", "title": "Test"}
        mock_svc = MagicMock()
        mock_svc.get.return_value = doc
        mock_svc.delete.return_value = False
        with (
            patch("src.commands.delete_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.delete_cmd.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, ["delete", "--id", "abc-123", "--yes"])
        assert result.exit_code == 3

    def test_missing_id_option_fails(self):
        result = CliRunner().invoke(cli, ["delete", "--yes"])
        assert result.exit_code != 0

    def test_confirmation_prompt_abort_cancels(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.get.return_value = {"id": "x", "title": "T"}
        with (
            patch("src.commands.delete_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.delete_cmd.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, ["delete", "--id", "x"], input="n\n")
        assert result.exit_code != 0

    def test_es_unreachable_exits_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with patch("src.commands.delete_cmd.get_es_client", return_value=mock_es):
            result = CliRunner().invoke(cli, ["delete", "--id", "x", "--yes"])
        assert result.exit_code == 3


class TestDeleteKafkaMode:
    def test_queues_delete_to_kafka(self):
        runner = CliRunner()
        with (
            patch("src.commands.delete_cmd.settings") as mock_settings,
            patch("src.commands.delete_cmd.send_command", return_value=55) as mock_send,
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            result = runner.invoke(cli, ["delete", "--id", "abc-123", "--yes"])
        assert result.exit_code == 0, result.output
        mock_send.assert_called_once_with("delete", {"id": "abc-123"})

    def test_shows_offset_in_output(self):
        runner = CliRunner()
        with (
            patch("src.commands.delete_cmd.settings") as mock_settings,
            patch("src.commands.delete_cmd.send_command", return_value=321),
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            result = runner.invoke(cli, ["delete", "--id", "some-id", "--yes"])
        assert "321" in result.output

    def test_does_not_call_es_in_kafka_mode(self):
        runner = CliRunner()
        mock_es = MagicMock()
        with (
            patch("src.commands.delete_cmd.settings") as mock_settings,
            patch("src.commands.delete_cmd.send_command", return_value=1),
            patch("src.commands.delete_cmd.get_es_client", return_value=mock_es),
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            runner.invoke(cli, ["delete", "--id", "x", "--yes"])
        mock_es.ping.assert_not_called()
