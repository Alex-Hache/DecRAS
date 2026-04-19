"""Camera-to-robot calibration script.

Procedure:
1. Move the gripper to several known positions in robot frame.
2. For each position, the user clicks the gripper tip in the camera image.
3. Compute an affine transform from pixel coords to robot coords.
4. Save the matrix to a JSON file for use by the perception pipeline.

Usage:
    python -m scripts.calibrate

In simulation mode, generates synthetic calibration data.
"""

import json
import logging
import numpy as np
from pathlib import Path

from mcp_server.config import SIMULATE

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

try:
    import cv2
except ImportError:
    cv2 = None

CALIBRATION_FILE = Path(__file__).parent.parent / "calibration.json"

# Calibration points: known robot positions to visit
CALIBRATION_POINTS = [
    [0.05, -0.15, 0.05],
    [0.35, -0.15, 0.05],
    [0.35, 0.15, 0.05],
    [0.05, 0.15, 0.05],
    [0.20, 0.0, 0.05],
]


def collect_points_interactive() -> tuple[np.ndarray, np.ndarray]:
    """Interactively collect calibration correspondences.

    Returns (pixel_points, robot_points) as Nx2 and Nx2 arrays.
    """
    from mcp_server.config import CAMERA_SOURCE
    from mcp_server.perception.camera import Camera

    camera = Camera(CAMERA_SOURCE)
    pixel_points = []
    robot_points = []
    click_pos = [None]

    def on_click(event, x, y, flags, param):
        if event == (cv2.EVENT_LBUTTONDOWN if cv2 else 1):
            click_pos[0] = (x, y)

    if cv2 is not None:
        cv2.namedWindow("Calibration")
        cv2.setMouseCallback("Calibration", on_click)

    for i, rpos in enumerate(CALIBRATION_POINTS):
        print(f"\n--- Point {i+1}/{len(CALIBRATION_POINTS)} ---")
        print(f"Move the gripper to robot position: {rpos}")
        input("Press Enter when the gripper is in position...")

        frame = camera.capture()

        if cv2 is not None:
            print("Click on the gripper tip in the image, then press any key.")
            cv2.imshow("Calibration", frame)
            click_pos[0] = None
            while click_pos[0] is None:
                cv2.waitKey(50)
            px, py = click_pos[0]
            print(f"  Pixel: ({px}, {py}) -> Robot: {rpos[:2]}")
        else:
            px = int(input("  Enter pixel X: "))
            py = int(input("  Enter pixel Y: "))

        pixel_points.append([px, py])
        robot_points.append(rpos[:2])  # only x, y

    if cv2 is not None:
        cv2.destroyAllWindows()
    camera.release()

    return np.array(pixel_points, dtype=np.float64), np.array(robot_points, dtype=np.float64)


def collect_points_simulated() -> tuple[np.ndarray, np.ndarray]:
    """Generate synthetic calibration data for testing."""
    # Simulate a simple linear mapping: pixel (0,0)->(640,480) maps to robot (0,-0.2)->(0.4,0.2)
    pixel_points = np.array([
        [80, 36],    # (0.05, -0.15)
        [560, 36],   # (0.35, -0.15)
        [560, 420],  # (0.35, 0.15)
        [80, 420],   # (0.05, 0.15)
        [320, 240],  # (0.20, 0.0)
    ], dtype=np.float64)

    robot_points = np.array([
        [0.05, -0.15],
        [0.35, -0.15],
        [0.35, 0.15],
        [0.05, 0.15],
        [0.20, 0.0],
    ], dtype=np.float64)

    return pixel_points, robot_points


def compute_affine(pixel_points: np.ndarray, robot_points: np.ndarray) -> np.ndarray:
    """Compute a 3x3 affine transform from pixel coords to robot coords.

    Uses least-squares fit: robot_xy = M @ [px, py, 1]^T
    """
    n = len(pixel_points)
    # Build matrix A: [px, py, 1] for each point
    A = np.column_stack([pixel_points, np.ones(n)])

    # Solve for x-component and y-component separately
    # robot_x = a*px + b*py + c
    # robot_y = d*px + e*py + f
    Mx, _, _, _ = np.linalg.lstsq(A, robot_points[:, 0], rcond=None)
    My, _, _, _ = np.linalg.lstsq(A, robot_points[:, 1], rcond=None)

    # Assemble 3x3 matrix (last row = [0, 0, 1] for homogeneous coords)
    M = np.array([
        [Mx[0], Mx[1], Mx[2]],
        [My[0], My[1], My[2]],
        [0.0,   0.0,   1.0],
    ])

    return M


def save_calibration(matrix: np.ndarray):
    data = {"camera_to_robot_matrix": matrix.tolist()}
    CALIBRATION_FILE.write_text(json.dumps(data, indent=2))
    logger.info("Calibration saved to %s", CALIBRATION_FILE)


def load_calibration() -> np.ndarray | None:
    """Load calibration matrix from file, if it exists."""
    if not CALIBRATION_FILE.exists():
        return None
    data = json.loads(CALIBRATION_FILE.read_text())
    return np.array(data["camera_to_robot_matrix"])


def main():
    print("=== DecRAS Camera-to-Robot Calibration ===\n")

    if SIMULATE:
        print("Running in SIMULATE mode — using synthetic data.\n")
        pixel_pts, robot_pts = collect_points_simulated()
    else:
        pixel_pts, robot_pts = collect_points_interactive()

    print(f"\nCollected {len(pixel_pts)} calibration points.")

    M = compute_affine(pixel_pts, robot_pts)
    print(f"\nAffine transform matrix:\n{M}")

    # Verify: transform pixel points back and check error
    errors = []
    for px_pt, r_pt in zip(pixel_pts, robot_pts):
        predicted = M @ np.array([px_pt[0], px_pt[1], 1.0])
        err = np.linalg.norm(predicted[:2] - r_pt)
        errors.append(err)
    print(f"\nReprojection errors (meters): {[f'{e:.6f}' for e in errors]}")
    print(f"Mean error: {np.mean(errors):.6f} m")

    save_calibration(M)
    print("\nCalibration complete!")


if __name__ == "__main__":
    main()
