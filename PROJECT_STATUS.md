# DecRAS — Project Status & Roadmap

## What is DecRAS?

Distributed Robotics Architecture challenging monolithic VLA models.
The core thesis: split reasoning (LLM) from execution (MCP primitives) from perception (vision pipeline), connected via MCP protocol.

**Stack**: Claude/Ollama (reasoning) + MCP server (motor primitives) + LeRobot SDK (SO-101 hardware) + PyBullet (simulation)

## Current State (April 2026)

### Working

- **MCP server** with 21 tools: `observe`, `move_to`, `move_to_delta`, `grasp`, `release`, `stop`, `go_back`, `get_status`, `calibrate`, `read_joints`, `send_joints`, `start_episode`, `end_episode`, `move_left`, `move_right`, `move_up`, `move_down`, `move_forward`, `move_back`, `rotate_gripper`, `tilt_gripper`
  - `move_to_delta(dx, dy, dz)` — diagonal 3D EE move in a single IK call; axis-aligned primitives are now aliases
  - **Hardware validated April 2026**: traces clean diagonals to within ~6mm (gravity sag floor). Implementation rewritten to plan all sub-waypoints upfront from FK seed, chain IK seeds, use convergence-based wait, and active-hold the final pose against droop.
- **Real hardware control** via LeRobot v0.4 SDK — SO-101 follower arm connects, calibrates, reads joints, moves, grasps
- **PyBullet simulation** with real SO-101 URDF + STL meshes — full pick-and-place verified
- **MCP-to-Claude integration** — Claude Code can call tools on the real robot via `.mcp.json` (uses `sg dialout` for serial permissions)
- **Episode recording** — JSON logs + PNG frames + MP4 video with step overlay
- **LLM reactive loop** (llm_controller/) — observe-think-act cycle with Ollama/mlx backends
- **Docker image** on Docker Hub (`alexhache1221/decras:latest`) for RunPod GPU deployment
- **Teleoperation recording** — `scripts/record_teleop.py` wraps LeRobot SOFollower+SOLeader+LeRobotDataset; produces HF-compatible Parquet+MP4 dataset; stdin controls (Enter=save, r=re-record, q=stop); verified on hardware March 2026
- **Episode replay** — `scripts/replay_teleop.py` reads Parquet and replays joint trajectory on follower at original FPS; `--list`, `--dry-run`, `--episode N` flags
- **Leader arm calibration** — `scripts/calibrate_leader.py`; calibration saved as `decras_leader` in LeRobot cache

### Key Files

```
mcp_server/
  server.py              — MCP entry point, lazy robot init, tool registration, error handling
  config.py              — SIMULATE flag, workspace limits, ports, objects
  robot/lerobot.py       — LeRobot SDK interface (connect, joints, grasp, IK)
  robot/kinematics.py    — placo FK/IK engine (PyBullet DIRECT headless client)
  sim/base.py            — Abstract SimEnvironment (designed for Isaac Sim swap)
  sim/pybullet_env.py    — PyBullet backend
  perception/camera.py   — Webcam capture (USB int device or IP Webcam URL via CAMERA_SOURCE / DECRAS_CAMERA env; degrades to simulated frames when SIMULATE=true)
  perception/detector.py — Color-based object detection
  perception/scene_graph.py — Scene graph builder
  episode.py             — Episode recorder
  history.py             — Position history for go_back
  interaction_log.py     — JSONL interaction logger for fine-tuning data

llm_controller/
  main.py                — Reactive reasoning loop (with interaction logging)
  prompt.py              — System prompt + response parser
  llm.py                 — Ollama/mlx backends
  config.py              — LLM settings
  mcp_client.py          — MCP stdio client

tests/                   — pytest test suite (67 tests)
  test_config.py         — Config validation
  test_history.py        — Position history buffer
  test_episode.py        — Episode recording
  test_perception.py     — Perception pipeline
  test_primitives.py     — Robot primitives (navigation, manipulation, meta)
  test_prompt.py         — Prompt builder + response parser
  test_server_tools.py   — MCP server tool functions
  test_interaction_log.py — Interaction logging
  test_sim.py            — PyBullet simulation (pick-and-place)
  test_record_grid.py    — Calibration grid recorder (save/load, coverage, grid spec)

scripts/
  test_hardware.py       — Interactive hardware test
  test_mcp.py            — Direct MCP primitives test
  calibrate.py           — Camera-to-robot calibration (camera_to_robot_matrix → calibration.json)
  calibrate_leader.py    — Leader arm motor calibration (saves decras_leader.json)
  replay.py              — Legacy JSON episode viewer (LLM traces)
  record_teleop.py       — Teleoperation recording → LeRobotDataset
  replay_teleop.py       — Replay recorded episode on follower hardware
  visualize_trajectory.py — FK over Parquet frames → 3D matplotlib EE path, per-episode colors; --segment --density {low|medium|high} overlays segmenter v2 waypoints + straight-line segments
  segment_trajectory.py  — Segmenter v2 (waypoint-based): direction changes + speed dips + gripper events → one move_to_delta per segment; --density tunes granularity (low~5, medium~13, high~26 primitives on sticks_v2)
  add_demo.py            — Thin CLI that wraps segmenter output + task as a Demo and writes it to the store (decras.imitation.store.ingest_sequence)
  replay_sequence.py     — Replay a segmenter sequence JSON on real hardware: reads starting joints from Parquet, executes via LeRobotInterface (SIMULATE=false baked in); --density / --seq flags

calibration/
  record_grid.py         — Interactive calibration grid recorder (leader+follower teleop, manual xyz input, resume support)

decras/
  imitation/
    retrieval.py         — Demo store schema (Demo, Primitive, DemoMetadata dataclasses, to_dict/from_dict)
    store.py             — Demo store writer: save_demo/load_demo/list_demos/ingest_sequence; deterministic id <dataset>_ep<NNN>_<density>

demos/                   — Demo store (one JSON per ingested segmenter output)

datasets/
  sticks_v1/             — 5 teleop episodes, task: "pick stick and place at target"
  sticks_v2/             — 1 teleop episode, task: "pick stick and place at target"
                           sequences/episode_000.json — segmenter output (already run)
  sticks_debug/          — 1 teleop episode (debug recording)
                           sequences/episode_000.json — segmenter output (already run)

.mcp.json                — Claude Code MCP server config (sg dialout wrapper)
```

### Known Limitations

- **placo FK/IK `.pos` suffix bug fixed (April 2026)** — `joints_to_cartesian()` and `cartesian_to_joints()` silently ignored input joint angles due to key name mismatch (`.pos` suffix from LeRobot). Fixed via `_normalize_joint_dict()`. FK/IK now produces correct results, validated with 10cm XY square on hardware. Remaining concern: IK still changes wrist_flex during EE-space moves → Z drop when moving in X.
- **`move_cartesian_delta` rewritten (April 2026)** — was reading mid-motion `get_observation()` between sub-steps and using a fast inner interpolation (200ms) the servo couldn't track. Both bugs caused 30-50% reach. New implementation plans waypoints upfront from FK seed, chains IK seeds, uses convergence-based wait + active-hold. Reach now 80-95% on horizontal/down moves.
- **Gravity sag — the real blocker for replay fidelity** — Extended-arm segments (especially post-release retreat) drift significantly due to servo torque insufficient to hold the arm against gravity. Causes ~2-5cm position error accumulating across 19-49 primitives. Z-up moves reach only 25-50% of commanded distance. Gravity compensation (empirical Z overshoot or feed-forward torque) is the next hardware task before Phase 6D recording.
- **Gripper recording fidelity** — sticks_v3 gripper range is 0.7-17.1/100 (barely moves). Meaningful dgripper replay requires recordings with deliberate full open/close cycles. Record 6D demos with exaggerated gripper motion.
- Camera pipeline live-tested with IP Webcam on phone (April 2026): 1920×1080 frames from `http://192.168.129.1:8080/video`. Detector runs end-to-end. Real-scene detector tuning (HSV ranges for actual lab objects, not demo red cup / blue plate) not yet done.
- Servo convergence under gravity load requires active hold loops (repeated send_joint_positions)
- Only 2 ports: follower on `/dev/ttyACM0`, leader on `/dev/ttyACM1`

## Objective

Build a complete distributed robotics PoC that demonstrates:
1. An LLM can reason about manipulation tasks using high-level tool calls
2. The architecture is modular and swappable (sim/real, different LLMs, different robots)
3. Demonstration data (imitation learning) can be decomposed into primitive sequences
4. Those primitive sequences can be used for fine-tuning the LLM's tool-calling ability

## Completed

### Phase 5A — Code Cleanup & Logging Infrastructure (DONE)

- Moved tests to `tests/` with pytest framework (51 tests across 9 files)
- Cleaned root folder: removed junk files, placeholder code, redundant configs
- Trimmed `.gitignore` from 208 lines of generic template to project-relevant rules
- Added `_safe_tool` decorator for consistent error handling across all 12 MCP tools
- Fixed silent error swallowing in `lerobot.py` grasp handler
- Built `InteractionLog` — JSONL logger capturing full LLM-to-tool traces with markdown summaries
- Integrated interaction logging into `llm_controller/main.py` reasoning loop
- Run tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest`

### Phase 5B — Hardware Validation & Gripper Fix (DONE)

- Verified gripper convention on real hardware: 0=CLOSED, 100=OPEN (Feetech servo SO-101)
- Fixed `GRIPPER_OPEN`/`GRIPPER_CLOSED` constants in `lerobot.py` (were inverted)
- Fixed `grasp()` force-to-position formula: `grip_pos = 30 - (force/FORCE_LIMIT)*30`
- Added `REST_POSITION` and `WORK_POSITION` dicts to `config.py` (hardware-verified angles)
- WORK_POSITION: pan=-18, lift=-60, elbow=37, wrist_flex=74 (gentle working pose)
- Validated full cycle on real hardware: move to work → grasp → release → rest

### Phase 5C — Composable Primitives (DONE)

All 8 motion primitives hardware-validated (March 2026):
- `move_left(distance_m)` / `move_right(distance_m)` — EE-space ±Y via FK+IK ✓
- `move_up(distance_m)` / `move_down(distance_m)` — EE-space ±Z via FK+IK ✓
- `move_forward(distance_m)` / `move_back(distance_m)` — EE-space ±X via FK+IK ✓
- `rotate_gripper(degrees)` — wrist_roll joint-space, positive=CW ✓
- `tilt_gripper(degrees)` — wrist_flex joint-space, positive=up ✓
- Sign map all +1 (verified empirically): hw degrees passed directly to URDF, no inversion
- WORK_POSITION FK: EE at ~[0.194, 0.050, 0.126]m
- `kinematics.py` uses PyBullet DIRECT headless client (FK + IK)
- `pybullet_env.py` passes physicsClientId to all API calls (multi-client isolation)
- Removed `primitives/` subpackage (was pure passthrough); all tools call robot directly
- 55 tests passing

## Next Steps

### Phase 6 — Imitation Learning Pipeline (CURRENT)

**Teleoperation recording (DONE)**:
- `scripts/record_teleop.py` — wires LeRobot's `SOFollower` + `SOLeader` + `LeRobotDataset`
- Produces HuggingFace-compatible dataset (Parquet + MP4) at a local path
- Keyboard controls: RightArrow=save episode, LeftArrow=re-record, Esc=stop
- Optional OpenCV camera via `--camera-index`; `--resume` to continue existing dataset
- Run: `uv run python -m scripts.record_teleop --task "..." --episodes 10 --out datasets/pick_cube`

**Trajectory tooling (DONE)**:
- `scripts/visualize_trajectory.py` — FK over all Parquet frames → 3D matplotlib EE path, one color per episode, grasp/release markers. `--segment --density {low|medium|high}` overlays segmenter v2 output (waypoints + straight-line segments) on top of the raw trajectory.
- `scripts/segment_trajectory.py` — **Segmenter v2 (waypoint-based)**: detects direction changes (windowed velocity-angle), speed dips (local minima below fraction of v_max), and gripper events; emits one `move_to_delta(dx, dy, dz)` per segment plus `grasp()`/`release()` at gripper events. `--density low|medium|high` tunes angle threshold / dip ratio / min segment distance. On sticks_v2 ep 0: 7 primitives at low vs 26 at high (v1 baseline was 19 staircase primitives).

**Demo store schema (DONE)**:
- `decras/imitation/retrieval.py` — `Demo`, `Primitive`, `DemoMetadata` dataclasses
- JSON format: `{ task, primitives: [{tool, args, timestamp}], metadata: {dataset, episode} }`

**Phase 6A — move_to_delta + Segmenter v2 (DONE)**:
- ~~Add `move_to_delta(dx, dy, dz)` primitive~~ — DONE
- ~~Refactor axis-aligned primitives as aliases~~ — DONE
- ~~Rewrite segmenter: waypoint-based~~ — DONE
- ~~Test Zero: replay segmenter v2 output on hardware~~ — **DONE 2026-05-17**: sticks_v3 ep0, structure correct, gravity sag the remaining known issue
- **5D delta** (`dx,dy,dz,dtheta,dgripper`) — DONE: `move_to_delta` and `move_cartesian_delta` extended; segmenter computes wrist_roll and gripper deltas per segment, no more separate `grasp()`/`release()` primitives in sequence output
- **Segmenter param overrides** — DONE: `--angle`, `--dip`, `--min-dist` CLI flags for fine-grained density beyond low/medium/high presets; custom sequences named `episode_NNN_aA_dD_mM.json`
- **`scripts/replay_sequence.py`** — DONE: reads first-frame joints from Parquet for correct start position, replays sequence via `LeRobotInterface` directly (`SIMULATE=false` baked in), supports `--density` and `--seq` for custom files

**Phase 6B — Full Loop (NEXT)**:
- ~~Camera setup (IP Webcam on phone) + wire into perception pipeline~~ — DONE (phone MJPEG stream, `DECRAS_CAMERA` env var, live-tested)
- LLM observe-think-act loop end-to-end on real hardware
- Analyze LLM failure modes
- First RAG experiment: inject demo sequence as few-shot example

**Phase 6C — Demo Store (DONE, retriever/RAG superseded)**:
- ~~Demo store schema~~ — DONE (retrieval.py dataclasses)
- ~~Demo store writer~~ — DONE (`decras.imitation.store`, CLI at `scripts/add_demo.py`, `demos/` at project root)
- Retriever / RAG / fine-tuning items moved to Phase 6F (over discovered codes, not raw `move_to_delta` sequences). See `EMERGENT_ROBOTICS_PLAN.md` and ARCHITECTURE.md decisions #8 and #9.

**Phase 6D — Data Collection for Vocabulary Discovery (NEXT)**:
- Recorder upgrades: gripper force (or skip), camera frames at 5Hz wired into Parquet
- 30+ teleop demos across 2-3 task types with deliberately varied starting positions
- **Gate**: Test Zero (6A.3) must pass first — delta replay reliability is a prerequisite for the conditioned policy in 6E

**Phase 6E — Action VQ-VAE**:
- ~300 LOC PyTorch on `decras/imitation/vqvae.py`. K=8 first, try 12 and 16
- Validate vocabulary: codebook usage, per-code member visualization, encode all demos to code sequences
- Self-supervised — no labels, no rewards

**Phase 6F — Conditioned Policy + LLM Grounding + RAG-over-codes**:
- `decras/imitation/policy.py`: small MLP/GRU, BC on (state, gripper, code) → (delta, gripper_action)
- LLM names each code by reading before/after scene graphs of all its members
- New MCP tool: `execute_code(code: int)` runs the policy at 50Hz; `move_to_delta` stays for debug/fallback
- RAG over codes: retrieve `(task, scene_features) → code_sequence` from past runs, inject as few-shot. Cold-start by encoding the 30 Phase 6D demos.

### Phase 7 — Rotation, JEPA, Memory (FUTURE)

- Extend deltas to (dx, dy, dz, dθ) — retrain VQ-VAE + policy with 4D action space
- JEPA enters: encode (delta_sequence, latent_state_transition) pairs so vocabulary is grounded in *what the world does*
- Persistent memory across sessions, task decomposition, error recovery
- Optional fine-tuning if RAG hits a ceiling

---

## Architectural Debt

### Refactor `scripts/` into a proper library (tracked, do later)

All the tooling currently living in `scripts/` (visualize_trajectory, segment_trajectory,
record_teleop, replay_teleop, calibrate*, etc.) is growing into a real library. These are
not throwaway scripts — they form the imitation learning pipeline.

Planned structure (do not rush this — wait until Phase 6 is stable):
```
decras/
  imitation/
    trajectory.py     — FK-over-parquet, EE computation, smoothing
    segmenter.py      — greedy direction-change segmentation
    visualizer.py     — 3D EE plot
    retrieval.py      — demo store + RAG retrieval
  recording/
    teleop.py         — record_teleop logic (currently scripts/record_teleop.py)
    replay.py         — replay_teleop logic
  calibration/
    ...
```
Scripts become thin CLI entry points that import from `decras.*`.
