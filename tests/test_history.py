"""Tests for position history buffer."""

from mcp_server.history import PositionHistory


def test_empty_history():
    h = PositionHistory()
    assert len(h) == 0
    assert h.current is None
    assert h.go_back(1) is None


def test_record_and_current():
    h = PositionHistory()
    h.record([0.1, 0.2, 0.3])
    assert len(h) == 1
    assert h.current == [0.1, 0.2, 0.3]


def test_go_back_single():
    h = PositionHistory()
    h.record([0.1, 0.2, 0.3])
    h.record([0.4, 0.5, 0.6])
    pos = h.go_back(1)
    assert pos == [0.4, 0.5, 0.6]
    assert len(h) == 1


def test_go_back_multiple():
    h = PositionHistory()
    h.record([0.1, 0.0, 0.0])
    h.record([0.2, 0.0, 0.0])
    h.record([0.3, 0.0, 0.0])
    pos = h.go_back(2)
    assert pos == [0.2, 0.0, 0.0]
    assert len(h) == 1


def test_go_back_clamped_to_available():
    h = PositionHistory()
    h.record([0.1, 0.0, 0.0])
    h.record([0.2, 0.0, 0.0])
    pos = h.go_back(10)  # more than available
    assert pos == [0.1, 0.0, 0.0]
    assert len(h) == 0


def test_max_size():
    h = PositionHistory(max_size=3)
    for i in range(5):
        h.record([float(i), 0.0, 0.0])
    assert len(h) == 3
    # Oldest entries were dropped
    assert h.current == [4.0, 0.0, 0.0]


def test_record_makes_copy():
    h = PositionHistory()
    pos = [0.1, 0.2, 0.3]
    h.record(pos)
    pos[0] = 999.0  # mutate original
    assert h.current == [0.1, 0.2, 0.3]  # should be unaffected
