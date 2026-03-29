"""Test MCP server primitives with real hardware.

Calls MCP tool functions directly (no stdio transport needed).

Usage:
    SIMULATE=false python -m scripts.test_mcp
    SIMULATE=true  python -m scripts.test_mcp   # sim mode
"""

import json
import os
import sys
import time

# Default to real hardware unless overridden
if "SIMULATE" not in os.environ:
    os.environ["SIMULATE"] = "false"

simulate = os.environ["SIMULATE"].lower() == "true"
print(f"Mode: {'SIMULATION' if simulate else 'REAL HARDWARE'}\n")

# Import the server module — this triggers robot/sim init
from mcp_server import server


def call_tool(name: str, **kwargs) -> dict:
    """Call an MCP tool function by name and return parsed result."""
    fn = getattr(server, name)
    raw = fn(**kwargs)
    result = json.loads(raw)
    print(f"  {name}({kwargs or ''}) -> {json.dumps(result, indent=2)}")
    return result


def pause(msg: str = ""):
    if msg:
        print(f"\n  {msg}")
    input("  Press Enter to continue...")
    print()


def main():
    print("=" * 50)
    print("  DecRAS — MCP Primitives Test")
    print("=" * 50)

    # 1. get_status
    print("\n[1] get_status")
    call_tool("get_status")

    # 2. read_joints
    print("\n[2] read_joints")
    call_tool("read_joints")

    # 3. observe (camera or joint-only)
    print("\n[3] observe")
    call_tool("observe")

    # 4. send_joints — small movement
    if not simulate:
        pause("Next: send_joints — will move shoulder_pan to +10°")
        print("[4] send_joints (shoulder_pan=10)")
        # First read current, then modify one joint
        raw = call_tool("read_joints")
        joints = raw.get("joints", {})
        joints["shoulder_pan"] = joints.get("shoulder_pan", 0.0) + 10.0
        call_tool("send_joints", **joints)
        time.sleep(1)

        print("\n    Reading back:")
        call_tool("read_joints")

        # Return to original
        joints["shoulder_pan"] -= 10.0
        print("\n    Returning shoulder_pan:")
        call_tool("send_joints", **joints)
        time.sleep(1)
    else:
        print("\n[4] send_joints (sim mode)")
        call_tool("send_joints", shoulder_pan=10.0, shoulder_lift=0.0,
                  elbow_flex=0.0, wrist_flex=0.0, wrist_roll=0.0, gripper=0.0)

    # 5. grasp + release
    if not simulate:
        pause("Next: gripper test (grasp + release)")
    print("\n[5] grasp")
    call_tool("grasp", force=3.0)
    time.sleep(1)

    print("\n[6] release")
    call_tool("release")
    time.sleep(0.5)

    # 7. Episode recording
    print("\n[7] start_episode")
    call_tool("start_episode", task="mcp_primitives_test")

    print("\n[8] Tool call during episode (read_joints)")
    call_tool("read_joints")

    print("\n[9] end_episode")
    call_tool("end_episode", success=True, reason="primitives_test_complete")

    # 8. Final status
    print("\n[10] Final get_status")
    call_tool("get_status")

    # 9. Stop (disconnects hardware)
    if not simulate:
        pause("Next: stop (will disconnect robot)")
    print("\n[11] stop")
    call_tool("stop")

    print("\n  All MCP primitives tested successfully!")


if __name__ == "__main__":
    main()
