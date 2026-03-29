"""
DecRAS Daily Pulse — reads BACKLOG.md and generates a status summary.

Used by GitHub Actions to post daily updates and by humans to check status.
"""

import re
import sys
import json
from pathlib import Path


def parse_backlog(backlog_path: str = "BACKLOG.md") -> dict:
    """Parse BACKLOG.md and extract task status."""
    text = Path(backlog_path).read_text(encoding="utf-8")

    # Find all phases
    phases = []
    current_phase = None
    current_section = None

    for line in text.split("\n"):
        # Phase headers: ## Phase X.X — Title (STATUS)
        phase_match = re.match(r"^## (Phase .+?)$", line)
        if phase_match:
            current_phase = {
                "name": phase_match.group(1).strip(),
                "sections": [],
                "tasks": [],
            }
            phases.append(current_phase)
            current_section = None
            continue

        # Section headers: ### X.X.X Title
        section_match = re.match(r"^### (.+?)$", line)
        if section_match and current_phase:
            current_section = section_match.group(1).strip()
            continue

        # Tasks: - [ ] or - [x]
        task_match = re.match(r"^- \[([ xX])\] \*\*(.+?)\*\*(.*)$", line)
        if task_match and current_phase:
            done = task_match.group(1).lower() == "x"
            title = task_match.group(2).strip()
            rest = task_match.group(3).strip()

            # Extract time estimate
            time_match = re.search(r"\*Time\*:\s*(.+?)$", rest)
            time_est = time_match.group(1).strip() if time_match else None

            # Extract tags
            tags = []
            if "`claude-code`" in rest or "`claude-code`" in text.split(title)[1].split("- [ ]")[0] if title in text else "":
                tags.append("claude-code")
            if "`hardware`" in rest:
                tags.append("hardware")

            task = {
                "title": title,
                "done": done,
                "section": current_section,
                "phase": current_phase["name"],
                "time": time_est,
                "tags": tags,
            }
            current_phase["tasks"].append(task)

    return {"phases": phases}


def find_next_task(parsed: dict) -> dict | None:
    """Find the first unchecked task across all phases."""
    for phase in parsed["phases"]:
        for task in phase["tasks"]:
            if not task["done"]:
                return task
    return None


def find_current_phase(parsed: dict) -> dict | None:
    """Find the phase that has incomplete tasks."""
    for phase in parsed["phases"]:
        total = len(phase["tasks"])
        done = sum(1 for t in phase["tasks"] if t["done"])
        if total > 0 and done < total:
            return {**phase, "total": total, "done": done}
    return None


def generate_claude_code_prompt(task: dict, repo: str = "Alex-Hache/DecRAS") -> str:
    """Generate a ready-to-paste Claude Code prompt for a task."""
    return (
        f"Work on {repo}. Read CLAUDE.md for project rules. "
        f"Read BACKLOG.md and implement this task: \"{task['title']}\". "
        f"Read ARCHITECTURE.md for design context. "
        f"Run tests before committing. "
        f"Update BACKLOG.md (check off the task) and PROJECT_STATUS.md per CLAUDE.md rules."
    )


def generate_pulse_comment(parsed: dict) -> str:
    """Generate the markdown comment for the daily pulse issue."""
    phase = find_current_phase(parsed)
    next_task = find_next_task(parsed)

    lines = []
    lines.append(f"## 📊 Daily Pulse — {__import__('datetime').date.today()}")
    lines.append("")

    if phase:
        progress_pct = int((phase["done"] / phase["total"]) * 100)
        bar_filled = int(progress_pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"**Current phase**: {phase['name']}")
        lines.append(f"**Progress**: {bar} {phase['done']}/{phase['total']} tasks ({progress_pct}%)")
        lines.append("")

    if next_task:
        lines.append("---")
        lines.append("")
        lines.append(f"### ⏭️ Next task")
        lines.append(f"**{next_task['title']}**")
        if next_task.get("time"):
            lines.append(f"⏱️ {next_task['time']}")
        if next_task.get("tags"):
            lines.append(f"🏷️ {', '.join(next_task['tags'])}")
        lines.append("")

        if "claude-code" in next_task.get("tags", []):
            lines.append("---")
            lines.append("")
            lines.append("### 🤖 Claude Code prompt (copy-paste ready)")
            lines.append("```")
            lines.append(generate_claude_code_prompt(next_task))
            lines.append("```")
        elif "hardware" in next_task.get("tags", []):
            lines.append("⚠️ This task requires hardware access.")
        lines.append("")
    else:
        lines.append("🎉 **All tasks complete!** Time to plan the next phase.")

    # Summary of all phases
    lines.append("---")
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>📋 Full backlog status</summary>")
    lines.append("")
    for p in parsed["phases"]:
        total = len(p["tasks"])
        if total == 0:
            continue
        done = sum(1 for t in p["tasks"] if t["done"])
        status = "✅" if done == total else "🔄" if done > 0 else "⬜"
        lines.append(f"- {status} **{p['name']}**: {done}/{total}")
    lines.append("")
    lines.append("</details>")

    return "\n".join(lines)


if __name__ == "__main__":
    parsed = parse_backlog()

    if "--json" in sys.argv:
        print(json.dumps(parsed, indent=2))
    elif "--next" in sys.argv:
        task = find_next_task(parsed)
        if task:
            print(f"Next: {task['title']}")
            print(f"Phase: {task['phase']}")
            if task.get("time"):
                print(f"Time: {task['time']}")
            print(f"\nClaude Code prompt:")
            print(generate_claude_code_prompt(task))
        else:
            print("All tasks complete!")
    else:
        print(generate_pulse_comment(parsed))
