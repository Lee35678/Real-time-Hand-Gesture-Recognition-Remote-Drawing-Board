"""카메라·MediaPipe 없이 파이프라인 순수 오버헤드를 측정한다 (refactoring.md §2.3).

"추론을 제외한 파이프라인 순수 오버헤드는 SyntheticSource로 별도 측정해 분리
기록한다" — 이 저장소의 실제 구조에서 카메라/네트워크를 완전히 배제하고 순수
오버헤드만 재현 가능하게 측정하는 가장 직접적인 방법은, 합성 프레임/랜드마크로
전처리·스무딩·기하 연산·직렬화 함수를 직접 호출해 시간을 재는 것이다 (MediaPipe
추론 자체는 여기서 실행하지 않는다 — 그 부분은 /metrics의 inference_ms_p50/p95로
실측 카메라 세션에서 별도 확인한다).

사용 예:
    python scripts/bench_pure_overhead.py --iterations 2000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import Handedness, LandmarkPacket, Quality
from app.vision.geometry import (
    Point,
    hand_scale,
    is_near_edge,
    max_displacement,
)
from app.vision.preprocess import prepare_for_inference
from app.vision.smoothing import HandLandmarksFilter


def _percentiles(samples_ms: list[float]) -> dict:
    arr = np.array(samples_ms)
    return {
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "mean": float(arr.mean()),
    }


def _time_calls(fn, iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return samples


def bench_preprocess(iterations: int) -> dict:
    frame = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)

    def fn():
        return prepare_for_inference(frame, "bgr8", 0, False, 640, 480, enable_clahe=False)

    return _percentiles(_time_calls(fn, iterations))


def bench_preprocess_with_clahe(iterations: int) -> dict:
    frame = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)

    def fn():
        return prepare_for_inference(frame, "bgr8", 0, False, 640, 480, enable_clahe=True)

    return _percentiles(_time_calls(fn, iterations))


def bench_smoothing(iterations: int) -> dict:
    filt = HandLandmarksFilter()
    landmarks = [Point(0.5, 0.5, 0.0) for _ in range(21)]
    t = 0.0

    def _step():
        nonlocal t
        t += 1.0 / 30.0
        filt.apply(landmarks, timestamp_ms=t * 1000.0)

    return _percentiles(_time_calls(_step, iterations))


def bench_geometry(iterations: int) -> dict:
    prev = [Point(0.5, 0.5, 0.0) for _ in range(21)]
    curr = [Point(0.501, 0.5, 0.0) for _ in range(21)]

    def _step():
        hand_scale(curr)
        is_near_edge(curr, 0.03)
        max_displacement(prev, curr)

    return _percentiles(_time_calls(_step, iterations))


def bench_packet_build_and_serialize(iterations: int) -> dict:
    landmarks = [Point(0.5, 0.5, 0.0) for _ in range(21)]
    world = [Point(0.01, 0.02, 0.03) for _ in range(21)]

    def _step():
        packet = LandmarkPacket.present(
            session_id="bench",
            seq=1,
            capture_ts=0,
            processed_ts=1,
            frame_w=640,
            frame_h=480,
            handedness=Handedness("Right", 0.95),
            landmarks=landmarks,
            world_landmarks=world,
            hand_scale=0.12,
            quality=Quality(),
        )
        packet.to_json()

    return _percentiles(_time_calls(_step, iterations))


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure pure pipeline overhead (no camera, no MediaPipe)")
    parser.add_argument("--iterations", type=int, default=2000)
    args = parser.parse_args()

    result = {
        "iterations": args.iterations,
        "preprocess_ms": bench_preprocess(args.iterations),
        "preprocess_with_clahe_ms": bench_preprocess_with_clahe(args.iterations),
        "smoothing_apply_ms": bench_smoothing(args.iterations),
        "geometry_ms": bench_geometry(args.iterations),
        "packet_build_and_serialize_ms": bench_packet_build_and_serialize(args.iterations),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
