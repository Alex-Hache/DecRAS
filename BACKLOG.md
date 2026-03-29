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

## Phase 6 — Imitation Learning Pipeline (CURRENT)

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

- [ ] **Design demo store schema** — Decide: how do you store a decomposed demo? Proposal: one JSON file per episode, containing `{ task: str, primitives: [{ tool: str, args: dict, timestamp: float }], metadata: { dataset: str, episode: int } }`. Write this down as a docstring or small spec.
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
- [ ] Fix placo IK orientation preservation (wrist_flex drift during EE moves)
- [ ] Add min-jerk interpolation to primitive execution (smoother trajectories)

---

## Quick Reference: Labels

| Label | Meaning |
|-------|---------|
| `claude-code` | Can be done entirely by Claude Code from a GitHub Issue |
| `hardware` | Requires physical robot access |
| `independent` | No dependencies — can do anytime |
| `research` | Requires thinking/design, not just coding |
