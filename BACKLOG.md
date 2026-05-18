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

- [x] **Hardware validation** — Test `move_to_delta` on the real arm. Diagonal move (e.g. 5cm forward + 3cm down) should trace a straight line, not a staircase.
  - *Done 2026-04-19*: Validated on hardware via `move_to_delta_validation.ipynb`. Diagonal XZ (+5cm X, -3cm Z) reaches 87% on X (was 35% before fix). Y axis perfect (~1mm error). Down moves accurate. Bug found and fixed in `move_cartesian_delta`: was reading mid-motion `get_observation()` between sub-steps + 200ms inner interpolation too fast for servo. Rewrote to plan all waypoints upfront from FK seed, chain IK seeds, use convergence-based wait + active-hold final pose. Residual ~6mm error is gravity sag (bounded).
  - *Known limit*: +Z up moves only reach ~25-50% (servo torque limit, not software). Filed as 6A.1.x below.

- [x] **Z-up gravity compensation** *(follow-up to 6A.1 hardware validation)* — Root cause: gravity droop (`q_actual = q_ref − τ_gravity / Kp_eff`), not torque saturation. Fixed 2026-05-18 by P-gain sweep: P=28 gives 91.7% reach (was 69.8% at P=16). Set `DECRAS_SERVO_P_GAIN=28` in `.mcp.json`. Placo-based compliance correction infrastructure also built (`gravity_torques_dict`, `SERVO_COMPLIANCE_DEG_PER_NM`, `LOG_GRAVITY_ERRORS`) but not needed — P-gain alone clears the >80% target.
  - *Done 2026-05-18*: P=16→70%, P=24→88%, P=28→92%. Settled on P=28.

### 6A.2 Segmenter v2 (waypoint-based)

- [x] **Rewrite segmenter core** — Replaced greedy dominant-axis algorithm with waypoint detection. Direction changes (windowed velocity-vector angle), speed dips (local minima below fraction of v_max), and gripper events are all waypoints. Between waypoints, emits one `move_to_delta(dx, dy, dz)`. Gripper events still produce `grasp()`/`release()`.
  - *Done*: sticks_v2 went from 19 v1 primitives (staircase) to 13 v2 primitives at medium / 7 at low — shorter and diagonals stay diagonal.

- [x] **Add waypoint density parameter** — `--density low|medium|high` scales angle threshold, dip ratio, and min-segment distance together.
  - *Done*: sticks_v2 episode 0 produces 7 / 13 / 26 primitives at low / medium / high.

- [x] **Visualize segmenter output** — `scripts/visualize_trajectory.py --segment --density {low|medium|high}` overlays raw trajectory (faded) + dashed straight-line segments + diamond waypoint markers.
  - *Done*: segments visually approximate the original curve; low is skeletal, high tracks the curves closely.

### 6A.3 Test Zero

- [x] **Replay segmenter v2 output on hardware** — sticks_v3 ep0, tested at 19/21/31/49 primitives. Structure correct (approach → descent → grasp zone → transit → release → retreat). **PASSES.** Gravity sag causes drift in extended-arm sections — tracked separately.
  - *Done 2026-05-17*: `scripts/replay_sequence.py` (new) reads starting joints from Parquet and replays via `LeRobotInterface` directly

---

## Phase 6B — Full Loop: Camera + LLM + Robot (NEXT)

> The LLM observe-think-act loop must work end-to-end before optimizing any part.
> Expect the LLM to fail at planning — but the infrastructure must be there.

### 6B.1 Camera setup

- [x] **Install IP Webcam on phone** — DONE (2026-04-19): stream at `http://192.168.129.1:8080/video`, verified returning 1920×1080 BGR frames.

- [x] **Wire phone camera into perception pipeline** — DONE (2026-04-19): `Camera(source)` accepts int (USB) or string URL; bare `host:port` normalized to `http://host:port/video`. `CAMERA_SOURCE` in `config.py` reads `DECRAS_CAMERA` env var (digits → int, else URL). `.mcp.json` sets `DECRAS_CAMERA=192.168.129.1:8080`. Live test: `Camera(CAMERA_SOURCE).capture()` returns a real frame from the phone; detector runs without error.

### 6B.2 LLM loop end-to-end

- [x] **Test LLM loop with real hardware + camera** — DONE (2026-05-18): full pick-and-place sequence executed. Arm moved correctly; perception was broken (CAMERA_TO_ROBOT_MATRIX=None → x=0.70m out-of-workspace). See EXPERIMENT_REPORT_2026_05_18.md.

- [x] **Analyze failure modes** — DONE (2026-05-18): root causes documented in EXPERIMENT_REPORT_2026_05_18.md. Failures: (1) uncalibrated camera transform, (2) no image in observe(), (3) false-positive grasp signal.

- [x] **Fix: expose camera image in observe()** — DONE (2026-05-18): observe() now returns [JSON, Image(jpeg)] so LLM can visually verify scene. Also fixed env propagation to MCP subprocess (SIMULATE etc. were being stripped by MCP's default env).

- [x] **Fix: few-shot example + move_to_delta in prompt** — DONE (2026-05-18): prompt.py updated with coordinate frame hints, move_to_delta (not move_to), and annotated sticks_v3 pick-and-place few-shot.

### 6B.3 — SUPERSEDED

Camera calibration and visual servoing are dropped. Second experiment (2026-05-18) confirmed:
camera is body-fixed → image doesn't change as EE moves → visual servoing is impossible without
calibration, and calibration contradicts the architecture goal (no fixed camera dependency).

**Decision**: pixel-to-robot transform removed from observe(). Camera serves semantic grounding
only (did the scene change?), not metric navigation. See DECISIONS.md 2026-05-18.

**Next**: Phase 6D — collect 30+ teleop demos. The LLM reactive loop returns in Phase 6F
over a *learned* vocabulary, not over raw move_to_delta coordinates.

---

## Phase 6C — Demo Store (DONE, retriever/RAG superseded by Phase 6F)

> Schema + writer are built. Retriever / RAG / fine-tuning items now live in Phase 6F
> (RAG over discovered codes, not over raw `move_to_delta` sequences).
> See `EMERGENT_ROBOTICS_PLAN.md` and ARCHITECTURE.md decisions #8 and #9.

- [x] **Design demo store schema** — `decras/imitation/retrieval.py` — `Demo`, `Primitive`, `DemoMetadata` dataclasses.
- [x] **Build demo store writer** — `decras.imitation.store` (save_demo/load_demo/list_demos/ingest_sequence), CLI `scripts/add_demo.py`, deterministic id, provenance fields.

---

## Phase 6D — Data Collection for Vocabulary Discovery (NEXT)

> 30+ teleop demos with deliberate variation so the VQ-VAE can discover meaningful action
> structure. Plan reference: Phase 1 in `EMERGENT_ROBOTICS_PLAN.md`.
>
> **Gate**: Test Zero (6A.3) must pass first. If delta replay fails on hardware, the
> conditioned policy in 6E will fail for the same reason.

### 6D.1 Recorder upgrades

- [ ] **Gripper force in observation** — Plan wants `gripper.force`. Decide: read force from Feetech if supported, or drop force and use gripper position deltas as the open/close signal. Document.
  - *Tag*: `research`, then `claude-code`
  - *Time*: 30 min

- [ ] **Wire camera frames into recorder** — Capture from `DECRAS_CAMERA` at 5Hz (every 6th control frame), store aligned with Parquet rows. Needed for later JEPA / scene graph annotation.
  - *Tag*: `claude-code`
  - *Time*: 30 min

### 6D.2 Record 30 demos with variation

- [ ] **Pick 2-3 task types** — e.g. cup→plate, block→stack, stick→bin. 10 demos each. Document in `datasets/README.md`.
  - *Tag*: `hardware`

- [ ] **Vary starting positions deliberately** — Object positions, arm start poses, approach angles. At least 3 distinct starting regions per task. The plan is explicit: uniform starts kill conditioned-policy generalization.
  - *Tag*: `hardware`
  - *Time*: 30-45 min per batch of 10

- [ ] **Coverage sanity check** — `scripts/visualize_trajectory.py` over the new dataset. EE paths should span the workspace.
  - *Tag*: `claude-code`

---

## Phase 6E — Action VQ-VAE (after 6D)

> ~300 LOC PyTorch. Plan reference: Phase 2.

### 6E.1 Baseline segments

- [ ] **Use segmenter v2 (medium) as segment source** — Already built. Per demo: ordered list of (delta_sequence, start_state, end_state) segments.
  - *Tag*: `claude-code`

- [ ] **Segment-distribution viz** — Histogram of segment lengths, directions, cause (gripper / direction change / speed dip). Informs choice of K.
  - *Tag*: `claude-code`

### 6E.2 Train VQ-VAE

- [ ] **Build `decras/imitation/vqvae.py`** — 1D CNN or small GRU encoder, learnable codebook (K=8 first; try 12 and 16), decoder reconstructs delta sequence. Reconstruction + commitment losses.
  - *Tag*: `claude-code`
  - *Time*: 2-3h

- [ ] **`scripts/train_vqvae.py`** — Read `demos/` segments, train, save checkpoint + codebook.
  - *Tag*: `claude-code`

### 6E.3 Validate vocabulary

- [ ] **Codebook usage report** — Dead codes → reduce K. Wildly different members → increase K.
- [ ] **Per-code member viz** — Overlay all delta trajectories mapping to code k. Should look similar in direction + speed profile.
- [ ] **Encode all demos to code sequences** — Persist `segment_id → code` and per-demo `code_sequence` into the demo store.

---

## Phase 6F — Conditioned Policy + LLM Grounding + RAG-over-codes

> ~200 LOC for the policy, rest is glue. Plan reference: Phases 3 + 4.

### 6F.1 Conditioned policy

- [ ] **Build `decras/imitation/policy.py`** — Small MLP/GRU. Input: current joints + gripper + one-hot code. Output: next delta + gripper action. BC training on (state_t, gripper_t, code) → (delta_t, gripper_action_t).
  - *Tag*: `claude-code`

- [ ] **`scripts/train_policy.py`**
  - *Tag*: `claude-code`

- [ ] **Held-out replay test** — Held-out demo, encoded to codes, executed by the policy from the recorded starting state. Does it match the demo?
  - *Tag*: `hardware`

- [ ] **Generalization test** — Same code from a different starting state. Sensible behavior?
  - *Tag*: `hardware`

### 6F.2 LLM grounding

- [ ] **Collect before/after scene-graphs per code** — For each code, gather scene graphs before/after every segment that maps to it. Feed to LLM, save the assigned name in codebook metadata.
  - *Tag*: `research`

### 6F.3 MCP `execute_code(k)` tool

- [ ] **Add `execute_code(code: int)` MCP tool** — Loads conditioned policy, runs at 50Hz from current state + code, returns post-execution scene graph.
  - *Tag*: `claude-code`

- [ ] **Keep `move_to_delta` registered** — Useful for debugging and fallback.

### 6F.4 RAG over codes

- [ ] **Extend `Primitive` dataclass** — Add code-mode variant `{code: int, name: str}` alongside the current tool-call variant.
  - *Tag*: `claude-code`

- [ ] **Code-sequence retriever** — Cosine similarity over `(task_embedding, scene_features)` where scene_features = object positions + gripper state + starting EE pose. Top-K past code sequences.
  - *Tag*: `claude-code`

- [ ] **RAG integration** — Inject retrieved code sequences into `llm_controller/prompt.py`. Bootstrap by encoding all 30 Phase 6D demos.
  - *Tag*: `claude-code`

- [ ] **End-to-end demo** — Natural-language task → LLM plans code sequence (with RAG few-shot) → MCP executes via `execute_code` → reactive replan after each code. Film a full pick-and-place.
  - *Tag*: `hardware`

---

## Phase 7 — Rotation, JEPA, Memory (FUTURE)

- [ ] Extend deltas to (dx, dy, dz, dθ); retrain VQ-VAE + policy with 4D action space
- [ ] JEPA enters: encode (delta_sequence, latent_state_transition) pairs so vocabulary is grounded in what the world does, not just what the robot does
- [ ] Persistent memory across sessions (what worked, what failed, object locations)
- [ ] Error recovery loop (grasp failed → re-observe → retry with adjustment)
- [ ] Optional: fine-tune LLM on accumulated (task, scene, code_sequence) data if RAG hits a ceiling

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
