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

## Phase 5.5 — Fix Motion Control: Joint-Space Lookup (CURRENT — BLOCKER)

> **Why this comes first**: The current IK (placo/PyBullet) produces wrong positions on
> real hardware because the DH parameters don't match the 3D-printed arm geometry. Every
> Cartesian primitive (move_left, move_forward, etc.) is unreliable. Phase 6 imitation
> learning builds on these primitives — if they don't work, segmenter output is meaningless.
> This must be fixed before anything else.

### 5.5.1 Build Calibration Recording Script

- [ ] **Create `calibration/record_grid.py`** — Interactive script: connects to leader+follower, prompts "move arm to position, press ENTER to record", reads joint angles via `robot.get_observation()`, accepts manual position input (x, y, z in meters via ruler), saves to `calibration/calibration_data.json`. Must support resuming (append to existing file) and display recorded count + workspace coverage.
  - *Done when*: Script runs, records one point with position + joints, saves JSON
  - *Time*: 30 min
  - *Tag*: `claude-code` (scaffold), then `hardware` (test on robot)

- [ ] **Record calibration grid** — Teleoperate arm to ~75 positions across workspace. X: 0.15–0.35m (5 pts), Y: ±0.15m (5 pts), Z: table to +0.15m (3 heights). Plus 5-10 extra at key locations (home, grasp height). Measure positions with ruler.
  - *Done when*: `calibration_data.json` has 75+ entries with plausible positions
  - *Time*: 45–60 min (one longer session)
  - *Note*: `hardware` — this is the one session that can't be micro

### 5.5.2 Build Joint Lookup

- [ ] **Create `control/joint_lookup.py`** — Load calibration JSON, build KDTree from positions, implement `solve(target_xyz)` with KNN (K=6) + inverse-distance weighting. Add workspace bounds check: refuse targets >5cm from any recorded point. Add `get_workspace_bounds()` method.
  - *Done when*: Unit test passes: `solve(recorded_point)` returns the recorded joints (± tolerance)
  - *Time*: 30 min
  - *Tag*: `claude-code`

- [ ] **Add RBF interpolation option** — Optionally upgrade from KNN to `scipy.interpolate.RBFInterpolator` with thin_plate_spline kernel for smoother results. Keep KNN as fallback.
  - *Done when*: Both interpolation modes work, can toggle via config
  - *Time*: 20 min
  - *Tag*: `claude-code`

### 5.5.3 Build Trajectory Execution

- [ ] **Create `control/trajectory.py`** — `minimum_jerk_joint_trajectory(q_start, q_end, duration, hz)` → (steps, num_joints) array. `compute_duration(q_start, q_end, speed)` with three presets: "slow" (near objects), "normal", "fast" (free space).
  - *Done when*: Unit test: trajectory starts at q_start, ends at q_end, has zero velocity at endpoints
  - *Time*: 20 min
  - *Tag*: `claude-code`

- [ ] **Create `control/executor.py`** — `TrajectoryExecutor` wrapping the robot. `execute(trajectory, gripper_value)` sends joints at 50Hz with timing control. Position history buffer for `go_back(steps)`.
  - *Done when*: Can execute a min-jerk trajectory in simulation or dry-run mode
  - *Time*: 30 min
  - *Tag*: `claude-code`

### 5.5.4 Wire Into MCP Server

- [ ] **Replace IK path with lookup** — Update the MCP primitives (move_left, move_forward, etc.) to use `JointLookup.solve()` → `minimum_jerk_trajectory()` → `TrajectoryExecutor.execute()` instead of `kinematics.py` FK/IK. Keep `kinematics.py` for simulation fallback.
  - *Done when*: `move_forward(0.05)` on real hardware actually moves forward 5cm (± 1cm)
  - *Time*: 30 min
  - *Note*: `hardware` — needs physical verification

- [ ] **Build `calibration/validate_grid.py`** — Command arm to each recorded position sequentially, visually verify accuracy. Flag points with large errors for re-recording.
  - *Done when*: Arm visits 10+ recorded points and they all look correct
  - *Time*: 20 min
  - *Tag*: `claude-code` (scaffold), then `hardware` (run on robot)

### 5.5.5 Validate End-to-End

- [ ] **Run a manual pick-and-place** — Using the new lookup-based primitives: move_forward → move_down → grasp → move_up → move_left → release. Does the arm actually do what the primitives say?
  - *Done when*: You can pick up an object and place it somewhere else using MCP tool calls
  - *Time*: 30 min
  - *Note*: `hardware` — the real test

---

## Phase 6 — Imitation Learning Pipeline (BLOCKED ON 5.5)

> **⚠ Do not start Phase 6 until Phase 5.5 is complete.** The segmenter decomposes
> teleoperation into primitives. If those primitives don't execute correctly (because IK
> is broken), the entire imitation learning pipeline produces garbage.

### 6.1 Validate Existing Tooling

- [ ] **Run visualizer on sticks_v1** — `uv run python -m scripts.visualize_trajectory --dataset datasets/sticks_v1` → screenshot the 3D EE plot, sanity-check that FK positions look plausible. If the arm goes through the table or into space, there's a FK/joint-mapping bug.
  - *Done when*: You have a screenshot and a yes/no on "do these trajectories look right?"
  - *Time*: 15 min

- [ ] **Run segmenter on sticks_v1** — `uv run python -m scripts.segment_trajectory --dataset datasets/sticks_v1` → inspect the output primitive sequences. Do they make intuitive sense? (e.g., move_forward → move_down → grasp → move_up)
  - *Done when*: You have JSON output and a gut-check assessment
  - *Time*: 15 min

- [ ] **Tune segmenter thresholds** — Adjust `SMOOTH_K` and `MIN_PRIM_DIST` in the segmenter until the output primitive sequences match what you visually see in the trajectory plot. This is an iterative loop: change params → re-run → compare.
  - *Done when*: At least one episode produces a "yeah, that looks right" primitive sequence
  - *Time*: 30 min

### 6.2 Demo Storage & Retrieval

- [x] **Design demo store schema** — Schema documented in `decras/imitation/retrieval.py` as `Demo`, `Primitive`, `DemoMetadata` dataclasses with full docstring.
  - *Done when*: Schema documented (even as a comment in code)
  - *Time*: 15 min
  - *Tag*: `claude-code` — Claude Code can scaffold this

- [ ] **Build demo store writer** — Script/function that takes segmenter output → writes to demo store format. Put in `decras/imitation/retrieval.py` (or `scripts/` for now).
  - *Done when*: Can run `segment_trajectory | store_demo` and see a JSON file on disk
  - *Time*: 30 min
  - *Tag*: `claude-code`

- [ ] **Build demo retriever** — Given a task description string, find the N most similar stored demos. Start simple: TF-IDF or sentence-transformer cosine similarity on task descriptions. No need for a vector DB — you'll have < 100 demos.
  - *Done when*: `retrieve("pick up the stick") → [demo_1, demo_3]` works
  - *Time*: 30 min
  - *Tag*: `claude-code`

- [ ] **RAG integration** — Inject retrieved demo primitive sequences into the LLM system prompt as few-shot examples. Modify `llm_controller/prompt.py` to accept an optional `demo_context` parameter.
  - *Done when*: The LLM's system prompt includes "Here's how a similar task was done: [primitive sequence]"
  - *Time*: 30 min

### 6.3 Fine-Tuning Data Preparation

- [ ] **Export training pairs** — From the demo store, generate `(task_description, tool_call_sequence)` pairs in JSONL format suitable for fine-tuning. Each line: `{"messages": [{"role": "user", "content": "pick up the red cube"}, {"role": "assistant", "content": "observe() → move_forward(0.05) → ..."}]}`
  - *Done when*: JSONL file exists with at least 5 real training pairs
  - *Time*: 30 min
  - *Tag*: `claude-code`

- [ ] **Record more demos** — You need variety. Record 5-10 episodes of different simple tasks (pick-place cube, push object, stack). Each recording session is ~15 min.
  - *Done when*: 3+ different task types in your dataset
  - *Time*: 15 min per task type (multiple sessions)
  - *Note*: Requires hardware access

---

## Phase 6.5 — Perception on Real Hardware (INDEPENDENT — can do anytime)

- [ ] **Install IP Webcam on phone** — Android app, free. Connect phone to same WiFi as robot PC. Note the stream URL (usually `http://<phone-ip>:8080/video`).
  - *Done when*: You can open the stream URL in a browser and see live video
  - *Time*: 10 min

- [ ] **Test ArUco detection on phone stream** — Write a quick OpenCV script that reads from the IP Webcam URL and runs ArUco detection. Print detected marker IDs and corners.
  - *Done when*: Script prints marker IDs when you hold an ArUco marker in front of the phone
  - *Time*: 20 min
  - *Tag*: `claude-code`

- [ ] **Print ArUco markers** — Generate and print 5-10 ArUco markers (use `cv2.aruco` dictionary). Tape them to objects in the workspace.
  - *Done when*: Physical markers exist and are detectable by the script above
  - *Time*: 15 min (plus printer access)

- [ ] **Wire phone camera into perception pipeline** — Update `perception/camera.py` to accept an IP Webcam URL as input source (alongside USB webcam). The scene graph builder should work unchanged.
  - *Done when*: `observe()` MCP tool returns scene graph with ArUco-detected objects via phone camera
  - *Time*: 30 min
  - *Tag*: `claude-code`

---

## Phase 7 — Memory & Context (FUTURE — don't start yet)

- [ ] Design persistent memory format (what worked, what failed, object locations)
- [ ] Implement task decomposition in LLM prompt
- [ ] Build error recovery loop (grasp failed → re-observe → retry with adjustment)

---

## Architectural Debt (DO WHEN IT HURTS, NOT BEFORE)

- [ ] Refactor `scripts/` into `decras/` library (see PROJECT_STATUS.md for planned structure)
- [ ] Remove placo/PyBullet IK dependency once lookup table is proven stable
- [ ] Upgrade calibration from ruler measurements to ArUco-based EE position measurement

---

## Quick Reference: Labels

| Label | Meaning |
|-------|---------|
| `claude-code` | Can be done entirely by Claude Code from a GitHub Issue |
| `hardware` | Requires physical robot access |
| `independent` | No dependencies — can do anytime |
| `research` | Requires thinking/design, not just coding |
