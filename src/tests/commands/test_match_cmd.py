"""Tests for `agora match` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli import cli
from src.services.match_service import MatchResult


def _mock_es_ok() -> MagicMock:
    m = MagicMock()
    m.ping.return_value = True
    return m


def _fake_result(score: float = 0.85) -> MatchResult:
    return MatchResult(
        score=score,
        listing={
            "id": "sell-1",
            "title": "iPhone 14 Pro",
            "price": 25_000_000,
            "price_currency": "VND",
            "city": "Hanoi",
            "contact": {"phone": "0901234567"},
            "_score": score,
        },
    )


class TestMatchCommand:
    def test_query_mode_success(self):
        runner = CliRunner()
        mock_match = MagicMock()
        mock_match.match.return_value = [_fake_result()]
        with (
            patch("src.commands.match_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.match_cmd.make_match_service", return_value=mock_match),
        ):
            result = runner.invoke(cli, ["match", "--query", "iphone 14"])
        assert result.exit_code == 0, result.output
        assert "iPhone 14 Pro" in result.output

    def test_buy_id_mode_uses_listing_service(self):
        runner = CliRunner()
        buy_doc = {
            "id": "buy-123",
            "title": "Want iphone",
            "type": "buy",
            "category": "dien-tu",
            "embedding": [0.1] * 768,
        }
        mock_listing = MagicMock()
        mock_listing.get.return_value = buy_doc
        mock_match = MagicMock()
        mock_match.match.return_value = [_fake_result()]
        with (
            patch("src.commands.match_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.match_cmd.make_listing_service", return_value=mock_listing),
            patch("src.commands.match_cmd.make_match_service", return_value=mock_match),
        ):
            result = runner.invoke(cli, ["match", "--buy-id", "buy-123"])
        assert result.exit_code == 0, result.output
        mock_listing.get.assert_called_once_with("buy-123")

    def test_buy_id_not_found_exits_1(self):
        runner = CliRunner()
        mock_listing = MagicMock()
        mock_listing.get.return_value = None
        with (
            patch("src.commands.match_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.match_cmd.make_listing_service", return_value=mock_listing),
        ):
            result = runner.invoke(cli, ["match", "--buy-id", "missing-id"])
        assert result.exit_code == 1

    def test_no_query_and_no_buy_id_exits_1(self):
        with patch("src.commands.match_cmd.get_es_client", return_value=_mock_es_ok()):
            result = CliRunner().invoke(cli, ["match"])
        assert result.exit_code == 1

    def test_no_results_prints_warning(self):
        mock_match = MagicMock()
        mock_match.match.return_value = []
        with (
            patch("src.commands.match_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.match_cmd.make_match_service", return_value=mock_match),
        ):
            result = CliRunner().invoke(cli, ["match", "--query", "something rare"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_es_unreachable_exits_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with patch("src.commands.match_cmd.get_es_client", return_value=mock_es):
            result = CliRunner().invoke(cli, ["match", "--query", "test"])
        assert result.exit_code == 3

    def test_budget_and_category_passed_to_service(self):
        mock_match = MagicMock()
        mock_match.match.return_value = []
        with (
            patch("src.commands.match_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.match_cmd.make_match_service", return_value=mock_match),
        ):
            CliRunner().invoke(
                cli,
                [
                    "match",
                    "--query",
                    "iphone",
                    "--budget",
                    "30000000",
                    "--category",
                    "dien-tu",
                    "--top",
                    "5",
                ],
            )
            call_kwargs = mock_match.match.call_args.kwargs
            assert call_kwargs["budget"] == 30_000_000
            assert call_kwargs["category"] == "dien-tu"
            assert call_kwargs["top"] == 5
