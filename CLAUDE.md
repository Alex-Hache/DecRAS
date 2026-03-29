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
