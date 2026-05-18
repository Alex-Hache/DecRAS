"""System prompt, prompt builder, and response parser."""

import re
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Workspace reference (meters, robot base frame)
#   +X = forward (away from base), 0–40 cm
#   +Y = left,                     -20 to +20 cm
#   +Z = up,                        0–30 cm
# Typical individual move: 2–12 cm per axis.
# Gripper starts near x=0.19, y=0.05, z=0.11 (WORK position).
# Objects on the table are typically at z=0.03–0.08 m.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a robot controller. You drive a SO-101 robot arm by selecting one action per turn.

COORDINATE FRAME:
  +X = forward (0–0.40 m from base)
  +Y = left    (-0.20 to +0.20 m)
  +Z = up      (0–0.30 m)
  Typical move per step: 2–12 cm (0.02–0.12 m) per axis.
  Objects on the table: z ≈ 0.03–0.08 m.

AVAILABLE ACTIONS:
  observe()                              → get gripper position + detected objects
  move_to_delta(dx, dy, dz)             → move relative to current position (meters)
  grasp(force=3.0)                       → close gripper (force 1–10)
  release()                              → open gripper
  get_status()                           → read joint positions and robot state
  stop()                                 → emergency stop

RULES:
  - Call observe() first to get current gripper position.
  - Use dx/dy/dz to express how far to move — NOT absolute coordinates.
  - One action per turn. After each action you receive the result.
  - Think step by step, keep reasoning to 1–2 sentences.
  - When the task is complete, respond with DONE.

PICK-AND-PLACE STRUCTURE (reference from a real recorded demo):

  Task: pick up the yellow glue stick (~30 cm forward) and move it left.
  Gripper starts at: [0.19, 0.05, 0.11]
  Object detected at: yellow_stick, pos=[0.31, 0.00, 0.02]

  Step 1 — move above the stick (it's ~12 cm forward, 5 cm right of gripper):
    move_to_delta(dx=0.12, dy=-0.05, dz=-0.03)

  Step 2 — descend to grasp height (table level ≈ z=0.02):
    move_to_delta(dx=0.0, dy=0.0, dz=-0.07)

  Step 3 — grasp:
    grasp(force=3.0)

  Step 4 — lift clear of the table:
    move_to_delta(dx=0.0, dy=0.0, dz=0.08)

  Step 5 — carry to target location (left 15 cm):
    move_to_delta(dx=0.0, dy=0.15, dz=0.0)

  Step 6 — release:
    release()

  Step 7 — retreat:
    move_to_delta(dx=-0.05, dy=0.0, dz=0.05)

RESPONSE FORMAT:
  Thought: <brief reasoning, 1–2 sentences>
  Action: <tool_call>
"""

# Pattern matches: tool_name(arg1, arg2, key=val, ...)
ACTION_PATTERN = re.compile(
    r"Action:\s*(\w+)\(([^)]*)\)",
    re.IGNORECASE,
)

DONE_PATTERN = re.compile(r"\bDONE\b", re.IGNORECASE)


@dataclass
class ParsedAction:
    name: str
    arguments: dict


def build_messages(
    task: str,
    history: list[dict],
    window: int = 5,
) -> list[dict[str, str]]:
    """Build the message list for the LLM."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages.append({
        "role": "user",
        "content": f"TASK: {task}",
    })

    recent = history[-window:] if len(history) > window else history
    for entry in recent:
        messages.append({
            "role": "assistant",
            "content": f"Thought: {entry['thought']}\nAction: {entry['action_text']}",
        })
        scene_summary = _summarize_scene(entry.get("scene"))
        messages.append({
            "role": "user",
            "content": (
                f"Result: {json.dumps(entry['result'], indent=1)}\n\n"
                f"Scene: {scene_summary}"
            ),
        })

    if not history:
        messages.append({
            "role": "user",
            "content": "Begin. What is your first action?",
        })

    return messages


def parse_response(text: str) -> tuple[str, "ParsedAction | None"]:
    """Parse the LLM response into thought and action."""
    if DONE_PATTERN.search(text):
        thought = text.split("DONE")[0].strip()
        return thought, None

    thought = ""
    thought_match = re.search(r"Thought:\s*(.+?)(?=\nAction:|\Z)", text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_match = ACTION_PATTERN.search(text)
    if not action_match:
        logger.warning("Failed to parse action from response: %s", text[:200])
        return thought or text.strip(), None

    func_name = action_match.group(1)
    args_str = action_match.group(2).strip()
    arguments = _parse_arguments(func_name, args_str)
    return thought, ParsedAction(name=func_name, arguments=arguments)


def format_retry_prompt() -> dict[str, str]:
    return {
        "role": "user",
        "content": (
            "I couldn't parse your response. Please respond with exactly:\n"
            "Thought: <your reasoning>\n"
            "Action: tool_name(params)\n"
            "Or say DONE if the task is complete."
        ),
    }


def _parse_arguments(func_name: str, args_str: str) -> dict:
    """Parse function arguments from a string like '0.05, -0.03, 0.0'."""
    if not args_str:
        return {}

    positional_args = {
        "move_to_delta": ["dx", "dy", "dz"],
        "move_to":       ["x", "y", "z"],       # legacy — still parsed if LLM uses it
        "grasp":         ["force"],
        "go_back":       ["steps"],
    }

    args = {}
    pos_names = positional_args.get(func_name, [])
    pos_idx = 0

    for part in _split_args(args_str):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, val = part.split("=", 1)
            args[key.strip()] = _coerce_value(val.strip())
        else:
            if pos_idx < len(pos_names):
                args[pos_names[pos_idx]] = _coerce_value(part)
                pos_idx += 1

    return args


def _split_args(s: str) -> list[str]:
    parts, current, in_quotes, quote_char = [], "", False, ""
    for ch in s:
        if ch in ('"', "'") and not in_quotes:
            in_quotes, quote_char = True, ch
        elif ch == quote_char and in_quotes:
            in_quotes = False
        elif ch == "," and not in_quotes:
            parts.append(current)
            current = ""
            continue
        current += ch
    if current:
        parts.append(current)
    return parts


def _coerce_value(s: str):
    s = s.strip().strip("\"'")
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _summarize_scene(scene: dict | None) -> str:
    """Compact scene summary for the prompt."""
    if not scene:
        return "No scene data."

    # Hardware observe() without camera: ee_position + joints
    if "joints" in scene and "objects" not in scene:
        ee = scene.get("ee_position", [])
        open_str = "open" if scene.get("gripper_open") else "closed"
        ee_str = f"[{', '.join(f'{v:.3f}' for v in ee)}]" if ee else "unknown"
        return f"Gripper EE position: {ee_str} m\nGripper state: {open_str}\n(No camera — use EE position for delta planning)"

    parts = []
    for obj in scene.get("objects", []):
        pos = obj["position"]
        status = "grasped" if obj.get("grasped") else "on table"
        parts.append(
            f"  {obj['id']} ({obj['type']}, {obj['color']}): "
            f"pos={pos}, {status}, graspable={obj.get('graspable')}"
        )

    gripper = scene.get("gripper", {})
    g_pos = gripper.get("position", [])
    g_state = "open" if gripper.get("open") else "closed"
    g_holding = gripper.get("holding") or "nothing"

    g_pos_str = f"[{', '.join(f'{v:.3f}' for v in g_pos)}]" if g_pos else str(g_pos)
    objects_text = "\n".join(parts) if parts else "  (none detected — color detector not tuned for this object)"
    return (
        f"Gripper EE position: {g_pos_str} m  |  {g_state}  |  holding={g_holding}\n"
        f"Objects:\n{objects_text}"
    )
