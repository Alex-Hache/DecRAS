"""Tests for the FK/IK kinematics module and gravity model."""

import os
import pytest

os.environ.setdefault("SIMULATE", "true")

from mcp_server.robot.kinematics import (
    joints_to_cartesian,
    cartesian_to_joints,
    gravity_torques_dict,
    JOINT_NAMES_ARM,
)

WORK_JOINTS = {
    "shoulder_pan": -18.0,
    "shoulder_lift": -60.0,
    "elbow_flex": 37.0,
    "wrist_flex": 74.0,
    "wrist_roll": 0.0,
}


def test_fk_returns_three_floats():
    pos = joints_to_cartesian(WORK_JOINTS)
    assert len(pos) == 3
    assert all(isinstance(v, float) for v in pos)


def test_fk_work_position_height():
    """EE at WORK_POSITION should be above the table (~0.10-0.20m)."""
    x, y, z = joints_to_cartesian(WORK_JOINTS)
    assert 0.05 < z < 0.30, f"Unexpected EE height at WORK_POSITION: z={z:.3f}"


def test_ik_roundtrip():
    """FK followed by IK should recover the original EE position within 5mm."""
    target = joints_to_cartesian(WORK_JOINTS)
    recovered = cartesian_to_joints(target[0], target[1], target[2], seed_hw_joints=WORK_JOINTS)
    ee_check = joints_to_cartesian(recovered)
    for orig, recov in zip(target, ee_check):
        assert abs(orig - recov) < 0.005, f"IK roundtrip error > 5mm: {orig:.4f} vs {recov:.4f}"


def test_gravity_torques_dict_keys():
    """gravity_torques_dict should return all arm joints."""
    τ = gravity_torques_dict(WORK_JOINTS)
    assert set(JOINT_NAMES_ARM) <= set(τ.keys()), (
        f"Missing joints in gravity dict. Got: {set(τ.keys())}"
    )


def test_gravity_torques_dict_values_finite():
    """All gravity torques should be finite floats."""
    τ = gravity_torques_dict(WORK_JOINTS)
    import math
    for name in JOINT_NAMES_ARM:
        assert math.isfinite(τ[name]), f"Non-finite gravity torque for {name}: {τ[name]}"


def test_gravity_torques_dict_magnitude():
    """Gravity torques should be in a physically plausible range (< 5 N·m for SO-101)."""
    τ = gravity_torques_dict(WORK_JOINTS)
    for name in JOINT_NAMES_ARM:
        assert abs(τ[name]) < 5.0, (
            f"Gravity torque for {name} seems unrealistic: {τ[name]:.3f} N·m"
        )


def test_gravity_torques_dict_changes_with_config():
    """Gravity torques at two different configs should differ for shoulder_lift."""
    τ_work = gravity_torques_dict(WORK_JOINTS)
    raised = dict(WORK_JOINTS, shoulder_lift=-80.0)
    τ_raised = gravity_torques_dict(raised)
    assert τ_work["shoulder_lift"] != τ_raised["shoulder_lift"], (
        "Gravity torques should change with configuration"
    )


def test_gravity_torques_accepts_pos_suffix():
    """gravity_torques_dict should accept .pos-suffixed keys (LeRobot format)."""
    joints_with_suffix = {f"{k}.pos": v for k, v in WORK_JOINTS.items()}
    τ = gravity_torques_dict(joints_with_suffix)
    assert set(JOINT_NAMES_ARM) <= set(τ.keys())
