"""Tests for prompt builder and response parser."""

from llm_controller.prompt import parse_response, build_messages, ParsedAction


class TestParseResponse:
    def test_observe(self):
        text = "Thought: I need to observe the scene first.\nAction: observe()"
        thought, action = parse_response(text)
        assert action is not None
        assert action.name == "observe"
        assert action.arguments == {}

    def test_move_to_positional(self):
        text = "Thought: Move to the red cup.\nAction: move_to(0.19, 0.01, 0.08)"
        thought, action = parse_response(text)
        assert action.name == "move_to"
        assert action.arguments == {"x": 0.19, "y": 0.01, "z": 0.08}

    def test_move_to_with_velocity(self):
        text = 'Thought: Approach slowly.\nAction: move_to(0.1, 0.2, 0.05, velocity="slow")'
        thought, action = parse_response(text)
        assert action.arguments["velocity"] == "slow"
        assert action.arguments["x"] == 0.1

    def test_grasp_with_force(self):
        text = "Thought: Grasp the cup.\nAction: grasp(force=2.5)"
        thought, action = parse_response(text)
        assert action.name == "grasp"
        assert action.arguments["force"] == 2.5

    def test_done(self):
        text = "Thought: The cup is on the plate.\nDONE"
        thought, action = parse_response(text)
        assert action is None
        assert "cup" in thought

    def test_go_back(self):
        text = "Thought: Go back.\nAction: go_back(2)"
        thought, action = parse_response(text)
        assert action.name == "go_back"
        assert action.arguments["steps"] == 2

    def test_release(self):
        text = "Thought: Release.\nAction: release()"
        thought, action = parse_response(text)
        assert action.name == "release"
        assert action.arguments == {}

    def test_unparseable_returns_none(self):
        text = "I don't know what to do."
        thought, action = parse_response(text)
        assert action is None
        assert thought != ""


class TestBuildMessages:
    def test_empty_history(self):
        messages = build_messages("Pick up the cup.", [])
        assert messages[0]["role"] == "system"
        assert "TASK:" in messages[1]["content"]
        assert messages[-1]["content"] == "Begin. What is your first action?"
        assert len(messages) == 3

    def test_with_history(self):
        history = [{
            "thought": "Observing",
            "action_text": "observe()",
            "result": {"status": "observed"},
            "scene": {
                "objects": [],
                "gripper": {"position": [0.2, 0, 0.15], "open": True, "holding": None},
            },
        }]
        messages = build_messages("Pick up the cup.", history)
        assert len(messages) == 4  # system + task + assistant + result
        assert messages[2]["role"] == "assistant"
        assert messages[3]["role"] == "user"

    def test_history_windowing(self):
        history = [
            {
                "thought": f"Step {i}",
                "action_text": "observe()",
                "result": {"status": "ok"},
                "scene": {"objects": [], "gripper": {"position": [0, 0, 0], "open": True, "holding": None}},
            }
            for i in range(10)
        ]
        messages = build_messages("Task", history, window=3)
        # system + task + 3 * (assistant + result) = 8
        assert len(messages) == 8
