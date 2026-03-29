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
│   (Executor)        │  Deterministic. FK/IK via placo + PyBullet headless.
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
- **Known IK issue**: placo IK changes wrist_flex during EE-space moves → small Z drop
  when moving in X. Orientation not preserved. Not yet fixed.
- **Servo holding**: Under gravity, servos need active hold loops (repeated send_joint_positions)
- **Ports**: follower on `/dev/ttyACM0`, leader on `/dev/ttyACM1`
