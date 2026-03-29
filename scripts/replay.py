"""Episode replay viewer.

Usage:
    python -m scripts.replay episodes/20260306_213000/
    python -m scripts.replay episodes/20260306_213000/ --video   # just re-encode video
    python -m scripts.replay --latest                            # replay most recent
    python -m scripts.replay --list                              # list all episodes

Without OpenCV GUI (headless/container), prints a step-by-step text replay.
With OpenCV GUI, shows frames in a window.
"""

import json
import sys
import time
from pathlib import Path

EPISODES_DIR = Path(__file__).parent.parent / "episodes"

try:
    import cv2
    HAS_GUI = True
except ImportError:
    HAS_GUI = False


def list_episodes():
    """List all recorded episodes."""
    if not EPISODES_DIR.exists():
        print("No episodes directory found.")
        return

    episodes = sorted(EPISODES_DIR.iterdir())
    if not episodes:
        print("No episodes recorded yet.")
        return

    print(f"{'Episode':30s} {'Steps':>6s} {'Time':>8s} {'Success':>8s} {'Task'}")
    print("-" * 90)

    for ep_dir in episodes:
        json_path = ep_dir / "episode.json"
        if not json_path.exists():
            continue
        data = json.loads(json_path.read_text())
        summary = data.get("summary", {})
        print(f"{ep_dir.name:30s} "
              f"{summary.get('total_steps', '?'):>6} "
              f"{summary.get('elapsed_seconds', '?'):>7}s "
              f"{'YES' if summary.get('success') else 'NO':>8s} "
              f"{data.get('task', '')[:40]}")


def replay_text(ep_dir: Path):
    """Text-based replay of an episode."""
    json_path = ep_dir / "episode.json"
    if not json_path.exists():
        print(f"No episode.json found in {ep_dir}")
        return

    data = json.loads(json_path.read_text())
    summary = data.get("summary", {})

    print(f"\n{'=' * 60}")
    print(f"EPISODE REPLAY: {ep_dir.name}")
    print(f"Task: {data.get('task', 'N/A')}")
    print(f"Started: {data.get('start_iso', '?')}")
    print(f"{'=' * 60}\n")

    for step in data.get("steps", []):
        status = step.get("result", {}).get("status", "?")
        status_icon = "OK" if status in ("complete", "observed") else "FAIL"

        print(f"┌─ Step {step['step']:03d} [{status_icon}] "
              f"({step.get('duration_ms', 0):.0f}ms)")

        if step.get("thought"):
            print(f"│  Thought: {step['thought'][:120]}")

        args_str = ", ".join(f"{k}={v}" for k, v in step.get("action_args", {}).items())
        print(f"│  Action:  {step['action']}({args_str})")
        print(f"│  Result:  {json.dumps(step.get('result', {}))[:120]}")

        # Show gripper position if scene available
        scene = step.get("scene")
        if scene and "gripper" in scene:
            g = scene["gripper"]
            print(f"│  Gripper: pos={g.get('position')}, "
                  f"open={g.get('open')}, holding={g.get('holding')}")

        if step.get("frame_file"):
            print(f"│  Frame:   {step['frame_file']}")

        print(f"└{'─' * 50}")

    print(f"\n{'=' * 60}")
    print(f"RESULT: {'SUCCESS' if summary.get('success') else 'FAILED'} "
          f"— {summary.get('reason', '?')}")
    print(f"Steps: {summary.get('total_steps', '?')}, "
          f"Time: {summary.get('elapsed_seconds', '?')}s")
    print(f"{'=' * 60}")

    # Check for video
    video_path = ep_dir / "episode.mp4"
    if video_path.exists():
        print(f"\nVideo available: {video_path}")
    else:
        print(f"\nNo video file (run with --video to encode)")


def replay_gui(ep_dir: Path):
    """GUI replay using OpenCV imshow."""
    json_path = ep_dir / "episode.json"
    data = json.loads(json_path.read_text())
    frames_dir = ep_dir / "frames"

    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        print("No frames found, falling back to text replay")
        replay_text(ep_dir)
        return

    steps = data.get("steps", [])
    print(f"Replaying {len(frames)} frames. Press Q to quit, SPACE to pause/resume.")

    paused = False
    idx = 0
    while idx < len(frames):
        img = cv2.imread(str(frames[idx]))
        if img is None:
            idx += 1
            continue

        # Overlay info
        if idx < len(steps):
            s = steps[idx]
            args = ", ".join(f"{k}={v}" for k, v in s.get("action_args", {}).items())
            cv2.putText(img, f"Step {idx}: {s['action']}({args})",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            if s.get("thought"):
                cv2.putText(img, s["thought"][:80],
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            status = s.get("result", {}).get("status", "")
            color = (0, 255, 0) if status == "complete" else (0, 0, 255)
            h = img.shape[0]
            cv2.putText(img, f"Result: {status}",
                        (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.imshow("DecRAS Episode Replay", img)
        key = cv2.waitKey(0 if paused else 500) & 0xFF

        if key == ord("q"):
            break
        elif key == ord(" "):
            paused = not paused
        elif key == ord("n") or (not paused):
            idx += 1
        elif key == ord("p"):
            idx = max(0, idx - 1)

    cv2.destroyAllWindows()


def reencode_video(ep_dir: Path):
    """Re-encode video from saved frames."""
    from mcp_server.episode import EpisodeRecorder
    json_path = ep_dir / "episode.json"
    data = json.loads(json_path.read_text())

    rec = EpisodeRecorder.__new__(EpisodeRecorder)
    rec._dir = ep_dir
    rec._frames_dir = ep_dir / "frames"
    rec._episode = data
    rec._frame_count = len(list(rec._frames_dir.glob("*.png")))

    video_path = rec.encode_video(fps=4)
    if video_path:
        print(f"Video saved: {video_path}")


def main():
    args = sys.argv[1:]

    if not args or "--help" in args:
        print(__doc__)
        return

    if "--list" in args:
        list_episodes()
        return

    if "--latest" in args:
        if not EPISODES_DIR.exists():
            print("No episodes directory found.")
            return
        episodes = sorted(EPISODES_DIR.iterdir())
        if not episodes:
            print("No episodes found.")
            return
        ep_dir = episodes[-1]
    else:
        ep_dir = Path(args[0])

    if not ep_dir.exists():
        print(f"Episode directory not found: {ep_dir}")
        return

    if "--video" in args:
        reencode_video(ep_dir)
        return

    # Try GUI replay first, fall back to text
    if HAS_GUI and "--text" not in args:
        try:
            replay_gui(ep_dir)
        except Exception:
            replay_text(ep_dir)
    else:
        replay_text(ep_dir)


if __name__ == "__main__":
    main()
