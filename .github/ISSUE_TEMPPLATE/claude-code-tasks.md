---
name: Claude Code Task
about: A task for Claude Code to pick up
labels: claude-code
---

## Task
<!-- One sentence: what needs to be done -->

## Context
<!-- Which files are involved, what the current state is -->
Read ARCHITECTURE.md for project context.
Read PROJECT_STATUS.md for implementation state.

## Done When
<!-- How to verify this is complete -->

## Constraints
- Run tests before committing: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest`
- Don't modify MCP tool signatures (they're the API contract)
- Keep changes focused — one task per PR
