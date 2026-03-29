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

## Two Research Paths

### Path B — The 4-Weekend PoC (ACTIVE, CURRENT FOCUS)

**Goal**: Demonstrate the full loop — record demos, decompose into primitives, use them
to improve LLM tool-call selection.

- Object-relative primitives (move_to_object, not move_left 0.05)
- Trivial demo parser (greedy axis segmentation — already built)
- Imitation learning: demo → primitive sequence → fine-tune LLM tool calling
- RAG retrieval: given task description, find similar demo sequences as context

**Why this first**: It proves the thesis end-to-end without requiring research breakthroughs.
If this works, even crudely, it validates the entire architecture.

### Path A — Research Track (FUTURE)

**Goal**: Discover the right primitive vocabulary from data, bottom-up.

- High-frequency axis-relative primitives (the current 20 tools)
- Embed tool-call sequences using structured tokenization
- Bottom-up vocabulary discovery: cluster sequences into higher-level skills
- This is where the JEPA + differentiable MPC work eventually connects

**Why later**: This requires solving the abstraction mismatch problem (see below).
Path B proves the architecture; Path A optimizes it.

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

### 6. No IK — Data-Driven Joint-Space Lookup (CURRENT BLOCKER)

**What**: Replace the placo/PyBullet IK solver with a lookup table built from real
teleoperation data. Teleoperate the arm to a grid of ~75 positions across the workspace,
record (Cartesian_position, joint_angles) pairs. For arbitrary targets, interpolate between
nearest recorded neighbors using KNN + inverse-distance weighting (optionally scipy RBF).

**Why**: The available IK solutions for SO-100/101 have inaccurate DH parameters — the
arm moves to wrong positions. This is inherent to 3D-printed arms where the actual
geometry doesn't match the URDF/DH model precisely. The lookup table bypasses this
entirely: the mapping comes from the physical arm, not a kinematic model.

**Status**: This is the current blocker. The existing 20 MCP primitives (move_left, etc.)
use placo IK via `kinematics.py`, which produces incorrect positions on real hardware.
Until the lookup table replaces this, Cartesian-space primitives are unreliable, and
segmenter output from teleoperation data maps to primitives that don't execute correctly.

**Control pipeline (target architecture)**:
```
MCP plan(skill="move_toward", target="cup")
    → Resolve "cup" → Cartesian position from scene graph
    → JointLookup.solve(target_xyz) → KDTree nearest neighbors
                                    → inverse-distance interpolation
                                    → target joint angles
    → minimum_jerk_joint_trajectory(current, target, duration)
    → TrajectoryExecutor: send joints at 50Hz via robot.send_action()
```

**Calibration grid spec**:
- X: 0.15m–0.35m from base (5 points), Y: ±0.15m (5 points), Z: table to +0.15m (3 heights)
- ~75 positions + 5-10 extra at key locations (home, grasp height)
- Recording: teleoperate with leader arm, record follower joint angles
- Position measurement: manual (ruler) initially, ArUco-based later
- Safety: refuse targets more than ~5cm from any recorded point

### 7. Minimum-Jerk Interpolation in Joint Space

**What**: Deterministic, closed-form trajectory generation. 20 lines of code.
`x(t) = x₀ + (x_f - x₀) × [10(t/T)³ - 15(t/T)⁴ + 6(t/T)⁵]`, applied per-joint.
**Why**: Produces smooth trajectories from coarse waypoints. No learned trajectory
generation needed. Combined with the lookup table, this gives reliable, smooth motion
from any current position to any target in the recorded workspace.

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
- **IK status**: BROKEN. placo IK uses inaccurate DH parameters → arm moves to wrong positions.
  Additionally changes wrist_flex during EE-space moves → Z drop when moving in X.
  Being replaced by data-driven joint-space lookup (see Decision #6).
- **Motor units**: LeRobot uses raw Feetech STS3215 positions (range 0–4095). Lookup table
  should use whatever units `robot.get_observation()` returns / `robot.send_action()` expects.
- **Servo holding**: Under gravity, servos need active hold loops (repeated send_joint_positions)
- **Ports**: follower on `/dev/ttyACM0`, leader on `/dev/ttyACM1`
- **Camera**: Samsung A23 phone via IP Webcam app (MJPEG over WiFi), not yet set up physically.
  Gooseneck mount needed (~€10). Placement: behind/above robot base, 45-60° down at workspace.
