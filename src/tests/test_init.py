"""Tests for src/__init__.py — covers _detect_mode() logic."""

import os
from unittest.mock import patch


class TestDetectMode:
    def test_returns_cli_when_mode_env_is_cli(self):
        from src import _detect_mode

        with patch.dict(os.environ, {"MODE": "cli"}):
            assert _detect_mode() == "cli"

    def test_returns_cli_when_mode_env_is_empty(self):
        from src import _detect_mode

        with patch.dict(os.environ, {}, clear=True):
            # Remove MODE if it exists, then test
            os.environ.pop("MODE", None)
            with patch("sys.argv", ["/usr/bin/python"]):
                assert _detect_mode() == "cli"

    def test_runner_heuristic_path_with_no_argv(self):
        """sys.argv is empty → runner='' → falls through to default cli."""
        from src import _detect_mode

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", []),
        ):
            os.environ.pop("MODE", None)
            assert _detect_mode() == "cli"
