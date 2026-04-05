"""Minimum-jerk joint trajectory generation for smooth robot motion.

Generates smooth joint trajectories using the 5th-order (minimum-jerk) polynomial.
This guarantees zero velocity and zero acceleration at both endpoints, giving
smooth, human-like motion that avoids abrupt starts and stops.

Reference: Flash & Hogan 1985 "The coordination of arm movements".
"""

import numpy as np

# Speed presets — base durations for a 90° joint move
SPEED_DURATIONS: "dict[str, float]" = {
    "slow":   3.0,  # near objects, delicate grasps
    "normal": 1.5,  # typical free-space moves
    "fast":   0.5,  # quick repositioning
}


# ---------------------------------------------------------------------------
# Core trajectory primitives
# ---------------------------------------------------------------------------

def minimum_jerk_profile(t: np.ndarray) -> np.ndarray:
    """Minimum-jerk normalised position profile.

    Args:
        t: Array of normalised time values in [0, 1].

    Returns:
        s: Normalised position in [0, 1] with zero velocity and acceleration
           at both endpoints.
    """
    t = np.clip(t, 0.0, 1.0)
    return 10.0 * t**3 - 15.0 * t**4 + 6.0 * t**5


def minimum_jerk_joint_trajectory(
    q_start: "dict[str, float] | np.ndarray | list",
    q_end: "dict[str, float] | np.ndarray | list",
    duration: float,
    hz: float = 50.0,
) -> np.ndarray:
    """Generate a minimum-jerk joint-space trajectory.

    Args:
        q_start: Starting joint angles. Either a dict ``{name: degrees}``
                 or an array/list of floats.
        q_end: Target joint angles. Same format as q_start.
        duration: Total motion duration in seconds.
        hz: Control frequency (waypoints per second). Default 50 Hz.

    Returns:
        trajectory: ``(steps, num_joints)`` array of joint angles in degrees.
                    The first row equals q_start; the last row equals q_end.
    """
    q_start_arr, q_end_arr = _to_arrays(q_start, q_end)

    steps = max(2, int(round(duration * hz)))
    t = np.linspace(0.0, 1.0, steps)
    s = minimum_jerk_profile(t)  # (steps,)

    # trajectory[i] = q_start + s[i] * (q_end - q_start)
    trajectory = q_start_arr[np.newaxis, :] + s[:, np.newaxis] * (q_end_arr - q_start_arr)
    return trajectory


def compute_duration(
    q_start: "dict[str, float] | np.ndarray | list",
    q_end: "dict[str, float] | np.ndarray | list",
    speed: str = "normal",
) -> float:
    """Compute appropriate trajectory duration from a speed preset.

    Scales the base duration by the maximum joint displacement so that small
    moves are not needlessly slowed down.

    Args:
        q_start: Starting joint angles (dict or array).
        q_end: Target joint angles (dict or array).
        speed: One of ``"slow"``, ``"normal"``, or ``"fast"``.

    Returns:
        Duration in seconds (minimum 0.2 s).
    """
    q_start_arr, q_end_arr = _to_arrays(q_start, q_end)
    base = SPEED_DURATIONS.get(speed, SPEED_DURATIONS["normal"])
    max_delta_deg = float(np.abs(q_end_arr - q_start_arr).max())
    # Scale linearly: full duration at 90°, minimum 0.2 s
    scale = min(1.0, max_delta_deg / 90.0)
    return max(0.2, base * scale)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_arrays(
    q_start: "dict[str, float] | np.ndarray | list",
    q_end: "dict[str, float] | np.ndarray | list",
) -> "tuple[np.ndarray, np.ndarray]":
    """Normalise q_start / q_end to numpy float64 arrays."""
    if isinstance(q_start, dict):
        keys = list(q_start.keys())
        start = np.array([q_start[k] for k in keys], dtype=np.float64)
        end = np.array([q_end[k] for k in keys], dtype=np.float64)
    else:
        start = np.array(q_start, dtype=np.float64)
        end = np.array(q_end, dtype=np.float64)
    return start, end
