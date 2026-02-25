---
description: Systematically diagnose and fix make check failures
---

// turbo-all

## Fix order (always follow this sequence)
format-check → lint → mypy → test

## Steps

1. Read skill `.agent/skills/debug_check.md`
2. Run each check individually to isolate failing layer — read ONLY the files mentioned in error output
3. Fix format issues:
   // turbo
   ```bash
   make format
   ```
4. Fix lint issues (safe auto-fix only):
   // turbo
   ```bash
   make lint fix=1
   ```
5. Fix remaining lint + mypy issues manually — read ONLY failing files
6. Fix test failures — read ONLY failing test files and their targets
