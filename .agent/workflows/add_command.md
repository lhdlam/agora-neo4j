---
description: Add a new agora CLI subcommand end-to-end
---

// turbo-all

## Context (DO NOT re-read source to confirm)
- All commands registered via `register()` in `src/commands/__init__.py`
- All factories live in `src/services/factories.py` — pattern: `make_<svc>_service()`
- Patch path in tests: `src.commands.<module>.make_<svc>_service` and `src.commands.<module>.get_es_client`
- SystemExit codes: 1 = user error, 3 = infra unavailable (ES unreachable)

## Steps

1. Read skill `.agent/skills/add_cli_command.md`
2. Create `src/commands/<cmd>.py` — use template from skill exactly
3. If new service needed: add `make_<svc>_service()` to `src/services/factories.py`
4. Register in `src/commands/__init__.py` → `register()` function + `__all__`
5. Add Rich output helper to `src/commands/output.py` if reusable rendering needed
6. Create `src/tests/commands/test_<cmd>.py` — patch factory + test ES unreachable exits 3
