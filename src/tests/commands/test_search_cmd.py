"""Tests for `agora search` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli import cli


def _mock_es_ok() -> MagicMock:
    m = MagicMock()
    m.ping.return_value = True
    return m


class TestSearchCommand:
    def test_search_displays_results(self):
        runner = CliRunner()
        fake_hit = {
            "id": "1",
            "type": "sell",
            "title": "iPhone 14",
            "category": "dien-tu",
            "price": 25_000_000,
            "price_currency": "VND",
            "city": "Hanoi",
            "_score": 0.9,
        }
        mock_svc = MagicMock()
        mock_svc.search.return_value = [fake_hit]
        with (
            patch("src.commands.search_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.search_cmd.make_search_service", return_value=mock_svc),
        ):
            result = runner.invoke(cli, ["search", "iphone 14"])
        assert result.exit_code == 0, result.output
        assert "iPhone 14" in result.output

    def test_no_results_prints_warning(self):
        mock_svc = MagicMock()
        mock_svc.search.return_value = []
        with (
            patch("src.commands.search_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.search_cmd.make_search_service", return_value=mock_svc),
        ):
            result = CliRunner().invoke(cli, ["search", "nothing here"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_all_type_converted_to_none(self):
        mock_svc = MagicMock()
        mock_svc.search.return_value = []
        with (
            patch("src.commands.search_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.search_cmd.make_search_service", return_value=mock_svc),
        ):
            CliRunner().invoke(cli, ["search", "test", "--type", "all"])
            call_kwargs = mock_svc.search.call_args
            assert call_kwargs.kwargs.get("listing_type") is None

    def test_sell_type_filter_passed_through(self):
        mock_svc = MagicMock()
        mock_svc.search.return_value = []
        with (
            patch("src.commands.search_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.search_cmd.make_search_service", return_value=mock_svc),
        ):
            CliRunner().invoke(cli, ["search", "iphone", "--type", "sell"])
            call_kwargs = mock_svc.search.call_args
            assert call_kwargs.kwargs.get("listing_type") == "sell"

    def test_filters_passed_to_service(self):
        mock_svc = MagicMock()
        mock_svc.search.return_value = []
        with (
            patch("src.commands.search_cmd.get_es_client", return_value=_mock_es_ok()),
            patch("src.commands.search_cmd.make_search_service", return_value=mock_svc),
        ):
            CliRunner().invoke(
                cli,
                [
                    "search",
                    "honda",
                    "--category",
                    "xe-may",
                    "--max-price",
                    "50000000",
                    "--lat",
                    "21.0",
                    "--lon",
                    "105.0",
                    "--radius",
                    "10km",
                    "--limit",
                    "5",
                ],
            )
            mock_svc.search.assert_called_once_with(
                "honda",
                listing_type=None,
                category="xe-may",
                max_price=50_000_000,
                lat=21.0,
                lon=105.0,
                radius="10km",
                limit=5,
            )

    def test_es_unreachable_exits_3(self):
        mock_es = MagicMock()
        mock_es.ping.return_value = False
        with patch("src.commands.search_cmd.get_es_client", return_value=mock_es):
            result = CliRunner().invoke(cli, ["search", "test"])
        assert result.exit_code == 3

    def test_invalid_category_fails(self):
        result = CliRunner().invoke(cli, ["search", "test", "--category", "not-a-category"])
        assert result.exit_code != 0
