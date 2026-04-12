# DecRAS — Decision Log

> Append-only log of architectural decisions made in claude.ai conversations.
> Claude Code reads this file for context. Do not edit manually except to append.

---

## 2026-03-29 — IK Bypass: Joint-Space Lookup Table

**Decision**: Replace placo/PyBullet IK with data-driven joint-space lookup table built from teleoperation recordings.

**Reason**: placo IK uses DH parameters that don't match the actual 3D-printed SO-101 arm geometry. The arm moves to wrong positions. This is fundamental — no amount of tuning fixes incorrect DH parameters on a 3D-printed arm.

**Approach**: Teleoperate arm to ~75 positions across workspace, record (Cartesian_position, joint_angles) pairs, use KDTree + inverse-distance interpolation for arbitrary targets. All trajectory generation in joint space via minimum-jerk profiles.

**Impact**:
- New Phase 5.5 inserted before Phase 6 (BACKLOG.md)
- Phase 6 (imitation learning) blocked until motion control is reliable
- New Decision #6 added to ARCHITECTURE.md
- Files to build: calibration/record_grid.py, control/joint_lookup.py, control/trajectory.py, control/executor.py

---

## 2026-03-29 — Project Workflow Established

**Decision**: Three-doc system (ARCHITECTURE.md + BACKLOG.md + DECISIONS.md) with automated sync.

**Reason**: Architectural decisions made in claude.ai conversations were not flowing into the repo. Claude Code had no visibility into strategic direction discussed here.

**Workflow**:
- End of each claude.ai conversation → Claude produces a sync block → user appends to DECISIONS.md
- Claude Code reads DECISIONS.md before every task (per CLAUDE.md rules)
- Every PR updates BACKLOG.md (check off task) + PROJECT_STATUS.md (new capabilities)
- Daily pulse via scripts/daily_pulse.py (GitHub Actions when billing unlocked)

---

## 2026-04-08 — FK Bug Found: `.pos` Suffix Mismatch in kinematics.py

**Decision**: Fix `joints_to_cartesian()` and `cartesian_to_joints()` to accept both `"shoulder_pan"` and `"shoulder_pan.pos"` key formats.

**Reason**: LeRobot's `robot.get_observation()` returns keys with `.pos` suffix (e.g. `"shoulder_pan.pos": -14.4`). The FK/IK functions in `kinematics.py` looked up bare names (`"shoulder_pan"`), causing `.get("shoulder_pan", 0.0)` to always return the default `0.0`. **Every FK call silently computed the zero-config position regardless of input.** This meant:
- FK always returned `[0.391, 0, 0.226]` (zero-config EE) no matter the actual joint angles
- IK was always seeded from zero config, not the current arm position
- All Cartesian primitives (move_left, move_forward, etc.) were based on wrong starting position

**Fix**: Added `_normalize_joint_dict()` that strips `.pos` suffix. Applied to both FK and IK input paths.

**Validation**: After the fix, FK at rest position correctly returns `~[0.145, 0.026, -0.009]` (matches PyBullet). 10cm XY square trajectory computed via IK and executed on real hardware — arm traced the expected shape.

**Impact on Phase 5.5**: The original reason for Phase 5.5 (placo IK produces wrong positions) was **partly caused by this bug**. With the fix, placo FK/IK may be accurate enough for the current primitives. Phase 5.5 (lookup table) may be deferred or reduced in scope. Further hardware testing needed to confirm.

**Methodology lesson**: When debugging FK/IK, always verify the data flow first — check that the function actually receives the joint angles you think it does, before questioning the kinematic model.

---

## 2026-04-12 — Phase 5.5 Skipped: FK/IK Good Enough

**Decision**: Skip Phase 5.5 (Joint-Space Lookup Table) entirely. Proceed directly to Phase 6.

**Reason**: The `.pos` suffix bug was the root cause of IK failures on hardware. With the fix applied and validated (10cm XY square traced correctly), placo FK/IK is accurate enough for the current primitives. Building a lookup table from 75 hand-measured positions is high effort for marginal gain.

**Impact**:
- Phase 5.5 marked as SKIPPED in BACKLOG.md
- Phase 6 (Imitation Learning Pipeline) is now unblocked
- `kinematics.py` remains the motion control path for both sim and hardware
- `calibration/record_grid.py` stays as-is (could be useful later for fine-tuning accuracy)
- `control/` directory (joint_lookup, trajectory, executor) will NOT be built

---

## 2026-04-12 — Two-Path Strategy: Path B (top-down) + Path A (bottom-up)

**Decision**: Pursue two complementary approaches to imitation learning, not one.

### Path B — Top-Down (CURRENT, Phase 6)

Hand-designed object-relative primitives → segmenter decomposes teleop demos into tool call sequences → few-shot/RAG injection into LLM prompt → LLM reasons and plans from day one.

- Fast to build (4 weekends)
- Fully interpretable — you can read and improve the LLM's reasoning
- Primitive vocabulary is human-designed (may not match what the robot actually needs)

### Path A — Bottom-Up (FUTURE, research track)

Low-level axis primitives at very high frequency → LLM acts as trajectory replayer → embed tool call sequences (e.g. `[right(0.01), right(0.01), down(0.01), grasp(3)]` → vector) → similar sequences map to nearby vectors → natural action clusters emerge → those clusters become data-driven primitives → retrain LLM to plan over discovered vocabulary.

- Essentially Action Chunking (ACT) but over tool-call tokens instead of joint-angle tokens
- 3-6 month research project, not a weekend POC
- Loses interpretability during the middle phase (embeddings are opaque)
- Risk: at high frequency the LLM becomes an expensive trajectory interpolator — a tiny MLP would be faster
- Real value is the **bootstrap path**: low-level replay is just data collection → embedding is vocabulary discovery → final phase restores LLM as planner over grounded vocabulary

### Strategy

- **Do Path B now** to prove the full loop works (LLM + primitives + demos)
- **Path A runs as passive data collection**: every teleoperation session records full high-frequency trajectories, building the dataset for future embedding analysis
- When enough data exists, run embedding analysis offline to see if natural clusters emerge
- If clusters match hand-designed primitives → validation. If they diverge → upgrade the vocabulary
- Path A retroactively validates or improves Path B. They are not mutually exclusive.

---

## 2026-04-12 — Implementation Plan: move_to_delta + Full Loop

**Context**: The axis-aligned primitive vocabulary (`move_left`, `move_forward`...) is the root cause of segmenter infidelity. A diagonal arm movement gets decomposed into sequential staircase moves. Replaying those moves traces a different path than the original. This makes Test Zero almost guaranteed to fail with the current setup.

### Key decisions

**1. New primitive: `move_to_delta(dx, dy, dz)`**

A single tool call that moves the end-effector diagonally in 3D. Implementation: read current joints → FK → add (dx,dy,dz) → IK → send joints. Same as existing axis-aligned primitives but composes all 3 axes in one move. The LLM doesn't need absolute coordinates — it reasons in relative displacements ("5cm forward and 3cm down simultaneously").

The existing axis-aligned primitives (`move_left`, etc.) become convenience aliases — `move_left(0.05)` is just `move_to_delta(0, 0.05, 0)`.

**2. Segmenter v2: waypoint-based**

Instead of greedy dominant-axis → axis-aligned primitives, detect **waypoints** (direction changes, velocity drops, gripper events) and emit one `move_to_delta(dx,dy,dz)` per segment. Much simpler algorithm, much more faithful output. Waypoint density is tunable: more waypoints = more faithful, fewer = more abstract.

**3. Full loop must exist before optimizing**

Camera + perception + LLM → tool calls → robot. Even if the LLM can't plan correctly, the infrastructure must be end-to-end. This is the test bed for everything that follows.

### Implementation order

See BACKLOG.md Phase 6A and 6B for task breakdown.

---

## 2026-04-12 — The Segmenter is the Critical Gate

**Context**: Before choosing between Path A and Path B, we identified a circular dependency in the reasoning:

1. Path B assumes the segmenter faithfully decomposes teleop demos into primitive sequences
2. If the segmenter is approximate, replayed sequences don't reproduce the task
3. Compensating with closed-loop vision feedback (camera + LLM adjusts) won't work — an LLM is not a world model
4. This pushes back toward Path A (high-frequency replay → embedding → discovered vocabulary)
5. But Path A is a 3-6 month research project

**Decision**: The segmenter is the critical gate. Before committing to either path, we must run **Test Zero**:

1. Take a teleoperated episode (sticks_v1)
2. Run it through the segmenter → sequence of MCP tool calls
3. Replay that sequence on the robot via MCP primitives
4. Observe: does the arm reproduce the original task?

**If Test Zero passes** (segmenter output replays correctly):
- Path B is viable — segmenter fidelity is sufficient
- Proceed with demo store, RAG, few-shot, fine-tuning
- The hand-designed primitive vocabulary works well enough

**If Test Zero fails** (replayed sequence doesn't match original task):
- Path B collapses — everything built on segmenter output inherits the error
- Options to explore:
  - **Improve the segmenter**: tune thresholds, better smoothing, smarter merging
  - **Replace the segmenter with a learned model**: train a small model (not hand-coded heuristics) to parse trajectories into primitives — this is a research axis of its own
  - **Skip segmentation entirely**: go Path A — high-frequency replay, embed raw tool call sequences, let clusters emerge from data
- The "learned segmenter" option is interesting: a model that watches a trajectory and outputs the primitive decomposition could generalize better than greedy axis-dominant heuristics, but it needs training data (pairs of trajectories + ground-truth primitive sequences), which is a chicken-and-egg problem unless bootstrapped from the heuristic segmenter

**Open research question**: Is there a middle ground between a static heuristic segmenter and a full Path A embedding pipeline? A learned segmenter (small transformer or even an LLM prompted with trajectory data) could be that middle ground — more adaptive than heuristics, less infrastructure than full embedding discovery. This is worth exploring but is a separate research axis.

**Key insight**: The architecture's value proposition (LLM reasons, primitives execute) only holds if there exists a faithful mapping between continuous trajectories and discrete primitive sequences. The segmenter *is* that mapping. If it's lossy, the entire decoupled approach needs rethinking.
