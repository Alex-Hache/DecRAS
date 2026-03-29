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
