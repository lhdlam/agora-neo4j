"""Tests for src/error_handling — dispatch() and handler registration."""

import json

import pytest

from src.error_handling import (
    _REGISTRY,
    BaseHandler,
    ErrorResult,
    NameHandler,
    PredicateHandler,
    TypeHandler,
    dispatch,
    register_handler,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


class _FakeNotFoundError(Exception):
    """Simulates an ES-style NotFoundError without importing elasticsearch."""


class _FakeBadRequestError(Exception):
    pass


class _FakeAuthenticationException(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# ErrorResult
# ─────────────────────────────────────────────────────────────────────────────


class TestErrorResult:
    def test_defaults_exit_code_1(self):
        r = ErrorResult(title="Oops", body="something broke")
        assert r.exit_code == 1

    def test_is_frozen(self):
        import dataclasses

        r = ErrorResult(title="T", body="B", exit_code=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.exit_code = 5  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# TypeHandler
# ─────────────────────────────────────────────────────────────────────────────


class TestTypeHandler:
    def test_matches_exact_type(self):
        h = TypeHandler(ValueError, "V", lambda e: str(e))
        assert h.matches(ValueError("bad")) is True

    def test_matches_subclass(self):
        h = TypeHandler(Exception, "E", lambda e: str(e))
        assert h.matches(RuntimeError("rt")) is True

    def test_no_match_different_type(self):
        h = TypeHandler(ValueError, "V", lambda e: str(e))
        assert h.matches(TypeError("t")) is False

    def test_matches_tuple_of_types(self):
        h = TypeHandler((ValueError, TypeError), "VT", lambda e: str(e))
        assert h.matches(TypeError("t")) is True
        assert h.matches(ValueError("v")) is True
        assert h.matches(RuntimeError("r")) is False

    def test_build_returns_correct_result(self):
        h = TypeHandler(RuntimeError, "RT", lambda e: f"msg={e}", exit_code=5)
        result = h.build(RuntimeError("boom"))
        assert result.title == "RT"
        assert result.body == "msg=boom"
        assert result.exit_code == 5


# ─────────────────────────────────────────────────────────────────────────────
# PredicateHandler
# ─────────────────────────────────────────────────────────────────────────────


class TestPredicateHandler:
    def test_matches_when_predicate_true(self):
        h = PredicateHandler(lambda exc: "special" in str(exc), "S", lambda e: str(e))
        assert h.matches(RuntimeError("special case")) is True

    def test_no_match_when_predicate_false(self):
        h = PredicateHandler(lambda exc: False, "S", lambda e: str(e))
        assert h.matches(Exception("anything")) is False

    def test_predicate_exception_returns_false(self):
        # A buggy predicate must never crash the dispatcher
        h = PredicateHandler(lambda exc: 1 / 0, "S", lambda e: str(e))  # type: ignore[arg-type]
        assert h.matches(Exception("x")) is False

    def test_build_uses_exit_code(self):
        h = PredicateHandler(lambda e: True, "Title", lambda e: "body", exit_code=3)
        assert h.build(Exception()).exit_code == 3


# ─────────────────────────────────────────────────────────────────────────────
# NameHandler
# ─────────────────────────────────────────────────────────────────────────────


class TestNameHandler:
    def test_matches_single_fragment(self):
        h = NameHandler("NotFoundError", "NF", lambda e: str(e))
        assert h.matches(_FakeNotFoundError()) is True

    def test_matches_any_fragment_in_tuple(self):
        h = NameHandler(("RequestError", "BadRequestError"), "BR", lambda e: str(e))
        assert h.matches(_FakeBadRequestError()) is True

    def test_no_match_unrelated_name(self):
        h = NameHandler("NotFoundError", "NF", lambda e: str(e))
        assert h.matches(ValueError("v")) is False


# ─────────────────────────────────────────────────────────────────────────────
# dispatch() — built-in handlers
# ─────────────────────────────────────────────────────────────────────────────


class TestDispatchBuiltins:
    def test_file_not_found(self):
        exc = FileNotFoundError(2, "No such file", "/tmp/missing.json")
        result = dispatch(exc)
        assert result.title == "File Not Found"
        assert result.exit_code == 1

    def test_permission_error(self):
        exc = PermissionError(13, "Permission denied", "/etc/shadow")
        result = dispatch(exc)
        assert result.title == "Permission Denied"
        assert result.exit_code == 1

    def test_json_decode_error(self):
        exc = json.JSONDecodeError("Expecting value", "bad{json", 4)
        result = dispatch(exc)
        assert result.title == "Invalid JSON"
        assert result.exit_code == 1

    def test_runtime_error_generic(self):
        result = dispatch(RuntimeError("something broke"))
        assert result.title == "Error"
        assert result.exit_code == 1

    def test_runtime_error_fastembed(self):
        exc = RuntimeError("fastembed is not installed. Run: pip install fastembed")
        result = dispatch(exc)
        assert result.title == "Embedding Model Error"
        assert "pip install fastembed" in result.body

    def test_value_error_exit_code_2(self):
        result = dispatch(ValueError("bad input"))
        assert result.title == "Invalid Input"
        assert result.exit_code == 2

    def test_not_found_error_by_name(self):
        result = dispatch(_FakeNotFoundError("id=abc"))
        assert result.title == "Not Found"
        assert result.exit_code == 3

    def test_bad_request_error_by_name(self):
        result = dispatch(_FakeBadRequestError("malformed"))
        assert result.title == "Bad Request"
        assert result.exit_code == 1

    def test_auth_exception_by_name(self):
        result = dispatch(_FakeAuthenticationException("401"))
        assert result.title == "Auth Error"
        assert result.exit_code == 1

    def test_catch_all_unknown_exception(self):
        class _Weird(Exception):
            pass

        result = dispatch(_Weird("something totally unknown"))
        assert result.title == "Unexpected Error"
        assert "_Weird" in result.body
        assert result.exit_code == 1

    def test_pydantic_validation_error(self):
        from pydantic import BaseModel, ValidationError

        class _M(BaseModel):
            x: int

        with pytest.raises(ValidationError) as exc_info:
            _M(x="not-an-int")  # type: ignore[arg-type]

        result = dispatch(exc_info.value)
        assert result.title == "Validation Error"
        assert result.exit_code == 2


# ─────────────────────────────────────────────────────────────────────────────
# dispatch() — custom handler registration (first-match-wins)
# ─────────────────────────────────────────────────────────────────────────────


class TestDispatchCustomHandler:
    def test_custom_handler_registered_at_end_still_matches(self):
        """Handler appended at the end is picked up if builtins don't match first."""

        class _OddError(Exception):
            pass

        register_handler(TypeHandler(_OddError, "Odd Error", lambda e: f"odd: {e}", exit_code=42))
        result = dispatch(_OddError("special"))
        assert result.title == "Odd Error"
        assert result.exit_code == 42

    def test_higher_priority_custom_handler_wins(self):
        """A handler inserted at the front beats built-ins."""

        class _SpecialRuntime(RuntimeError):
            pass

        # Insert at position 0 to win over the generic RuntimeError handler
        _REGISTRY.insert(
            0,
            TypeHandler(
                _SpecialRuntime,
                "Special Runtime",
                lambda e: str(e),
                exit_code=99,
            ),
        )
        try:
            result = dispatch(_SpecialRuntime("priority"))
            assert result.title == "Special Runtime"
            assert result.exit_code == 99
        finally:
            # Clean up so we don't affect other tests
            _REGISTRY.pop(0)


# ─────────────────────────────────────────────────────────────────────────────
# dispatch() — handler.build() crashing gracefully
# ─────────────────────────────────────────────────────────────────────────────


class TestDispatchBuildCrash:
    def test_broken_build_falls_through_to_catchall(self):
        class _BrokenHandler(BaseHandler):
            def matches(self, exc):
                return True  # always claim to match

            def build(self, exc):
                raise OSError("handler broken")

        # Insert a broken handler at the front
        _REGISTRY.insert(0, _BrokenHandler())
        try:

            class _UniqueError(Exception):
                pass

            result = dispatch(_UniqueError("test"))
            # Should fall through to catch-all
            assert result.title == "Unexpected Error"
        finally:
            _REGISTRY.pop(0)
