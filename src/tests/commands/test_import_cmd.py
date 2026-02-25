"""Tests for `agora import` CLI command."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli import cli


def _mock_es_ok() -> MagicMock:
    m = MagicMock()
    m.ping.return_value = True
    return m


def _write_json(records: list, tmp_dir: str) -> str:
    path = Path(tmp_dir) / "listings.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return str(path)


_VALID_RECORD = {"type": "sell", "title": "Test iPhone", "category": "dien-tu", "price": 10_000_000}


class TestImportCommand:
    def test_json_import_success(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json([_VALID_RECORD], tmp)
            mock_svc = MagicMock()
            mock_svc.bulk_import.return_value = (1, 0)
            with (
                patch("src.commands.import_cmd.get_es_client", return_value=_mock_es_ok()),
                patch("src.commands.import_cmd.make_listing_service", return_value=mock_svc),
            ):
                result = runner.invoke(cli, ["import", "--file", path])
        assert result.exit_code == 0, result.output
        assert "1" in result.output

    def test_json_single_object_accepted(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "single.json"
            path.write_text(json.dumps(_VALID_RECORD), encoding="utf-8")
            mock_svc = MagicMock()
            mock_svc.bulk_import.return_value = (1, 0)
            with (
                patch("src.commands.import_cmd.get_es_client", return_value=_mock_es_ok()),
                patch("src.commands.import_cmd.make_listing_service", return_value=mock_svc),
            ):
                result = runner.invoke(cli, ["import", "--file", str(path)])
        assert result.exit_code == 0, result.output

    def test_validation_errors_reported(self):
        runner = CliRunner()
        records = [_VALID_RECORD, {"type": "sell", "title": "Missing category"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(records, tmp)
            mock_svc = MagicMock()
            mock_svc.bulk_import.return_value = (1, 0)
            with (
                patch("src.commands.import_cmd.get_es_client", return_value=_mock_es_ok()),
                patch("src.commands.import_cmd.make_listing_service", return_value=mock_svc),
            ):
                result = runner.invoke(cli, ["import", "--file", path])
        assert result.exit_code == 0, result.output
        assert "validation" in result.output.lower() or "Warning" in result.output

    def test_all_records_invalid_exits_1(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json([{"invalid": "record"}], tmp)
            with patch("src.commands.import_cmd.get_es_client", return_value=_mock_es_ok()):
                result = runner.invoke(cli, ["import", "--file", path])
        assert result.exit_code == 1

    def test_file_not_found_exits_nonzero(self):
        result = CliRunner().invoke(cli, ["import", "--file", "/nonexistent/file.json"])
        assert result.exit_code != 0

    def test_es_unreachable_exits_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json([_VALID_RECORD], tmp)
            with patch("src.commands.import_cmd.get_es_client", return_value=mock_es):
                result = CliRunner().invoke(cli, ["import", "--file", path])
        assert result.exit_code == 3


class TestImportCsvFormat:
    """Covers lines 53–54: CSV parsing path."""

    def test_csv_import_success(self):
        import csv

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "listings.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["type", "title", "category", "price"])
                writer.writeheader()
                writer.writerow(
                    {
                        "type": "sell",
                        "title": "CSV iPhone",
                        "category": "dien-tu",
                        "price": "5000000",
                    }
                )

            mock_svc = MagicMock()
            mock_svc.bulk_import.return_value = (1, 0)
            with (
                patch("src.commands.import_cmd.get_es_client", return_value=_mock_es_ok()),
                patch("src.commands.import_cmd.make_listing_service", return_value=mock_svc),
            ):
                result = runner.invoke(cli, ["import", "--file", str(csv_path), "--format", "csv"])
        assert result.exit_code == 0, result.output


class TestImportKafkaMode:
    """Covers lines 71–102: KAFKA_WRITE_MODE=True path → _kafka_import()."""

    def test_kafka_mode_queues_commands(self):
        """Line 72: KAFKA_WRITE_MODE branch calls _kafka_import."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json([_VALID_RECORD], tmp)
            with (
                patch("src.commands.import_cmd.settings") as mock_settings,
                patch("src.commands.import_cmd.send_command", return_value=0) as mock_send,
            ):
                mock_settings.KAFKA_WRITE_MODE = True
                result = runner.invoke(cli, ["import", "--file", path])
        assert result.exit_code == 0, result.output
        mock_send.assert_called_once()

    def test_kafka_mode_partial_error_still_reports(self):
        """Lines 96–100: Some records fail during Kafka send → error count incremented."""
        runner = CliRunner()
        records = [_VALID_RECORD, _VALID_RECORD]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(records, tmp)
            call_count = {"n": 0}

            def _flaky_send(action, payload):
                call_count["n"] += 1
                if call_count["n"] == 2:
                    raise RuntimeError("Kafka broker unavailable")
                return 0

            with (
                patch("src.commands.import_cmd.settings") as mock_settings,
                patch("src.commands.import_cmd.send_command", side_effect=_flaky_send),
            ):
                mock_settings.KAFKA_WRITE_MODE = True
                result = runner.invoke(cli, ["import", "--file", path])
        assert result.exit_code == 0, result.output
        # Summary table should mention the error
        assert "1" in result.output  # at least 1 indexed OK


class TestImportProgressCallback:
    """Covers line 129: _on_progress nested function inside _sync_import."""

    def test_progress_callback_is_called_during_bulk_import(self):
        """Ensures the _on_progress lambda updates the progress bar (line 129)."""
        runner = CliRunner()
        records = [_VALID_RECORD, _VALID_RECORD]

        with tempfile.TemporaryDirectory() as tmp:
            path = _write_json(records, tmp)

            captured_callbacks = []

            def _mock_bulk_import(listings, on_progress=None):
                # Simulate progress updates — this exercises line 129 (_on_progress)
                if on_progress:
                    for i, _ in enumerate(listings, 1):
                        on_progress(i, len(listings))
                        captured_callbacks.append(i)
                return len(listings), 0

            mock_svc = MagicMock()
            mock_svc.bulk_import.side_effect = _mock_bulk_import

            with (
                patch("src.commands.import_cmd.get_es_client", return_value=_mock_es_ok()),
                patch("src.commands.import_cmd.make_listing_service", return_value=mock_svc),
            ):
                result = runner.invoke(cli, ["import", "--file", path])

        assert result.exit_code == 0, result.output
        assert len(captured_callbacks) == 2  # callback called once per record
