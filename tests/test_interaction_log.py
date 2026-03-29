"""Tests for MCP interaction logging."""

import json

from mcp_server.interaction_log import InteractionLog


def test_basic_session(tmp_path):
    log = InteractionLog(task="Test task", output_dir=tmp_path)

    log.record_turn(
        step=1,
        messages=[{"role": "system", "content": "You are a robot."}],
        llm_response="Thought: Observe.\nAction: observe()",
        thought="Observe.",
        tool_name="observe",
        tool_args={},
        tool_result={"status": "observed", "objects": []},
        llm_latency_ms=100,
        tool_latency_ms=20,
    )

    log.record_turn(
        step=2,
        messages=[{"role": "system", "content": "You are a robot."}],
        llm_response="Thought: Move.\nAction: move_to(0.2, 0.0, 0.1)",
        thought="Move.",
        tool_name="move_to",
        tool_args={"x": 0.2, "y": 0.0, "z": 0.1},
        tool_result={"status": "complete", "final_position": [0.2, 0.0, 0.1]},
        llm_latency_ms=150,
        tool_latency_ms=30,
    )

    result_path = log.finish(success=True, reason="test_complete")

    # Verify JSONL
    assert result_path.exists()
    lines = result_path.read_text().strip().split("\n")
    assert len(lines) == 4  # session_start + 2 turns + session_end

    header = json.loads(lines[0])
    assert header["type"] == "session_start"
    assert header["task"] == "Test task"

    turn1 = json.loads(lines[1])
    assert turn1["type"] == "turn"
    assert turn1["tool_name"] == "observe"
    assert turn1["step"] == 1

    turn2 = json.loads(lines[2])
    assert turn2["tool_args"]["x"] == 0.2

    footer = json.loads(lines[3])
    assert footer["type"] == "session_end"
    assert footer["success"] is True

    # Verify markdown summary exists
    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1
    md_content = md_files[0].read_text()
    assert "SUCCESS" in md_content
    assert "observe" in md_content


def test_parse_failure(tmp_path):
    log = InteractionLog(task="Parse fail test", output_dir=tmp_path)
    log.record_parse_failure(step=1, llm_response="Gibberish output")
    result_path = log.finish(success=False, reason="parse_failures")

    lines = result_path.read_text().strip().split("\n")
    failure = json.loads(lines[1])
    assert failure["type"] == "parse_failure"
    assert "Gibberish" in failure["llm_response"]


def test_empty_session(tmp_path):
    log = InteractionLog(task="Empty", output_dir=tmp_path)
    result_path = log.finish(success=False, reason="no_actions")

    lines = result_path.read_text().strip().split("\n")
    assert len(lines) == 2  # start + end
    footer = json.loads(lines[1])
    assert footer["total_turns"] == 0
