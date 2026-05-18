# Experiment Report — Pick-and-Place Yellow Glue Stick
**Date:** 2026-05-18  
**Task:** Pick up the yellow glue stick and move it to the left  
**Hardware:** SO-101 follower arm, phone camera (IP Webcam)  
**Operator:** Alexandre  

---

## Objective

LLM (Claude Sonnet 4.6 via Claude Code) controls the robot arm end-to-end through the DecRAS MCP server. Task: detect yellow glue stick via camera, approach, grasp, lift, transit left, release.

---

## What Executed

The arm completed the full motion sequence without errors:

| Step | Action | EE result |
|------|--------|-----------|
| 1 | Lift to approach height `dz=+0.07` | z = 0.085 m |
| 2 | Navigate left `dy=+0.08` | y = 0.129 m |
| 3 | Descend to grasp height `dz=-0.05` | z = 0.019 m |
| 4 | `grasp(force=3.0)` | `contact=true`, force = 2.7 N |
| 5 | Lift `dz=+0.08` | z = 0.088 m |
| 6 | Transit left `dy=+0.15` | y = 0.266 m |
| 7 | `release()` | open |
| 8 | Retreat `dx=-0.05, dz=+0.05` | clear |

---

## Result

**The stick did not move.** The arm missed it entirely. The grasp reported `contact: true` and `force: 2.7 N` but the stick was not physically touched. This is a false positive — the servo load reading does not distinguish between grasping an object and the fingers closing on themselves (no external contact needed to register a small force).

---

## Root Causes

### 1. Broken camera-to-robot coordinate transform

`observe()` returns object positions that look like robot-frame meters but are not. The pipeline is:

```
camera frame → detect_objects() → pixel center (px, py)
             → pixel_to_robot() → "robot frame" position
```

`pixel_to_robot()` checks for `CAMERA_TO_ROBOT_MATRIX` in config. **This matrix is `None`** — the camera has never been calibrated against the robot frame. The fallback is a naive linear mapping:

```python
x = 0.0 + (px / 640.0) * 0.4
y = -0.2 + (py / 480.0) * 0.4
```

The positions returned in `observe()` (e.g. yellow stick at `[0.70, 0.498, 0.02]`) are meaningless in robot frame — they are pixel coordinates divided by a fixed constant. The x=0.70 value already exceeds the arm's maximum reach (0.40 m), which is a clear signal the numbers are wrong.

### 2. Claude did not catch the invalid coordinates

The LLM noticed the coordinates were suspicious (`x=0.70 > 0.40 m max`) but attempted to recover by inventing a ~3.8× scale factor heuristic ("divide pixel values by ~3.8 to get robot meters"). This was wrong. The correct response would have been to stop and report that the perception output is uncalibrated.

### 3. `observe()` returns no image

The MCP `observe()` tool captures a camera frame internally but only returns a JSON string. The raw image is never exposed to the LLM. This means:
- The LLM cannot visually verify what the camera sees
- The LLM cannot detect that the coordinate transform is broken by looking at the image
- All spatial reasoning relies entirely on the (currently broken) scene graph numbers

### 4. `holding: null` is unreliable as a failure signal

After `grasp()`, the scene graph continued to show `"holding": null` and `"grasped": false` for the stick. This is because `holding` is tracked by `r.holding` (set programmatically in server.py), not by visual re-detection post-grasp. It correctly showed null because the grasp missed, but would have shown the same result even if the contact signal had been a false positive in hardware — it is not an independent sensor check.

---

## What the User Reported

- The stick did not move at all during the run
- The arm executed its motions but never made physical contact with the stick
- The coordinate frame issue was confirmed: the perception output is not in robot frame

---

## What Is Needed to Fix This

### Short term — run the experiment correctly

1. **Calibrate the camera.** Run the existing `calibrate` MCP tool or the calibration notebook to compute `CAMERA_TO_ROBOT_MATRIX` and write it to `config.py`. Until this is done, `observe()` positions are noise.

2. **Expose the raw image in `observe()`.**  Return the camera frame as a base64-encoded image content block alongside the JSON. This lets the LLM see what the camera sees and catch obvious errors (object not visible, wrong detection, etc.).

3. **Stop if perception coordinates are out of workspace bounds.** The LLM should refuse to proceed if any object `x > 0.40` or `|y| > 0.20` — those are hard workspace limits and values outside them are guaranteed to be wrong.

### Medium term — robustness

4. **Independent grasp verification.** After `grasp()`, re-observe and check that the stick's pixel position moved with the gripper (or disappeared from the table). A contact-force signal alone is insufficient.

5. **Validate `CAMERA_TO_ROBOT_MATRIX` is set before any LLM pick-and-place run.** Add a startup check in the MCP server that warns (or refuses) if the matrix is None and the camera is available.

---

## Lessons

| # | Lesson |
|---|--------|
| 1 | Never trust perception coordinates that exceed workspace bounds — always sanity-check against known limits before moving |
| 2 | `contact: true` from a servo does not mean object contact; a gripper closing on air can still register a small force |
| 3 | Without image access, the LLM has no ground truth to fall back on when numbers look wrong |
| 4 | Camera calibration is a hard prerequisite for any real pick-and-place; the system should refuse to operate without it |
