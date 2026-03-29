"""MCP interaction logging — captures full LLM-to-tool traces as JSONL.

Each session produces a JSONL file where every line is one interaction turn.
Schema is designed for fine-tuning: each entry maps to a training example
(system prompt, user context, assistant reasoning + tool call, tool result).

Usage:
    log = InteractionLog(task="Pick up the red cup")
    log.record_turn(
        step=1,
        messages=[...],           # full prompt sent to LLM
        llm_response="Thought: ...\nAction: observe()",
        thought="I need to observe",
        tool_name="observe",
        tool_args={},
        tool_result={"objects": [...]},
        llm_latency_ms=320,
        tool_latency_ms=45,
    )
    log.finish(success=True, reason="task_complete")
"""

import json
import time
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parent.parent / "logs"


class InteractionLog:
    """Captures the full LLM reasoning + tool interaction trace."""

    def __init__(self, task: str = "", output_dir: Path | None = None):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._dir = output_dir or LOGS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self._dir / f"session_{ts}.jsonl"
        self._summary_path = self._dir / f"session_{ts}.md"

        self._task = task
        self._start_time = time.time()
        self._turns: list[dict] = []

        # Write header entry
        self._write_entry({
            "type": "session_start",
            "task": task,
            "timestamp": datetime.now().isoformat(),
        })

    def record_turn(
        self,
        step: int,
        messages: list[dict[str, str]],
        llm_response: str,
        thought: str,
        tool_name: str | None,
        tool_args: dict | None,
        tool_result: dict | None,
        llm_latency_ms: float = 0,
        tool_latency_ms: float = 0,
    ):
        """Record one observe-think-act turn."""
        turn = {
            "type": "turn",
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "messages": messages,
            "llm_response": llm_response,
            "thought": thought,
            "tool_name": tool_name,
            "tool_args": tool_args or {},
            "tool_result": tool_result,
            "llm_latency_ms": round(llm_latency_ms, 1),
            "tool_latency_ms": round(tool_latency_ms, 1),
            "success": tool_result.get("status") != "failed" if tool_result else None,
        }
        self._turns.append(turn)
        self._write_entry(turn)

    def record_parse_failure(self, step: int, llm_response: str):
        """Record a turn where the LLM response couldn't be parsed."""
        entry = {
            "type": "parse_failure",
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "llm_response": llm_response,
        }
        self._turns.append(entry)
        self._write_entry(entry)

    def finish(self, success: bool = False, reason: str = ""):
        """Finalize the session log and write the markdown summary."""
        elapsed = time.time() - self._start_time
        summary = {
            "type": "session_end",
            "task": self._task,
            "success": success,
            "reason": reason,
            "total_turns": len(self._turns),
            "elapsed_seconds": round(elapsed, 2),
            "timestamp": datetime.now().isoformat(),
        }
        self._write_entry(summary)

        # Write human-readable markdown summary
        self._write_markdown_summary(summary)

        logger.info("Interaction log saved: %s (%d turns, %.1fs)",
                     self._jsonl_path, len(self._turns), elapsed)
        return self._jsonl_path

    def _write_entry(self, entry: dict):
        """Append one JSON line to the JSONL file."""
        with open(self._jsonl_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _write_markdown_summary(self, summary: dict):
        """Write a human-readable summary of the session."""
        lines = [
            f"# Session: {self._task}",
            f"",
            f"- **Result**: {'SUCCESS' if summary['success'] else 'FAILED'} — {summary['reason']}",
            f"- **Turns**: {summary['total_turns']}",
            f"- **Duration**: {summary['elapsed_seconds']}s",
            f"- **JSONL**: `{self._jsonl_path.name}`",
            f"",
            f"## Turn-by-turn",
            f"",
        ]

        for turn in self._turns:
            if turn["type"] == "parse_failure":
                lines.append(f"### Step {turn['step']} — PARSE FAILURE")
                lines.append(f"```\n{turn['llm_response'][:200]}\n```")
                lines.append("")
                continue

            if turn["type"] != "turn":
                continue

            status = "?"
            if turn.get("tool_result"):
                status = turn["tool_result"].get("status", "?")

            tool_call = f"{turn['tool_name']}({_format_args(turn['tool_args'])})" if turn['tool_name'] else "DONE"
            lines.append(f"### Step {turn['step']}")
            lines.append(f"- **Thought**: {turn['thought']}")
            lines.append(f"- **Action**: `{tool_call}`")
            lines.append(f"- **Result**: {status}")
            lines.append(f"- **Latency**: LLM {turn['llm_latency_ms']}ms, Tool {turn['tool_latency_ms']}ms")
            lines.append("")

        self._summary_path.write_text("\n".join(lines))


def _format_args(args: dict) -> str:
    if not args:
        return ""
    return ", ".join(f"{k}={v!r}" for k, v in args.items())
