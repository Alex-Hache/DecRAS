"""System prompt, prompt builder, and response parser."""

import re
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a robot controller. You drive a robot arm by selecting one action at a time.

AVAILABLE ACTIONS:
- observe() → get current scene as JSON
- move_to(x, y, z, velocity="normal") → move gripper to position
- grasp(force=3.0) → close gripper
- release() → open gripper
- stop() → emergency stop
- go_back(steps=1) → return to previous position
- get_status() → get current robot state

RULES:
- Always call observe() first to see the current scene.
- Issue exactly ONE action per turn.
- After each action, you will receive the result and updated scene.
- Think step by step but keep reasoning to 1-2 sentences.
- When the task is complete, respond with DONE.
- Use the exact coordinates from the scene graph to move to objects.
- To grasp an object: move_to its position first, then grasp().
- To place an object: move_to the target position, then release().

RESPONSE FORMAT:
Thought: <brief reasoning>
Action: <tool_call>
"""

# Pattern to match action calls like: move_to(0.1, 0.2, 0.3) or observe() or grasp(force=2.5)
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

    # Task instruction
    messages.append({
        "role": "user",
        "content": f"TASK: {task}",
    })

    # Include recent history as alternating user/assistant turns
    recent = history[-window:] if len(history) > window else history
    for entry in recent:
        # Assistant's previous response
        messages.append({
            "role": "assistant",
            "content": f"Thought: {entry['thought']}\nAction: {entry['action_text']}",
        })
        # Result feedback
        scene_summary = _summarize_scene(entry.get("scene"))
        messages.append({
            "role": "user",
            "content": (
                f"Result: {json.dumps(entry['result'], indent=1)}\n\n"
                f"Scene: {scene_summary}"
            ),
        })

    # If no history yet, prompt to start
    if not history:
        messages.append({
            "role": "user",
            "content": "Begin. What is your first action?",
        })

    return messages


def parse_response(text: str) -> tuple[str, ParsedAction | None]:
    """Parse the LLM response into thought and action.

    Returns (thought, action) where action is None if DONE or parse failure.
    """
    # Check for DONE
    if DONE_PATTERN.search(text):
        thought = text.split("DONE")[0].strip()
        return thought, None

    # Extract thought
    thought = ""
    thought_match = re.search(r"Thought:\s*(.+?)(?=\nAction:|\Z)", text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Extract action
    action_match = ACTION_PATTERN.search(text)
    if not action_match:
        logger.warning("Failed to parse action from response: %s", text[:200])
        return thought or text.strip(), None

    func_name = action_match.group(1)
    args_str = action_match.group(2).strip()

    arguments = _parse_arguments(func_name, args_str)
    return thought, ParsedAction(name=func_name, arguments=arguments)


def format_retry_prompt() -> dict[str, str]:
    """Return a prompt to ask the LLM to retry with correct format."""
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
    """Parse function arguments from a string like '0.1, 0.2, 0.3, velocity=\"slow\"'."""
    if not args_str:
        return {}

    # Define positional arg names for each function
    positional_args = {
        "move_to": ["x", "y", "z"],
        "grasp": ["force"],
        "go_back": ["steps"],
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
    """Split argument string by commas, respecting quotes."""
    parts = []
    current = ""
    in_quotes = False
    quote_char = ""

    for ch in s:
        if ch in ('"', "'") and not in_quotes:
            in_quotes = True
            quote_char = ch
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
    """Try to convert a string value to int, float, or strip quotes."""
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
    """Create a compact scene summary for the prompt."""
    if not scene:
        return "No scene data."

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

    objects_text = "\n".join(parts) if parts else "  (no objects detected)"
    return (
        f"Objects:\n{objects_text}\n"
        f"Gripper: pos={g_pos}, {g_state}, holding={g_holding}"
    )
