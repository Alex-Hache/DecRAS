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
