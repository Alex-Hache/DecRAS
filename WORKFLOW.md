# DecRAS — Claude Code Workflow (Phone-First)

> **Goal**: Pick up a task from your phone in 2 minutes, have Claude Code do the work,
> review the PR when ready.

---

## Setup (One-Time, ~15 min)

### 1. Connect Claude Code to the DecRAS repo

You already have Claude Code authorized on GitHub (for another repo). To point it at DecRAS:

```bash
# In a Claude Code session (terminal or web):
claude code --repo Alex-Hache/DecRAS
```

Or if using the web interface, just open a new Claude Code session and tell it:
"Work on the repo github.com/Alex-Hache/DecRAS"

### 2. Create Issue Templates

Add this file to your repo so GitHub Issues have the right structure for Claude Code:

**File: `.github/ISSUE_TEMPLATE/claude-code-task.md`**

```markdown
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
```

### 3. Add a CLAUDE.md to the repo root

Claude Code reads `CLAUDE.md` automatically for project context. Create this file:

**File: `CLAUDE.md`**

```markdown
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
```

---

## Daily Workflow (From Phone)

### Option A: GitHub Issue → Claude Code (Recommended)

1. **Open GitHub mobile app** (or browser)
2. **Create a new Issue** on `Alex-Hache/DecRAS` using the "Claude Code Task" template
3. **Fill in** the task from BACKLOG.md (copy the task title + done-when criteria)
4. **Open Claude Code** (claude.ai mobile or Claude app)
5. **Tell it**: "Work on Alex-Hache/DecRAS, pick up issue #N"
6. Claude Code reads `CLAUDE.md`, understands the project, works on the issue
7. **Review the diff** when Claude Code is done — approve or request changes

### Option B: Direct Claude Code Session (Quick Tasks)

1. **Open Claude Code** on your phone
2. **Say**: "Work on Alex-Hache/DecRAS. [paste task from BACKLOG.md]"
3. Claude Code does the work
4. Review and commit

### Option C: Discuss Here, Execute There

1. **Chat with me here** (claude.ai) about design decisions, architecture questions
2. Once we agree on an approach, I'll help you write the GitHub Issue
3. You create the Issue on your phone → Claude Code picks it up

---

## Tips for Good Claude Code Sessions

### Give it enough context
Bad: "Add retrieval to the project"
Good: "In Alex-Hache/DecRAS, create `scripts/store_demo.py` that reads segmenter JSON
output from `scripts/segment_trajectory.py` and writes it to a demo store as
`demos/{dataset}_{episode}.json` with schema: `{task, primitives: [{tool, args, timestamp}], metadata}`"

### Reference the docs
Claude Code reads `CLAUDE.md` automatically, but you can also tell it:
"Read BACKLOG.md task 6.2.1 and implement it"

### Keep sessions focused
One task per session. If Claude Code suggests "I could also refactor X" — say no, file
a separate issue. This keeps PRs reviewable and progress trackable.

### Test before committing
Always ask Claude Code to run the test suite before committing:
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest`

---

## Motivation System: The Streak

The BACKLOG.md tasks are designed so that each one is:
- **Completable in one session** (15-30 min)
- **Independently satisfying** (you see a result: a file, a plot, a passing test)
- **Visible in git history** (each task = one commit)

The game: maintain a streak. One task per day, even if it's the smallest one.
Your git commit history becomes the scoreboard. No task is too small — "run the
visualizer and screenshot the output" counts.

When you're stuck or unmotivated: pick the shortest task. Action creates motivation,
not the other way around.
