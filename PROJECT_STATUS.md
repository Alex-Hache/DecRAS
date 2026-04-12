# DecRAS — Project Status & Roadmap

## What is DecRAS?

Distributed Robotics Architecture challenging monolithic VLA models.
The core thesis: split reasoning (LLM) from execution (MCP primitives) from perception (vision pipeline), connected via MCP protocol.

**Stack**: Claude/Ollama (reasoning) + MCP server (motor primitives) + LeRobot SDK (SO-101 hardware) + PyBullet (simulation)

## Current State (April 2026)

### Working

- **MCP server** with 20 tools: `observe`, `move_to`, `grasp`, `release`, `stop`, `go_back`, `get_status`, `calibrate`, `read_joints`, `send_joints`, `start_episode`, `end_episode`, `move_left`, `move_right`, `move_up`, `move_down`, `move_forward`, `move_back`, `rotate_gripper`, `tilt_gripper`
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
  perception/camera.py   — Webcam capture (optional, degrades gracefully)
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

tests/                   — pytest test suite (55 tests)
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
  visualize_trajectory.py — FK over Parquet frames → 3D matplotlib EE path, per-episode colors
  segment_trajectory.py  — Greedy dominant-axis segmenter → MCP primitive sequence JSON

calibration/
  record_grid.py         — Interactive calibration grid recorder (leader+follower teleop, manual xyz input, resume support)

decras/
  imitation/
    retrieval.py         — Demo store schema (Demo, Primitive, DemoMetadata dataclasses)

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
- Camera/perception pipeline not tested on real hardware yet
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

### Phase 5.5 — Fix Motion Control: Joint-Space Lookup (SKIPPED)

Originally planned to replace placo FK/IK with a data-driven lookup table. **Skipped (April 2026)**: the `.pos` suffix bug was the root cause of IK failures — with the fix, placo FK/IK is accurate enough (validated with 10cm XY square on hardware).

### Phase 6 — Imitation Learning Pipeline (CURRENT)

**Teleoperation recording (DONE)**:
- `scripts/record_teleop.py` — wires LeRobot's `SOFollower` + `SOLeader` + `LeRobotDataset`
- Produces HuggingFace-compatible dataset (Parquet + MP4) at a local path
- Keyboard controls: RightArrow=save episode, LeftArrow=re-record, Esc=stop
- Optional OpenCV camera via `--camera-index`; `--resume` to continue existing dataset
- Run: `uv run python -m scripts.record_teleop --task "..." --episodes 10 --out datasets/pick_cube`

**Trajectory tooling (DONE)**:
- `scripts/visualize_trajectory.py` — FK over all Parquet frames → 3D matplotlib EE path, one color per episode, grasp/release markers
- `scripts/segment_trajectory.py` — greedy dominant-axis segmenter → list of MCP primitive calls; detects gripper events (grasp/release) to split phases; outputs JSON

**Demo store schema (DONE)**:
- `decras/imitation/retrieval.py` — `Demo`, `Primitive`, `DemoMetadata` dataclasses
- JSON format: `{ task, primitives: [{tool, args, timestamp}], metadata: {dataset, episode} }`

**Next**:
- Build demo store writer: segmenter JSON + task string → Demo JSON on disk
- Build demo retriever: TF-IDF/sentence-transformer cosine similarity on task descriptions
- RAG: inject retrieved demo sequences into LLM system prompt as few-shot examples
- Fine-tune LLM on (task description → tool call sequence) pairs from demo data

### Phase 7 — Memory & Context

- Persistent memory across sessions (what worked, what failed, object locations)
- Task decomposition: break complex instructions into subtask plans
- Error recovery: if a grasp fails, reason about why and retry with adjusted parameters

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
