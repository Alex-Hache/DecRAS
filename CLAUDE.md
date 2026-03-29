# DecRAS — Claude Code Context

## What is this project?
Distributed robotics architecture: LLM (planner) + MCP server (executor) + perception pipeline.
See ARCHITECTURE.md for design decisions and PROJECT_STATUS.md for implementation state.

## How to run tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest

## Key rules
- MCP tool signatures in server.py are the API contract — don't change them without discussion
- SIMULATE flag in config.py switches between real hardware and PyBullet
- All robot interaction goes through robot/lerobot.py, never direct serial access
- FK/IK goes through robot/kinematics.py (PyBullet DIRECT headless client)

## Current focus
Phase 6 — Imitation Learning Pipeline. See BACKLOG.md for specific tasks.

## File structure
See PROJECT_STATUS.md "Key Files" section for the full map.

## MANDATORY: Doc updates on every task

Every PR / commit that completes a task MUST also update the project docs in the same commit:

1. **BACKLOG.md** — Check off (`- [x]`) the completed task(s)
2. **PROJECT_STATUS.md** — If the task adds a new capability, file, or changes behavior:
   - Add it under the appropriate section (Working, Key Files, Completed, etc.)
   - If a new file was created, add it to the Key Files tree
   - If a phase milestone was reached, note it under Completed
3. **ARCHITECTURE.md** — Only update if a design decision was made or changed (rare)

### How to do this
After implementing the task and before committing:
- Re-read BACKLOG.md, find the task you just completed, check the box
- Re-read PROJECT_STATUS.md, add any new capabilities/files
- Include these doc changes in the same commit as the code changes

### Example commit message format
```
feat: add demo store schema (BACKLOG 6.2.1)

- Created decras/imitation/retrieval.py with DemoRecord schema
- Updated BACKLOG.md: checked off task 6.2.1
- Updated PROJECT_STATUS.md: added retrieval.py to Key Files
```

This keeps the project docs always in sync with the code. No separate "update docs" step needed.
