# Making Language Emerge from Robot Interaction

## A Distributed Architecture That Challenges Monolithic VLA Models

---

## The Problem We're Solving

The dominant approach in robot learning today is the Vision-Language-Action model: one massive neural network that takes in camera images, understands language instructions, and outputs motor commands. RT-2, π₀, GR00T — they all follow this pattern. They work, but they have fundamental limitations.

They need enormous demonstration datasets — hundreds of thousands of trajectories for a single task domain. They're black boxes — when the robot fails, you can't diagnose why. They can't generalize beyond their training distribution without retraining the entire model. They're too large to run on edge hardware. And critically, they fuse perception, reasoning, and control into a single monolith, which means improving any one capability requires retraining everything.

We believe there's a better way: **distribute the intelligence across specialized components that communicate through a shared vocabulary — and let that vocabulary emerge from data rather than designing it by hand.**

---

## How We Got Here: The Decision Journey

This architecture wasn't designed top-down. It was discovered through a series of proposals, challenges, and rejections. Each section below represents a real design decision, what motivated it, and what killed the alternatives.

### Attempt 1: JEPA + LLM + MPPI

The first proposal was mathematically elegant. A JEPA world model produces latent state representations. An LLM provides a nominal trajectory as a sequence of waypoints. An MPPI (Model Predictive Path Integral) controller optimizes around that trajectory using rollouts through the JEPA latent space, minimizing a cost function with weights Q and R that the LLM tunes based on task context.

**What killed it:** The JEPA latent space has no metric structure. JEPA training (energy-based, self-supervised) guarantees that f(z_t, u_t) ≈ z_{t+1} — predictive consistency — but NOT that distances between latent points correspond to anything physically meaningful. The cost function J = Σ(z - z_goal)ᵀQ(z - z_goal) assumes Euclidean distance in latent space is a valid cost. It isn't. The optimizer would score physically different trajectories as nearly equivalent, producing unstable or nonsensical behavior.

**What survived:** The idea of three specialized components communicating through defined interfaces. The JEPA as a predictor. The LLM as a planner. But the interfaces and the optimization approach had to change completely.

### Attempt 2: Add a Learned Outcome Critic

To fix the latent metric problem, we proposed training a critic head on top of the JEPA: g(z_trajectory, task) → success_probability. This replaces the hand-designed cost function with a learned one. The critic absorbs the complexity that Q, R, and λ were trying to encode.

**What killed it:** The critic is an RL problem. Training a function that predicts task success from latent trajectories across diverse tasks requires exactly the kind of massive data collection and reward engineering that we're trying to avoid. We'd be solving a hard RL problem to avoid solving a hard end-to-end learning problem. The dependency is the same; only the form changes.

**What survived:** The recognition that we need some way to evaluate whether the robot is doing the right thing — but it should be reactive (observe and correct) rather than predictive (score and optimize).

### Attempt 3: High-Frequency Reactive Loop

Drop trajectory optimization entirely. Drop the critic. Drop multi-horizon rollouts. Instead: the LLM observes the scene, picks one primitive action, observes the result, picks the next. Intelligence emerges from fast closed-loop reasoning, not from trajectory planning.

The analogy: a human catching a ball doesn't run an outcome critic. They reach, observe, adjust, reach, observe, adjust, at high frequency.

**What survived:** The reactive loop as the core interaction pattern. This became a load-bearing architectural decision — it simplified everything downstream and removed the need for components that were too expensive to build or train.

**New problem surfaced:** What should the primitives be?

### The Primitive Vocabulary Problem

We explored multiple options for how the LLM should express intent to the robot.

**Fixed axis-relative commands (move_left, move_right, up, down + distance):** Simple, unambiguous, the MCP server can execute them immediately. But demonstrations don't decompose cleanly into axis-aligned steps — a smooth curve becomes a jerky sequence of micro-steps. And rotation is completely unaddressed. This gives you a working demo but not a learning system.

**Object-relative primitives (move_toward(cup), move_above(plate)):** The parser becomes trivial — detect which object the gripper is approaching. Demonstrations decompose naturally. But the vocabulary is hand-designed and might not match what the robot actually needs. And it requires accurate perception to resolve object references.

**Cloudflare-style natural language intent (plan(intent="reach above cup carefully")):** Inspired by how Cloudflare reduced 2,500 API endpoints to 2 tools. Flexible and extensible. But requires an intent parser that maps natural language to motor behavior — which is either a massive if/elif tree or a physics sandbox, both of which are too expensive to build and maintain.

**Physics sandbox to resolve intent into trajectories:** A lightweight simulation that takes structured params and produces collision-free waypoints. Solves the parsing problem elegantly. But it doesn't generalize, is expensive to build accurately, and adds a component that needs to match the real workspace.

**What killed all of them:** They all share the same flaw — the vocabulary is designed by a human engineer, whether that engineer is writing primitive names, intent schemas, or simulation constraints. The robot's actual behavioral structure might not match the engineer's intuitions. And any hand-designed vocabulary creates a ceiling on what the system can learn.

### The Breakthrough: Delta Primitives and Emergent Vocabulary

The key insight came from a practical decision. We switched to `move_to_delta(dx, dy, dz)` — relative displacement commands — because the robot has no world representation, so absolute coordinates don't make sense at the actuator level.

This solved the parser problem completely: `delta = position[t+1] - position[t]`. Just subtraction. Works at any frequency. No segmentation heuristics, no intent detection.

But it surfaced the deeper question: if we have long sequences of micro-deltas from demonstrations, can we discover the vocabulary from the data instead of designing it?

**The answer is yes, and this is the core thesis of the project.**

### The Final Architecture: Three Layers of Learned Abstraction

The system has three layers, each speaking its natural language. The interfaces between them are learned, not designed.

**Layer 1 — Conditioned Policy (runs at 50-100Hz on the robot):**
Takes the current robot state and a latent intent code. Produces the next delta. Handles real-time motor execution, adapts to the current physical situation. This is behavioral cloning conditioned on intent — a small, fast network.

**Layer 2 — Action Structure Model (self-supervised, like JEPA but for actions):**
Trained on delta sequences from demonstrations. Learns to segment action streams into meaningful chunks and encode each chunk into a discrete latent code (via VQ-VAE). The codebook that emerges IS the vocabulary. It's not designed — it's discovered from the statistical structure of real motor behavior. This is analogous to how JEPA discovers structure in visual observations, but applied to the action space.

**Layer 3 — LLM Planner (runs at 0.5-2Hz, remote or on Jetson):**
Plans sequences of latent codes. Doesn't know what the codes mean internally — the grounding comes from observing scene graph outcomes. The LLM names the codes ("code 3 always results in the gripper moving above an object → I'll call this 'approach'") and reasons about sequencing them to achieve tasks.

```
Layer 3: LLM
  "approach → descend → grasp → lift → transit → lower → release"
  │  Speaks: natural language, reasons about task structure
  │  Grounds: by observing scene outcomes of each code
  │
  ▼  latent codes (discrete vocabulary)
Layer 2: Action VQ-VAE
  │  Speaks: discrete latent codes
  │  Learns: self-supervised segmentation + encoding of delta sequences
  │  Discovers: the vocabulary from data
  │
  ▼  (current_state, latent_code) pairs
Layer 1: Conditioned Policy  
  │  Speaks: deltas (dx, dy, dz) at 50-100Hz
  │  Adapts: same intent code → different deltas depending on current state
  │
  ▼  motor commands
Robot
```

### Why This Challenges VLAs

A VLA is one giant function: pixels → actions. This architecture is three smaller functions composed: actions → structure (Layer 2), structure + state → actions (Layer 1), structure → plan (Layer 3).

The VLA needs massive data because it learns everything implicitly. This architecture separates structure discovery from control from reasoning, so each component needs less data and can be improved independently.

The VLA is a black box. This architecture has interpretable interfaces — you can inspect the discovered vocabulary, read the LLM's reasoning, visualize what each latent code does.

The VLA must be retrained for new tasks. This architecture adapts by re-sequencing existing codes — the LLM reasons about new compositions of known behaviors.

The VLA requires massive compute at every control step. This architecture runs a tiny policy at 100Hz and only invokes the LLM at 1-2Hz for planning.

---

## Current State

### What Works

- **LeRobot SO-101**: assembled, calibrated, teleoperation functional with leader-follower setup
- **FK/IK**: `.pos` suffix bug identified and fixed (April 2026), placo FK/IK validated on hardware with 10cm XY square
- **`move_to_delta(dx, dy, dz)`**: hardware-validated April 2026 (80-95% reach on horizontal/down moves, 6mm gravity-sag floor). Plans waypoints upfront from FK seed, chains IK seeds, active-holds final pose.
- **Segmenter v2** (waypoint-based): direction changes + speed dips + gripper events → `move_to_delta` sequence; `--density low|medium|high` knob; visualizer overlays segments on raw EE path
- **Demo store** (`decras/imitation/store.py`): segmenter output + task → JSON in `demos/`, with provenance (git sha, source path, created_at). CLI: `scripts/add_demo.py`. Schema: `Demo`, `Primitive`, `DemoMetadata`.
- **Teleop recording**: `scripts/record_teleop.py` produces LeRobotDataset Parquet+MP4 (currently 7 episodes across `sticks_v1/v2/debug`)
- **MCP server**: 21 tools registered, lazy robot init, `_safe_tool` error handling, `sg dialout` wrapper for serial
- **IP Webcam camera**: phone MJPEG stream wired into perception pipeline (`DECRAS_CAMERA` env var, live-tested at 1920×1080)
- **LLM reactive loop**: `llm_controller/main.py` observe-think-act with Ollama/mlx backends, JSONL interaction logger

### What's Next To Build

The project proceeds in four phases, each producing a concrete, testable deliverable.

---

## Phase 1: Data Collection (Week 1-2)

### Goal
Record 30+ demonstrations with sufficient variety to discover meaningful action structure.

### What to Record
- **Tasks**: pick-and-place with 2-3 objects. Vary the task (cup to plate, block to stack, object to bin).
- **Variation**: Change object positions between demonstrations. Change starting arm position. Approach from different angles. This diversity is critical — if every "approach" starts from home position, the conditioned policy won't generalize.
- **Frequency**: 30Hz. Each timestep records joint angles, gripper state (open/closed/force), and the computed delta from the previous timestep.
- **Scene snapshots**: Record camera frames at 5Hz (every 6th control frame) for later JEPA training and scene graph annotation.

### Data Format
```json
{
  "demo_id": "demo_017",
  "task": "pick_cup_place_on_plate",
  "frequency_hz": 30,
  "steps": [
    {
      "t": 0.000,
      "joint_angles": [512, 340, 670, 510, 500],
      "delta": [0.0, 0.0, 0.0],
      "gripper": {"state": "open", "force": 0.0},
      "has_scene_snapshot": true
    },
    {
      "t": 0.033,
      "joint_angles": [514, 339, 668, 510, 500],
      "delta": [0.003, -0.001, -0.002],
      "gripper": {"state": "open", "force": 0.0},
      "has_scene_snapshot": false
    }
  ]
}
```

### Deliverable
A `demos/` directory with 30+ JSON files. Each demo is 3-8 seconds of teleoperation, producing 90-240 timesteps. Total dataset: ~5,000+ timesteps across all demonstrations.

### Why 30 Demonstrations
With gripper events as segment boundaries, each pick-and-place demo produces roughly 6-8 segments (approach, descend, grasp, lift, transit, descend, place, retreat). 30 demos × 7 segments = ~210 segments. For a codebook of size 8-12, that's ~20 examples per code. Tight, but self-supervised methods like VQ-VAE can learn meaningful structure from this amount of data in a low-dimensional action space (3D deltas).

---

## Phase 2: Structure Discovery (Week 3-4)

### Goal
Train a self-supervised model that discovers the segmentation and vocabulary from the collected delta sequences.

### Step 2a: Baseline Segmentation
Before training anything learned, establish a baseline using the two unambiguous signals:
- **Gripper events**: every open→close and close→open is a hard boundary
- **Velocity near-zero**: when ||delta|| < threshold for N consecutive frames, that's a pause/boundary

This gives you segments to analyze even before training the VQ-VAE. Examine them manually. Do they correspond to meaningful behaviors? How many distinct "types" of segments can you identify visually? This tells you what codebook size to target.

### Step 2b: Action VQ-VAE
Train a Vector Quantized Variational Autoencoder on the delta segments.

**Architecture:**
- **Encoder**: 1D CNN or small GRU that takes a variable-length delta sequence and outputs a fixed-size vector
- **Quantizer**: maps the encoder output to the nearest code in a learnable codebook of size K (start with K=8, try K=12 and K=16)
- **Decoder**: takes the quantized code and reconstructs the original delta sequence

**Training objective**: reconstruction loss (can the decoder reproduce the original deltas from just the code?) plus the VQ commitment loss (standard VQ-VAE training). Self-supervised — no labels, no rewards, no task descriptions.

**What to look for**: after training, examine the codebook usage. Are all K codes used, or do some go dead? Do similar behaviors (all "lift" segments) map to the same code? Do different behaviors (lift vs transit) map to different codes? If yes, the model has discovered meaningful structure.

### Step 2c: Validate Discovered Vocabulary
For each code in the codebook, collect all segments that map to it. Visualize them: plot the delta trajectories overlaid. They should look similar — same general direction, similar speed profile, similar duration. If a single code contains wildly different behaviors, increase K. If multiple codes contain the same behavior, decrease K.

### Deliverable
A trained VQ-VAE with a codebook of size K (probably 8-12). A mapping from every segment in the dataset to its code. Visual evidence that the codes correspond to distinct, meaningful motor behaviors.

---

## Phase 3: Conditioned Policy (Week 5-6)

### Goal
Train a small network that can execute any discovered code from any starting state.

### The Problem This Solves
The VQ-VAE tells you that "code 3 is a lift behavior." But if you try to execute it by replaying a recorded lift trajectory, it only works from the exact starting position of that recording. The conditioned policy generalizes: given code 3 and ANY current arm state, produce the right deltas to achieve a lift.

### Architecture
A small MLP or GRU:
- **Input**: current joint angles (5 DOF) + current gripper state + latent code (one-hot or embedding of size K)
- **Output**: next delta (dx, dy, dz) + gripper action (open/close/hold)
- **Training**: behavioral cloning on the demonstration data. For each timestep in each segment, the training tuple is (joint_angles_t, gripper_t, segment_code) → (delta_t, gripper_action_t).

### Why This Is Not a VLA
It looks superficially similar — a neural network outputting motor commands. But the critical difference: this network is tiny (thousands of parameters, not billions), it's conditioned on a discrete intent code (not raw language), and it operates in a factored action space (deltas, not joint torques). The intelligence is in the code selection (Layer 3, the LLM), not in the policy network.

### Testing Protocol
1. Record a new demonstration (not in the training set)
2. Segment it and encode each segment to its VQ code
3. For each segment, execute the conditioned policy from the segment's starting state with the segment's code
4. Compare: does the policy reproduce the demonstration behavior?
5. Crucially: execute the same code from a DIFFERENT starting state. Does it generalize?

### Deliverable
A conditioned policy that can execute any of the K discovered behaviors from arbitrary starting positions within the workspace. Validated on held-out demonstrations and on novel starting positions.

---

## Phase 4: LLM Grounding and Planning (Week 7-8)

### Goal
Connect the LLM to the discovered vocabulary so it can plan and reason about robot behavior.

### Step 4a: Ground the Codes
For each code in the vocabulary, collect the scene graph snapshots from before and after execution of all segments with that code. Feed these to the LLM:

```
"When the robot executes code 3:
 - Before: gripper near object, open, at height ~0.05m above table
 - After: gripper at same XY position, closed, at height ~0.05m
 - Duration: ~0.3 seconds
 - This occurs in 28 out of 30 demonstrations
 What behavior is this?"
```

The LLM names it: "grasp." Now code 3 = "grasp" in the LLM's vocabulary.

### Step 4b: Plan with Vocabulary
The LLM receives a task instruction and a scene graph. It outputs a sequence of vocabulary words:

```
Task: "Pick up the red block and stack it on the blue block"
Scene: {red_block: (0.25, 0.1, 0.05), blue_block: (0.35, -0.05, 0.05), 
        gripper: (0.0, 0.2, 0.15)}

LLM plan: approach → descend → grasp → lift → transit → descend → release → retreat
```

The MCP server maps each word back to its codebook index, feeds the code + current state to the conditioned policy, and executes at 50Hz.

### Step 4c: Reactive Replanning
After each code execution, the MCP server captures a new scene graph and sends it to the LLM. The LLM verifies the outcome matches expectations and decides the next code. If something went wrong ("grasp resulted in no force feedback → object missed"), the LLM re-plans.

This is the reactive loop from Attempt 3, but now operating over a learned vocabulary instead of hand-designed primitives.

### Step 4d: RAG over Discovered Codes
Once the LLM is grounded, every successful run produces a `(task, scene_features, code_sequence)` tuple stored in the demo store. New tasks retrieve the K nearest past runs (cosine similarity over task embedding + scene-graph features: object positions, gripper state, starting EE pose) and inject them as few-shot examples in the prompt.

This is RAG, but over the *discovered vocabulary* rather than raw deltas:
- Cheap: code sequences are short token IDs, not 200-frame arrays
- Self-improving: every run adds an entry, no retraining needed
- Cold-start: bootstrap by encoding the original 30 demos through the trained VQ-VAE on day one
- Scene-aware retrieval matters more than task-string matching — "pick from far-left" should retrieve differently from "pick from center"

The existing demo store schema (`decras/imitation/store.py`) is reused. A `Primitive` becomes `{code: int, name: str}` instead of `{tool: "move_to_delta", args: {...}}`.

### Deliverable
An end-to-end demonstration: human gives a task in natural language → LLM plans a code sequence → MCP server executes via conditioned policy → robot completes the task. With reactive replanning on failure.

---

## Hardware and Infrastructure

### What We Have
| Component | Status |
|-----------|--------|
| MacBook M4 24GB | Primary compute — LLM (mlx-lm), VQ-VAE training, MCP server |
| LeRobot SO-101 (follower) | Assembled, calibrated, FK/IK validated |
| LeRobot SO-101 (leader) | Assembled, calibrated, teleoperation working |
| Samsung A23 phone | Camera via IP Webcam app (setup pending) |
| 2x Raspberry Pi | Parked for future distributed deployment |

### What We Need
| Item | Cost | When |
|------|------|------|
| Phone gooseneck mount | ~€10 | Phase 1 (data collection benefits from camera) |
| ArUco markers (print) | €0 | Phase 1 |
| Test objects (cups, blocks) | ~€5 | Phase 1 |
| Jetson Orin Nano | ~€250 | Phase 4+ (for on-robot inference) |

### Software Stack
- **Python 3.10+**, numpy, scipy, OpenCV
- **PyTorch** (for VQ-VAE and conditioned policy training)
- **MCP Python SDK** (for MCP server)
- **mlx-lm or ollama** (for local LLM inference)
- **LeRobot** (robot control)

---

## Open Questions (Honest Uncertainties)

### Will 30 demonstrations be enough?
We need ~210 segments for a codebook of size 8-12. Self-supervised methods in low-dimensional spaces can work with this, but it's tight. Mitigation: start with 30, examine codebook quality, record more if codes are noisy or underused. The data collection is cheap — 30 minutes of teleoperation per batch.

### Will the conditioned policy generalize to new positions?
The policy sees (state, code) → delta. If training data lacks diversity in starting positions, the policy overfits to specific state regions. Mitigation: deliberately vary starting positions and object locations across demonstrations. Record some "weird" starts — arm reaching from the far left, from maximum height, etc.

### How do we handle rotation?
Current deltas are (dx, dy, dz) — translation only. The SO-101 has a wrist roll joint that matters for tasks like pouring or inserting. We'll need to extend deltas to (dx, dy, dz, dθ) eventually. This is an extension, not a redesign — the VQ-VAE and conditioned policy handle 4D deltas the same way as 3D. Deferred to after the basic system works.

### What if the discovered vocabulary doesn't match task-useful behaviors?
The VQ-VAE optimizes for reconstruction, not task success. It might discover codes that are statistically common but not semantically useful (e.g., splitting "transit" into "transit-fast" and "transit-slightly-less-fast" instead of distinguishing "approach-from-top" and "approach-from-side"). Mitigation: examine the codebook manually. If it's not useful, add a weak task-aware signal to training — e.g., contrastive loss that pulls same-phase segments together across demonstrations.

### When does JEPA enter the picture?
The JEPA world model was deferred but not abandoned. It enters when we add scene snapshots to the VQ-VAE training. Instead of encoding delta sequences alone, we encode (delta_sequence, latent_state_transition) pairs. This gives the vocabulary grounding in what the world does, not just what the robot does. Two segments with identical deltas but different outcomes (successful grasp vs missed grasp) would get different codes. This is Phase 5 — after the basic system works with action-only codes.

---

## Why This Will Work

This is not a speculative research proposal. Every component uses proven techniques:

- **VQ-VAE** is well-understood and works reliably in low-dimensional spaces. It's been used for action discretization in robotics (VQ-BeT, DAGGER variants).
- **Conditioned behavioral cloning** is the simplest form of policy learning. It works when the conditioning signal (the latent code) is informative — which is exactly what the VQ-VAE is designed to produce.
- **LLM planning over discrete actions** is what every tool-calling LLM already does. We're just making the tool vocabulary data-driven instead of hand-designed.
- **Reactive replanning** is robust to individual execution errors. The system doesn't need perfect control — it needs good-enough control with the ability to detect and correct failures.

The novelty is not in any single component. It's in the composition: **self-supervised vocabulary discovery grounding an LLM planner that drives a conditioned policy through an MCP interface**. Each piece is proven. The architecture is new.

---

## Why This Is Worth Your Weekends

You have a working robot, working teleoperation, a working demo parser, and a working MCP server. The low-level control is validated. The infrastructure is in place.

Phase 1 (data collection) requires no new code — just teleoperation sessions. Phase 2 (VQ-VAE) is ~300 lines of PyTorch. Phase 3 (conditioned policy) is ~200 lines. Phase 4 (LLM grounding) reuses your existing MCP server and LLM setup.

In 8 weeks of evenings and weekends, you can have a system where a language model drives a physical robot through a vocabulary that nobody designed — that emerged from the robot's own experience. That's a demo that no VLA can match, because no VLA discovers its own action language.

And every demonstration you record, every codebook you train, every policy you test — it all compounds. The data from Phase 1 feeds Phase 2. The vocabulary from Phase 2 feeds Phase 3. The grounding from Phase 4 feeds back into better data collection for Phase 1. The system improves itself.

Start recording demonstrations.
