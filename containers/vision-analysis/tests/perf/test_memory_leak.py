"""10,000회 반복 후 RSS 증가량 검증 (refactoring.md Pillar 3-5 / 3-6 수용 기준).

카메라·MediaPipe 불필요 — 이 컨테이너 자체 코드(전처리/스무딩/기하연산/패킷
직렬화)가 장시간 구동해도 스스로 메모리를 누적하지 않는지만 확인한다. 실제
MediaPipe HandLandmarker의 네이티브 메모리는 별도 관심사이며 카메라 기반
측정(docs/00_baseline_metrics.md §3.3)이 준비되면 그쪽에서 확인한다.

기본 CI/로컬 실행에서는 제외된다(@pytest.mark.slow, pytest.ini의
`-m "not slow"`) — 명시적으로 실행하려면:

    pytest -m slow tests/perf/test_memory_leak.py
"""

from __future__ import annotations

import gc
import json

import numpy as np
import psutil
import pytest

from app.contracts import Handedness, LandmarkPacket, Quality
from app.vision.geometry import Point, hand_scale, is_near_edge, max_displacement
from app.vision.preprocess import prepare_for_inference
from app.vision.smoothing import HandLandmarksFilter

ITERATIONS = 10_000
WARMUP_ITERATIONS = 200
MAX_RSS_GROWTH_BYTES = 50 * 1024 * 1024  # refactoring.md 3-6: 10,000 프레임 후 RSS 증가 < 50MB


@pytest.mark.slow
def test_pure_pipeline_functions_do_not_leak_over_10000_iterations():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    filt = HandLandmarksFilter()
    state = {"prev_landmarks": None}
    process = psutil.Process()

    def run_one_iteration(i: int) -> None:
        prepared, _ = prepare_for_inference(frame, "bgr8", 0, False, 640, 480, enable_clahe=False)
        assert prepared.shape == (480, 640, 3)

        # Small deterministic per-frame variation, not a fixed constant — a
        # leak tied to changing values (e.g. an ever-growing history) wouldn't
        # show up if every iteration used byte-identical input.
        landmarks = [Point(0.5 + 0.0001 * (i % 37), 0.5, 0.0) for _ in range(21)]
        filtered = filt.apply(landmarks, timestamp_ms=float(i) * 33.0)

        scale = hand_scale(filtered)
        is_near_edge(filtered, 0.03)
        if state["prev_landmarks"] is not None and scale > 0:
            max_displacement(state["prev_landmarks"], filtered)
        state["prev_landmarks"] = filtered

        packet = LandmarkPacket.present(
            session_id="leak-check",
            seq=i,
            capture_ts=i,
            processed_ts=i,
            frame_w=640,
            frame_h=480,
            handedness=Handedness("Right", 0.9),
            landmarks=filtered,
            world_landmarks=filtered,
            hand_scale=scale,
            quality=Quality(),
        )
        json.loads(packet.to_json())

        if i % 500 == 0:
            # Exercises the hand-lost reset path too (pipeline/runner.py calls
            # this whenever a session's hand disappears) so a leak specific to
            # reset() wouldn't be missed by only ever calling apply().
            filt.reset()
            state["prev_landmarks"] = None

    for i in range(WARMUP_ITERATIONS):
        run_one_iteration(i)

    gc.collect()
    rss_before = process.memory_info().rss

    for i in range(WARMUP_ITERATIONS, WARMUP_ITERATIONS + ITERATIONS):
        run_one_iteration(i)

    gc.collect()
    rss_after = process.memory_info().rss

    growth_mb = (rss_after - rss_before) / 1024 / 1024
    assert rss_after - rss_before < MAX_RSS_GROWTH_BYTES, (
        f"RSS grew by {growth_mb:.1f}MB over {ITERATIONS} iterations "
        f"(limit {MAX_RSS_GROWTH_BYTES / 1024 / 1024:.0f}MB)"
    )
