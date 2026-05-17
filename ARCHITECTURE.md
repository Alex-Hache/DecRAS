# DecRAS — Architecture & Decision Log

> **Purpose**: This document captures the *why* behind DecRAS — the architectural thesis,
> key decisions made, alternatives rejected, and strategic direction. It complements
> `PROJECT_STATUS.md` (which tracks the *what* — code, tests, features).
>
> When you sit down after a break, read this first. Then check `PROJECT_STATUS.md` for
> implementation state. Then check `BACKLOG.md` for your next 15-minute task.

---

## Core Thesis

DecRAS challenges the dominant monolithic VLA (Vision-Language-Action) model paradigm.
Instead of training one giant end-to-end model, we split the problem:

| Concern     | Component         | Why separate?                                              |
|-------------|-------------------|------------------------------------------------------------|
| Reasoning   | LLM (Claude/Ollama) | LLMs already reason well — don't retrain for robotics    |
| Execution   | MCP server        | Motor primitives are deterministic — don't need learning   |
| Perception  | Vision pipeline   | ArUco + scene graphs give structured, interpretable state  |

The hypothesis: this decomposition gives you modularity (swap any component),
interpretability (every decision is a tool call you can inspect), and data efficiency
(you only fine-tune the LLM's tool-call selection, not a full visuomotor policy).

---

## Architecture Overview

```
┌─────────────────────┐
│   LLM (Planner)     │  "Given this scene graph, which primitive should I call?"
│   Claude / Ollama   │
└────────┬────────────┘
         │ tool calls (MCP protocol)
         ▼
┌─────────────────────┐
│   MCP Server        │  20 tools: move_*, grasp, release, observe, etc.
│   (Executor)        │  Deterministic. Data-driven joint-space lookup + min-jerk.
└────────┬────────────┘
         │ joint commands
         ▼
┌─────────────────────┐
│   Hardware / Sim    │  SO-101 via LeRobot SDK  OR  PyBullet simulation
│                     │  (swappable via SIMULATE flag)
└─────────────────────┘
         ▲
         │ camera frames
┌─────────────────────┐
│   Perception        │  ArUco markers → structured scene graph
│   (planned: phone   │  Output: { object_id: { pos, orientation, type } }
│    via IP Webcam)    │
└─────────────────────┘
```

**Key connector**: MCP protocol. This is what makes the architecture genuinely distributed —
the LLM doesn't need to know about joint angles, and the executor doesn't need to know
about task semantics.

---

## Unified Research Direction (2026-05)

Path A and Path B have been merged. See `EMERGENT_ROBOTICS_PLAN.md` for the full plan.

**Three-layer architecture with learned interfaces:**

1. **Conditioned policy** (50-100Hz): `(state, latent_code) → delta`. Small MLP/GRU trained by behavioral cloning on segmented demos.
2. **Action VQ-VAE** (self-supervised): trained on delta-sequence segments. Codebook (K≈8-12) IS the vocabulary — discovered, not designed.
3. **LLM planner** (0.5-2Hz): emits sequences of latent codes. Names codes by observing scene-graph before/after of each code across demos. Reactive replan after each code execution.

**RAG over discovered codes** replaces RAG over raw demos. Every successful run stores `(task, scene_features, code_sequence)`. Retrieval keyed on task embedding + scene graph (object positions, gripper state, starting EE pose) — not task string alone. Few-shot inject into LLM prompt. Cold-start by encoding the original 30 demos through the VQ-VAE.

**Why this composition:** the VQ-VAE solves the abstraction mismatch — segmentation and vocabulary are co-discovered from the same self-supervised loss. The LLM stays in its strength zone (discrete reasoning over a small symbol set). The conditioned policy absorbs state-dependent execution detail without needing language. RAG compounds with use without retraining.

**Why merged:** Path B's "demo → primitive sequence → fine-tune" assumed hand-designed primitives. Path A's "bottom-up vocabulary discovery" assumed bespoke clustering. The VQ-VAE does both jobs at once, with a proven technique (VQ-BeT, VQ-VAE for action discretization). No need to keep the paths separate.

---

## Key Decisions Made (and Why)

### 1. MPPI Rejected

**What**: Model Predictive Path Integral — a sampling-based MPC method.
**Why rejected**: MPPI requires a cost function defined in a metric space. If we use JEPA
latent representations for planning, those latent spaces don't have guaranteed metric
structure. You can't meaningfully sample trajectories and evaluate costs in a space where
distances aren't meaningful.

### 2. Learned Outcome Critic Rejected

**What**: Train a neural network to evaluate "how good is this state?" and use it to
guide planning.
**Why rejected**: This reframes the problem as RL (you're learning a value function).
The whole point of DecRAS is to avoid end-to-end learning for control. If we need a
learned critic, we've lost the architectural advantage.

### 3. High-Frequency Reactive Loop (Current Design)

**What**: The LLM selects ONE semantic primitive per turn, based on the current scene
graph. No multi-step planning — just reactive selection.
**Why this**: It's the simplest thing that could work. The LLM doesn't need to plan
trajectories; it just needs to answer "given what I see right now, what's the single
best next action?" This maps perfectly to tool-call selection, which LLMs are already
good at.

### 4. Structured Tokenization for Primitive Embedding

**What**: When embedding tool-call sequences (for Path A), use categorical function name
+ raw float concatenation, NOT sentence transformers.
**Why**: Standard sentence transformers encode `move_left(0.05)` and `move_left(0.50)` as
nearly identical embeddings — they weren't trained to care about numeric arguments.
Structured tokenization preserves the numeric precision that matters for motor control.

### 5. ArUco-Based Perception (Not Learned Vision)

**What**: Use ArUco fiducial markers on objects → structured scene graph.
**Why**: Reliable, interpretable, no training needed. The perception problem isn't what
we're researching — the planning/execution decomposition is. ArUco lets us sidestep
vision uncertainty entirely for the PoC. The plan is to use a phone as camera via
IP Webcam app, which avoids USB camera driver headaches on Linux.

### 6. Joint-Space Lookup Table — ABANDONED (resolved 2026-04-12)

**What was proposed**: Replace placo IK with a KNN lookup over a teleoperated calibration
grid (~75 positions, ruler-measured xyz → joint angles).

**Why abandoned**: The root cause of "broken IK on hardware" turned out to be a software
bug, not bad DH parameters. `joints_to_cartesian()` and `cartesian_to_joints()` were
silently defaulting all input joints to 0° because LeRobot returns `"shoulder_pan.pos"`
keys but `kinematics.py` looked up `"shoulder_pan"`. Fix: `_normalize_joint_dict()` in
kinematics.py. Validated on hardware with 10cm XY square. placo IK is now accurate
enough; the lookup table approach would be high effort for marginal gain.

**Residual issue**: position-only IK changes wrist_flex during EE-space moves → small
Z drift when moving in X. Tracked as a known limitation, not a blocker.

### 7. `move_to_delta` as the Canonical EE-Space Primitive (2026-04-19)

**What**: One primitive — `move_to_delta(dx, dy, dz)` — handles all EE-space translation.
Axis-aligned primitives (`move_left`, `move_up`, etc.) are thin aliases that call it with
two zero components. Plans all sub-waypoints upfront from FK seed, chains IK seeds,
uses convergence-based wait + active-hold the final pose against gravity droop.

**Why**: Diagonal moves in a single IK call, no staircase artifacts in segmenter output,
and the prior implementation's two bugs (mid-motion `get_observation()` reads + 200ms
inner interpolation servos couldn't track) are fixed. Hardware-validated: 80-95% reach
on horizontal/down moves, ~6mm gravity-sag floor.

**Known hardware limit**: +Z up moves only reach 25-50% of commanded distance due to
Feetech servo torque insufficient to lift the arm against gravity. Tracked in BACKLOG.

### 8. Emergent Vocabulary via Action VQ-VAE (2026-05)

**What**: Stop hand-designing the LLM's primitive vocabulary. Train a VQ-VAE on delta
sequences from teleop demos. The discrete codebook IS the vocabulary. A conditioned
policy executes any code from any state. The LLM names the codes by observing scene-graph
outcomes and plans by sequencing them.

**Why**: Hand-designed primitives create a ceiling on what the system can learn — the
engineer's intuitions about action granularity may not match the robot's actual behavioral
structure. VQ-VAE is well-understood in low-dim action spaces (VQ-BeT etc.). Self-supervised
on cheap teleop data. Decouples reasoning (LLM) from structure discovery (VQ-VAE) from
control (conditioned policy) — each can be improved independently.

**What this replaces**: the previous plan of "fine-tune the LLM on (task, tool_call_sequence)
pairs over hand-designed primitives." Fine-tuning becomes optional / Phase 7+ if it's even
needed.

### 9. RAG over Discovered Codes (2026-05)

**What**: Retrieve past `(task, scene_features, code_sequence)` tuples by cosine similarity
on task embedding + scene-graph features. Inject the top-K as few-shot in the LLM prompt.

**Why this over fine-tuning**: code sequences are tiny (token IDs), self-improving (every
successful run adds an entry), no retraining loop, and the reactive replan loop corrects
when the retrieved sequence diverges from the current scene. Scene-aware retrieval is what
matters — task-string-only retrieval can't tell "pick from far-left" from "pick from center."

**Cold start**: bootstrap by encoding the original 30 demos through the trained VQ-VAE.
Day one of Phase 4 already has 30 entries.

**Reuses**: existing `decras/imitation/store.py` schema. A `Primitive` becomes
`{code: int, name: str}` instead of `{tool: "move_to_delta", args: {...}}`.

---

## The Fundamental Tension: Abstraction Mismatch

The hardest unsolved problem in DecRAS (and arguably in all of robot learning):

**Primitive vocabulary** (move_left, grasp, etc.) operates at one level of abstraction.
**Demonstration data** (continuous joint trajectories from teleoperation) operates at another.

The segmenter bridges this gap by decomposing continuous trajectories into sequences of
discrete primitives. But the segmentation is lossy — you lose the smooth, coordinated
motion that a human demonstrator produces. This is the core tension:

- Too few primitives → can't express the demonstrations faithfully
- Too many primitives → the LLM can't reason about them effectively
- Wrong primitives → the decomposition is meaningless

Path B accepts this tension and works with it (crude segmentation is fine for a PoC).
Path A tries to resolve it (discover the right vocabulary from data).

---

## Related Prior Work

- **V-JEPA 2-AC (Meta)**: Closest prior work. Uses JEPA for world modeling + action
  conditioning. DecRAS's novel angle: replace continuous robot actions with
  text-embedded tool calls, leveraging the LLM's existing reasoning capabilities.
- **JEPA + Differentiable MPC**: A planning framework explored in our discussions.
  Five-phase implementation plan exists (action round-trip → JEPA latent quality →
  joint training → latent trajectory replay → CEM-based MPC). This connects to Path A.

---

## Hardware Notes

- **Robot**: SO-101 follower arm (Feetech servos), SO-100/101 leader for teleoperation
- **Gripper convention**: 0 = CLOSED, 100 = OPEN (verified on hardware, was previously inverted)
- **FK reference**: WORK_POSITION EE at ~[0.194, 0.050, 0.126]m
- **FK/IK status**: placo FK/IK now works correctly after fixing `.pos` suffix key mismatch
  (April 2026). The prior "broken IK" diagnosis was largely caused by FK always computing
  zero-config, not by incorrect DH parameters. Validated with 10cm XY square trajectory on
  real hardware. Known remaining issue: position-only IK changes wrist_flex during EE moves
  → small Z drift when moving in X. Phase 5.5 (lookup table) scope under review.
- **Motor units**: LeRobot uses raw Feetech STS3215 positions (range 0–4095). Lookup table
  should use whatever units `robot.get_observation()` returns / `robot.send_action()` expects.
- **Servo holding**: Under gravity, servos need active hold loops (repeated send_joint_positions)
- **Ports**: follower on `/dev/ttyACM0`, leader on `/dev/ttyACM1`
- **Camera**: Samsung A23 phone via IP Webcam app (MJPEG over WiFi), not yet set up physically.
  Gooseneck mount needed (~€10). Placement: behind/above robot base, 45-60° down at workspace.
