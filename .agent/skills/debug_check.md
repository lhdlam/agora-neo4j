---
name: debug_check
description: >
  Diagnose and fix failures from `make check` (ruff format, ruff lint, mypy, pytest).
  Use this skill whenever `make check` returns errors and you need a systematic approach
  to find and fix the root cause quickly.
---

# Skill: Debug a Failing `make check`

## When to use
- `make check` reports errors.
- A specific check (lint / typecheck / test) fails.
- Pre-commit hooks reject a commit.

## Step 1 — Identify WHICH check fails

```bash
make format check=1   # ruff format --check (formatting only)
make lint           # ruff lint (style + quality rules)
make mypy           # mypy strict
make test           # pytest + coverage
```

Run them individually to isolate the failure. Fix in this order:
1. `format check=1` → 2. `lint` → 3. `mypy` → 4. `test`

---

## Fixing: `make format check=1` (formatting)

The check is **read-only**. Fix with:

// turbo
```bash
make format    # ruff format src/ tests/
```

Then re-run `make format check=1` to confirm zero diff.

Common causes:
- Trailing whitespace
- Wrong quote style (single vs double) — ruff enforces **double quotes**
- Incorrect indentation

---

## Fixing: `make lint` (ruff)

### Common rule violations and fixes

| Rule | Message | Fix |
|------|---------|-----|
| `E501` | Line too long (>100 chars) | Break line or use implicit string concat |
| `I001` | Import order | Run `make lint fix=1` to auto-sort |
| `F401` | Unused import | Remove it |
| `ANN001` | Missing arg type annotation | Add `: TypeHint` |
| `ANN201` | Missing return type | Add `-> ReturnType` |
| `ANN202` | Missing return on private method | Add `-> ReturnType` |
| `T201` | `print()` in src/ | Replace with `logger.info(...)` or `Console().print()` |
| `TRY300` | `return` inside `try` block | Move return after `else:` block |
| `SIM108` | Ternary instead of if-else | Rewrite as `x = a if cond else b` |
| `B008` | Function call in default arg | Use `None` default + guard in body |
| `PTH123` | `open()` → `Path.open()` | Replace `open(path)` with `Path(path).open()` |
| `G004` | f-string in logging call | Use `logger.info("msg %s", var)` not `logger.info(f"msg {var}")` |
| `RET504` | Unnecessary assignment before return | Return directly |

Auto-fix safe rules:
// turbo
```bash
make lint fix=1   # ruff check --fix src/ tests/
```

> ⚠️ `make lint fix=1` does NOT fix `ANN` (annotation) errors — fix those manually.

### Annotations quick reference

```python
# Function with no return value:
def my_func(x: str) -> None: ...

# Optional parameter:
def my_func(x: str | None = None) -> str: ...

# List / dict:
def my_func(items: list[str]) -> dict[str, int]: ...

# Callable:
from collections.abc import Callable
def my_func(callback: Callable[[int, int], None]) -> None: ...

# Any (avoid — use specific type):
from typing import Any
def my_func(data: dict[str, Any]) -> Any: ...   # only if truly dynamic
```

---

## Fixing: `make mypy` (mypy strict)

### Common mypy errors

| Error | Fix |
|-------|-----|
| `error: Function is missing a return type annotation` | Add `-> ReturnType` |
| `error: Argument 1 to "X" has incompatible type` | Fix the type passed or widen the accepted type |
| `error: Item "None" of "X \| None" has no attribute "Y"` | Guard with `if x is not None: x.Y` |
| `error: "list[X]" has no attribute "Y"` | Wrong type inferred — annotate explicitly |
| `error: Module "X" has no attribute "Y"` | Import is wrong, or stub is missing |
| `error: Incompatible return value type` | Return type annotation doesn't match actual return |
| `error: Missing positional argument` | Function signature changed — update callers |

### Useful mypy patterns

```python
# Narrowing Optional:
if self._client is None:
    raise RuntimeError("Client not initialized")
# After this, mypy knows _client is not None

# Type assertion (use sparingly):
assert isinstance(result, str)  # mypy narrows type after this

# cast (last resort):
from typing import cast
value = cast(str, some_any_value)

# TYPE_CHECKING guard (for forward references / circular imports):
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.domain.models import Listing
```

### Checking specific file only

```bash
.venv/bin/mypy src/path/to/file.py
```

---

## Fixing: `make test` (pytest + coverage)

### Run only failing tests

```bash
# Re-run last failed:
.venv/bin/pytest --lf

# Run specific file:
.venv/bin/pytest src/tests/test_listing_service.py -v

# Run specific test:
.venv/bin/pytest src/tests/test_listing_service.py::TestListingService::test_post -v
```

### Common test failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImportError` | Wrong import path | Check `from src.X.Y import Z` |
| `AttributeError: Mock object has no attribute X` | Mock not configured | Add `mock.X = MagicMock()` |
| `AssertionError: assert 0 == 1` | Wrong return value | Check mock's `return_value` |
| `ValidationError` | Model field changed | Update test fixture to match new model |
| Coverage `< 80%` | New code not covered | Add tests for new paths |

### Coverage: find uncovered lines

```bash
make test   # shows term-missing report
```

Output example:
```
src/services/listing_service.py    89%   42-45, 67
```

Lines 42-45 and 67 are not covered. Open the file and write tests that exercise those branches.

### Coverage: exempt a line

Only use if the line is truly untestable (e.g., platform-specific, `__main__` guard):

```python
if __name__ == "__main__":  # pragma: no cover
    main()
```

---

## Full reset workflow (if everything is broken)

```bash
make clean          # remove all caches
make lint fix=1       # auto-fix lint issues
make format         # auto-format
make mypy           # check types manually
make test           # run tests without coverage (faster feedback)
make check          # final full check
```

---

## Pre-commit hook failures

Pre-commit runs `ruff lint → ruff format → mypy`. To bypass temporarily:

```bash
git commit --no-verify -m "WIP: ..."
```

> ⚠️ Never merge with `--no-verify` — fix the issues before final commit.

To re-run hooks on all files manually:

```bash
make pre-commit
```
