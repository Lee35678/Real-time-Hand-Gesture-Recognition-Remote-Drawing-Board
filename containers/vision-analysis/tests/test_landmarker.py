import queue
from dataclasses import dataclass
from typing import Any

from app.vision.landmarker import HandLandmarkerSession, MonotonicTimestampGuard


def test_timestamp_guard_passes_through_increasing_values():
    guard = MonotonicTimestampGuard()
    assert guard.next(100) == 100
    assert guard.next(200) == 200


def test_timestamp_guard_bumps_non_increasing_values():
    guard = MonotonicTimestampGuard()
    assert guard.next(100) == 100
    assert guard.next(100) == 101
    assert guard.next(50) == 102


def test_timestamp_guard_starts_from_first_value():
    guard = MonotonicTimestampGuard()
    assert guard.next(0) == 0
    assert guard.next(0) == 1


def _make_bare_session() -> HandLandmarkerSession:
    """Builds a HandLandmarkerSession without running __init__ (which would
    load a real MediaPipe model) — _on_result only touches the two attributes
    set here."""
    session = object.__new__(HandLandmarkerSession)
    session._pending_started_at = {}
    session._result_queue = queue.Queue()
    return session


@dataclass
class _FakePoint:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class _FakeCategory:
    category_name: str = "Right"
    score: float = 0.9


class _FakeResult:
    def __init__(self, hand_landmarks: Any, hand_world_landmarks: Any):
        self.hand_landmarks = hand_landmarks
        self.hand_world_landmarks = hand_world_landmarks
        self.handedness = [[_FakeCategory()]]


def test_on_result_treats_missing_world_landmarks_as_hand_not_present():
    session = _make_bare_session()
    one_hand = [_FakePoint() for _ in range(21)]

    session._on_result(_FakeResult(hand_landmarks=[one_hand], hand_world_landmarks=[]), None, 42)

    result = session._result_queue.get_nowait()
    assert result.hand_present is False
    assert result.landmarks is None
    assert result.world_landmarks is None


def test_on_result_builds_packet_when_both_landmark_sets_present():
    session = _make_bare_session()
    one_hand = [_FakePoint(x=i / 100) for i in range(21)]

    session._on_result(
        _FakeResult(hand_landmarks=[one_hand], hand_world_landmarks=[one_hand]), None, 42
    )

    result = session._result_queue.get_nowait()
    assert result.hand_present is True
    assert len(result.landmarks) == 21
    assert len(result.world_landmarks) == 21
