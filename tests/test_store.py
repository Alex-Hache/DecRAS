"""Tests for the demo store (save/load/list + ingest)."""

import json

import pytest

from decras.imitation.retrieval import Demo, DemoMetadata, Primitive
from decras.imitation.store import (
    demo_id,
    demo_path,
    ingest_sequence,
    list_demos,
    load_demo,
    save_demo,
)


def _make_demo(dataset="ds", episode=0, density="medium") -> Demo:
    return Demo(
        task="pick and place",
        primitives=[
            Primitive(tool="move_to_delta", args={"dx": 0.05, "dy": 0.0, "dz": -0.02}, timestamp=0.0),
            Primitive(tool="grasp", args={"force": 0.5}, timestamp=0.4),
            Primitive(tool="release", args={}, timestamp=1.1),
        ],
        metadata=DemoMetadata(dataset=dataset, episode=episode, density=density),
    )


def test_demo_id_includes_density():
    meta = DemoMetadata(dataset="sticks_v2", episode=3, density="low")
    assert demo_id(meta) == "sticks_v2_ep003_low"


def test_demo_id_omits_missing_density():
    meta = DemoMetadata(dataset="sticks_v2", episode=3)
    assert demo_id(meta) == "sticks_v2_ep003"


def test_save_load_roundtrip(tmp_path):
    demo = _make_demo()
    path = save_demo(demo, root=tmp_path)

    assert path == demo_path(demo, tmp_path)
    assert path.exists()

    loaded = load_demo(path)
    assert loaded == demo
    assert loaded.to_dict() == demo.to_dict()


def test_save_includes_provenance_fields_when_set(tmp_path):
    demo = _make_demo()
    demo.metadata.created_at = "2026-04-19T10:00:00+00:00"
    demo.metadata.source_sequence_path = "datasets/ds/sequences/episode_000.json"
    demo.metadata.segmenter_git_sha = "abc1234"

    path = save_demo(demo, root=tmp_path)
    raw = json.loads(path.read_text())

    assert raw["metadata"]["created_at"] == "2026-04-19T10:00:00+00:00"
    assert raw["metadata"]["source_sequence_path"] == "datasets/ds/sequences/episode_000.json"
    assert raw["metadata"]["segmenter_git_sha"] == "abc1234"


def test_save_omits_unset_provenance_fields(tmp_path):
    demo = _make_demo()
    path = save_demo(demo, root=tmp_path)
    raw = json.loads(path.read_text())

    assert "created_at" not in raw["metadata"]
    assert "source_sequence_path" not in raw["metadata"]
    assert "segmenter_git_sha" not in raw["metadata"]


def test_list_demos_returns_all_sorted(tmp_path):
    save_demo(_make_demo(dataset="b", episode=1, density="medium"), root=tmp_path)
    save_demo(_make_demo(dataset="a", episode=0, density="low"), root=tmp_path)
    save_demo(_make_demo(dataset="a", episode=2, density="high"), root=tmp_path)

    demos = list_demos(tmp_path)
    assert len(demos) == 3
    ids = [demo_id(d.metadata) for d in demos]
    assert ids == sorted(ids)  # alphabetical by filename


def test_list_demos_empty_root(tmp_path):
    assert list_demos(tmp_path / "nonexistent") == []
    assert list_demos(tmp_path) == []


def test_duplicate_raises_by_default(tmp_path):
    demo = _make_demo()
    save_demo(demo, root=tmp_path)
    with pytest.raises(FileExistsError):
        save_demo(demo, root=tmp_path)


def test_duplicate_overwrite_replaces_file(tmp_path):
    demo = _make_demo()
    save_demo(demo, root=tmp_path)

    demo.task = "a different task"
    path = save_demo(demo, root=tmp_path, overwrite=True)

    assert load_demo(path).task == "a different task"


def _write_sequence(path, *, task=None, dataset="ds", episode=0, density="medium"):
    body = {
        "primitives": [
            {"tool": "move_to_delta", "args": {"dx": 0.01, "dy": 0.0, "dz": 0.0}, "timestamp": 0.0},
            {"tool": "grasp", "args": {"force": 0.5}, "timestamp": 0.1},
        ],
        "metadata": {
            "dataset": dataset,
            "episode": episode,
            "density": density,
            "start_ee_position": {"x": 0.1, "y": 0.05, "z": 0.12},
        },
    }
    if task is not None:
        body["task"] = task
    path.write_text(json.dumps(body))


def test_ingest_sequence_populates_provenance(tmp_path):
    seq = tmp_path / "episode_000.json"
    _write_sequence(seq, task="pick and place")
    store = tmp_path / "demos"

    path = ingest_sequence(seq, root=store)
    demo = load_demo(path)

    assert demo.task == "pick and place"
    assert demo.metadata.dataset == "ds"
    assert demo.metadata.episode == 0
    assert demo.metadata.density == "medium"
    assert demo.metadata.start_ee_position == {"x": 0.1, "y": 0.05, "z": 0.12}
    assert demo.metadata.created_at is not None
    assert demo.metadata.source_sequence_path is not None
    # Expected filename from deterministic id
    assert path.name == "ds_ep000_medium.json"


def test_ingest_sequence_task_override(tmp_path):
    seq = tmp_path / "episode_000.json"
    _write_sequence(seq, task="stale task")
    store = tmp_path / "demos"

    path = ingest_sequence(seq, task="fresh task", root=store)
    assert load_demo(path).task == "fresh task"


def test_ingest_sequence_requires_task(tmp_path):
    seq = tmp_path / "episode_000.json"
    _write_sequence(seq, task=None)
    with pytest.raises(ValueError, match="task"):
        ingest_sequence(seq, root=tmp_path / "demos")


def test_ingest_sequence_refuses_duplicate_without_overwrite(tmp_path):
    seq = tmp_path / "episode_000.json"
    _write_sequence(seq, task="t")
    store = tmp_path / "demos"

    ingest_sequence(seq, root=store)
    with pytest.raises(FileExistsError):
        ingest_sequence(seq, root=store)

    # And succeeds with overwrite
    ingest_sequence(seq, task="updated", root=store, overwrite=True)
    demos = list_demos(store)
    assert len(demos) == 1
    assert demos[0].task == "updated"
