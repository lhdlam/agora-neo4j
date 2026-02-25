"""Tests for `agora post sell` and `agora post buy` CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli import cli

_SELL_REQUIRED = [
    "post",
    "sell",
    "--title",
    "iPhone 14 Pro",
    "--category",
    "dien-tu",
    "--price",
    "25000000",
    "--contact-phone",
    "0901234567",
]
_BUY_REQUIRED = [
    "post",
    "buy",
    "--title",
    "Looking for iPhone 14",
    "--category",
    "dien-tu",
    "--contact-phone",
    "0912345678",
]


def _mock_es_ok() -> MagicMock:
    m = MagicMock()
    m.ping.return_value = True
    return m


class TestPostSell:
    def test_success_prints_doc_id(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.post.return_value = "new-doc-id-123"
        with (
            patch("src.commands.post.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.post.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, _SELL_REQUIRED)
        assert result.exit_code == 0, result.output
        assert "new-doc-id-123" in result.output

    def test_missing_title_fails(self):
        result = CliRunner().invoke(
            cli, ["post", "sell", "--category", "dien-tu", "--price", "1000"]
        )
        assert result.exit_code != 0

    def test_missing_price_fails(self):
        result = CliRunner().invoke(cli, ["post", "sell", "--title", "X", "--category", "dien-tu"])
        assert result.exit_code != 0

    def test_invalid_category_fails(self):
        result = CliRunner().invoke(
            cli, ["post", "sell", "--title", "X", "--price", "1000", "--category", "invalid"]
        )
        assert result.exit_code != 0

    def test_with_geo_location(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.post.return_value = "geo-doc-id"
        with (
            patch("src.commands.post.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.post.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, _SELL_REQUIRED + ["--lat", "21.0285", "--lon", "105.8542"])
        assert result.exit_code == 0, result.output

    def test_service_error_exits_with_1(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.post.side_effect = RuntimeError("ES is down")
        with (
            patch("src.commands.post.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.post.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, _SELL_REQUIRED)
        assert result.exit_code == 1

    def test_es_unreachable_exits_with_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with patch("src.commands.post.get_es_client", return_value=mock_es):
            result = CliRunner().invoke(cli, _SELL_REQUIRED)
        assert result.exit_code == 3


class TestPostBuy:
    def test_success_prints_doc_id(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.post.return_value = "buy-doc-789"
        with (
            patch("src.commands.post.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.post.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, _BUY_REQUIRED)
        assert result.exit_code == 0, result.output
        assert "buy-doc-789" in result.output

    def test_missing_title_fails(self):
        result = CliRunner().invoke(cli, ["post", "buy", "--category", "dien-tu"])
        assert result.exit_code != 0

    def test_with_budget(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.post.return_value = "b-id"
        with (
            patch("src.commands.post.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.post.make_listing_service", return_value=mock_svc),
        ):
            result = runner.invoke(
                cli,
                _BUY_REQUIRED + ["--budget-max", "27000000", "--urgency", "asap"],
            )
        assert result.exit_code == 0, result.output

    def test_invalid_urgency_fails(self):
        result = CliRunner().invoke(cli, _BUY_REQUIRED + ["--urgency", "super-urgent"])
        assert result.exit_code != 0


class TestPostSellKafkaMode:
    def test_queues_to_kafka_instead_of_es(self):
        runner = CliRunner()
        with (
            patch("src.commands.post.settings") as mock_settings,
            patch("src.commands.post.send_command", return_value=42) as mock_send,
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            result = runner.invoke(cli, _SELL_REQUIRED)
        assert result.exit_code == 0, result.output
        mock_send.assert_called_once_with("create", mock_send.call_args.args[1])

    def test_shows_offset_in_output(self):
        runner = CliRunner()
        with (
            patch("src.commands.post.settings") as mock_settings,
            patch("src.commands.post.send_command", return_value=999),
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            result = runner.invoke(cli, _SELL_REQUIRED)
        assert "999" in result.output

    def test_does_not_call_es_in_kafka_mode(self):
        runner = CliRunner()
        mock_es = MagicMock()
        with (
            patch("src.commands.post.settings") as mock_settings,
            patch("src.commands.post.send_command", return_value=1),
            patch("src.commands.post.get_es_client", return_value=mock_es),
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            runner.invoke(cli, _SELL_REQUIRED)
        mock_es.ping.assert_not_called()


class TestPostBuyKafkaMode:
    def test_queues_to_kafka_instead_of_es(self):
        runner = CliRunner()
        with (
            patch("src.commands.post.settings") as mock_settings,
            patch("src.commands.post.send_command", return_value=7) as mock_send,
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            result = runner.invoke(cli, _BUY_REQUIRED)
        assert result.exit_code == 0, result.output
        mock_send.assert_called_once()

    def test_shows_offset_in_output(self):
        runner = CliRunner()
        with (
            patch("src.commands.post.settings") as mock_settings,
            patch("src.commands.post.send_command", return_value=777),
        ):
            mock_settings.KAFKA_WRITE_MODE = True
            result = runner.invoke(cli, _BUY_REQUIRED)
        assert "777" in result.output


# ─────────────────────────────────────────────────────────────────────────────
# output.py helpers — extract_contact edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractContact:
    """Unit tests for output.extract_contact — covers list and empty-list formats."""

    def test_contact_as_non_empty_list_returns_phone(self):
        from src.commands.output import extract_contact

        hit = {"contact": [{"phone": "0901234567"}]}
        assert extract_contact(hit) == "0901234567"

    def test_contact_as_empty_list_returns_dash(self):
        from src.commands.output import extract_contact

        hit = {"contact": []}
        assert extract_contact(hit) == "—"

    def test_contact_as_dict_returns_phone(self):
        from src.commands.output import extract_contact

        hit = {"contact": {"phone": "0912345678"}}
        assert extract_contact(hit) == "0912345678"

    def test_contact_missing_returns_dash(self):
        from src.commands.output import extract_contact

        hit = {}
        assert extract_contact(hit) == "—"

    def test_contact_list_with_email_only(self):
        from src.commands.output import extract_contact

        hit = {"contact": [{"email": "seller@example.com"}]}
        assert extract_contact(hit) == "seller@example.com"
