# DecRAS — Backlog (15-30 min tasks)

> **How to use this file**:
> 1. Pick the top unchecked task in your current phase
> 2. Do it in one session (15-30 min)
> 3. Check it off, commit, push
> 4. If you're on your phone, create a GitHub Issue with the task title and label `claude-code`
>    → Claude Code can pick it up (see WORKFLOW.md)
>
> Tasks are ordered by dependency. Don't skip ahead unless marked "independent".

---

## Phase 5.5 — Fix Motion Control: Joint-Space Lookup (SKIPPED)

> **SKIPPED (2026-04-12)**: The `.pos` suffix bug in kinematics.py was the root cause of IK
> failures on hardware (see DECISIONS.md, 2026-04-08). With the fix applied and validated
> (10cm XY square traced correctly), placo FK/IK is accurate enough. Lookup table approach
> abandoned — high effort for marginal gain.

### 5.5.1 Build Calibration Recording Script

- [x] **Create `calibration/record_grid.py`** — Interactive script: connects to leader+follower, prompts "move arm to position, press ENTER to record", reads joint angles via `robot.get_observation()`, accepts manual position input (x, y, z in meters via ruler), saves to `calibration/calibration_data.json`. Must support resuming (append to existing file) and display recorded count + workspace coverage.
  - *Done when*: Script runs, records one point with position + joints, saves JSON
  - *Time*: 30 min
  - *Tag*: `claude-code` (scaffold), then `hardware` (test on robot)

- [x] **Record calibration grid** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

### 5.5.2 Build Joint Lookup

- [x] **Create `control/joint_lookup.py`** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

- [x] **Add RBF interpolation option** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

### 5.5.3 Build Trajectory Execution

- [x] **Create `control/trajectory.py`** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

- [x] **Create `control/executor.py`** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

### 5.5.4 Wire Into MCP Server

- [x] **Replace IK path with lookup** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

- [x] **Build `calibration/validate_grid.py`** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

### 5.5.5 Validate End-to-End

- [x] **Run a manual pick-and-place** — *(skipped — Phase 5.5 abandoned, see DECISIONS.md 2026-04-12)*

---

## Phase 6A — move_to_delta + Segmenter v2 (CURRENT)

> The axis-aligned primitive vocabulary is the root cause of segmenter infidelity.
> `move_to_delta(dx, dy, dz)` fixes this by allowing diagonal moves in a single call.
> Axis-aligned primitives become aliases. See DECISIONS.md (2026-04-12).

### 6A.1 Add `move_to_delta` primitive

- [x] **Implement `move_to_delta(dx, dy, dz)` in server.py** — Read current joints → FK → add delta vector → IK → send joints. Single tool call, diagonal movement. Existing axis-aligned primitives (`move_left`, etc.) become thin wrappers that call `move_to_delta` internally.
  - *Done when*: `move_to_delta(0.05, -0.03, 0.0)` moves the arm diagonally in sim, tests pass
  - *Time*: 30 min
  - *Tag*: `claude-code`

- [x] **Refactor axis-aligned primitives as aliases** — `move_left(d)` → `move_to_delta(0, d, 0)`, etc. Keep the old tool names registered (LLM still uses them), but the implementation is a one-liner.
  - *Done when*: All existing tests still pass, axis-aligned tools call `move_to_delta` internally
  - *Time*: 20 min
  - *Tag*: `claude-code`

- [ ] **Hardware validation** — Test `move_to_delta` on the real arm. Diagonal move (e.g. 5cm forward + 3cm down) should trace a straight line, not a staircase.
  - *Done when*: Visual confirmation on hardware
  - *Time*: 15 min
  - *Tag*: `hardware`

### 6A.2 Segmenter v2 (waypoint-based)

- [ ] **Rewrite segmenter core** — Replace greedy dominant-axis algorithm with waypoint detection. Detect direction changes (angle threshold on velocity vector) + velocity drops + gripper events. Between waypoints, emit one `move_to_delta(dx, dy, dz)`. Gripper events still produce `grasp()`/`release()`.
  - *Done when*: Segmenter v2 on sticks_v2 produces shorter, more intuitive sequences than v1
  - *Time*: 45 min
  - *Tag*: `claude-code`

- [ ] **Add waypoint density parameter** — `--density low|medium|high` controls angle threshold for direction changes. High = many small waypoints (faithful replay). Low = few large waypoints (abstract, more like "intent").
  - *Done when*: Same episode produces 5 primitives (low) vs 20 primitives (high)
  - *Time*: 20 min
  - *Tag*: `claude-code`

- [ ] **Visualize segmenter output** — Overlay waypoints on the 3D trajectory plot. Each `move_to_delta` is a straight-line segment. Visual check: do the segments approximate the original curve?
  - *Done when*: matplotlib plot with trajectory + waypoint markers
  - *Time*: 20 min
  - *Tag*: `claude-code`

### 6A.3 Test Zero

- [ ] **Replay segmenter v2 output on hardware** — Take sticks_v2 episode 0, run through segmenter v2 (high density), replay the `move_to_delta` sequence via MCP tools on the real arm. Film it. Compare to the original teleop recording.
  - *Done when*: Side-by-side comparison video. Honest assessment: does the arm do the same thing?
  - *Time*: 30 min
  - *Tag*: `hardware`
  - **This is the critical gate.** If this fails, Path B needs rethinking.

---

## Phase 6B — Full Loop: Camera + LLM + Robot (NEXT)

> The LLM observe-think-act loop must work end-to-end before optimizing any part.
> Expect the LLM to fail at planning — but the infrastructure must be there.

### 6B.1 Camera setup

- [ ] **Install IP Webcam on phone** — Android app, connect to same WiFi as robot PC. Note stream URL (`http://<phone-ip>:8080/video`).
  - *Done when*: Stream URL opens in browser with live video
  - *Time*: 10 min

- [ ] **Wire phone camera into perception pipeline** — Update `perception/camera.py` to accept an IP Webcam URL as input source (alongside USB webcam). Scene graph builder should work unchanged.
  - *Done when*: `observe()` MCP tool returns scene graph with detected objects via phone camera
  - *Time*: 30 min
  - *Tag*: `claude-code`

### 6B.2 LLM loop end-to-end

- [ ] **Test LLM loop with real hardware + camera** — Run `llm_controller/main.py` with the real arm and phone camera. Give it a simple task ("pick up the stick"). Observe what it tries to do. Record the full interaction log.
  - *Done when*: LLM produces tool calls, arm moves, you have an interaction log to analyze
  - *Time*: 30 min
  - *Tag*: `hardware`

- [ ] **Analyze failure modes** — The LLM will almost certainly fail. Document *how* it fails: wrong tool sequence? wrong distances? doesn't understand scene graph? This analysis drives what to build next.
  - *Done when*: Written analysis of failure modes (append to DECISIONS.md)
  - *Time*: 15 min

### 6B.3 First RAG experiment (if Test Zero passed)

- [ ] **Inject demo sequence into LLM prompt** — Take a successful segmenter v2 sequence, hardcode it as a few-shot example in `llm_controller/prompt.py`. Re-run the LLM loop on the same task. Does the example help?
  - *Done when*: Comparison: LLM output with vs without the demo example
  - *Time*: 30 min

---

## Phase 6C — Demo Store & Retrieval (AFTER 6A + 6B)

> Only worth building once Test Zero passes and the LLM loop exists.

- [x] **Design demo store schema** — `decras/imitation/retrieval.py` — `Demo`, `Primitive`, `DemoMetadata` dataclasses.

- [ ] **Build demo store writer** — Segmenter v2 output + task string → Demo JSON on disk.
  - *Tag*: `claude-code`

- [ ] **Build demo retriever** — TF-IDF or sentence-transformer cosine similarity on task descriptions. `retrieve("pick up the stick") → [demo_1, demo_3]`.
  - *Tag*: `claude-code`

- [ ] **RAG integration** — Inject retrieved demos into LLM prompt via `llm_controller/prompt.py`.

- [ ] **Record more demos** — 5-10 episodes of different tasks (pick-place, push, stack).
  - *Tag*: `hardware`

- [ ] **Export fine-tuning pairs** — `(task_description, tool_call_sequence)` JSONL for fine-tuning.
  - *Tag*: `claude-code`

---

## Phase 7 — Memory & Context (FUTURE — don't start yet)

- [ ] Design persistent memory format (what worked, what failed, object locations)
- [ ] Implement task decomposition in LLM prompt
- [ ] Build error recovery loop (grasp failed → re-observe → retry with adjustment)

---

## Architectural Debt (DO WHEN IT HURTS, NOT BEFORE)

- [ ] Refactor `scripts/` into `decras/` library (see PROJECT_STATUS.md for planned structure)
- [ ] Upgrade calibration from ruler measurements to ArUco-based EE position measurement

---

## Quick Reference: Labels

| Label | Meaning |
|-------|---------|
| `claude-code` | Can be done entirely by Claude Code from a GitHub Issue |
| `hardware` | Requires physical robot access |
| `independent` | No dependencies — can do anytime |
| `research` | Requires thinking/design, not just coding |
