"""베이스라인 측정용 카메라 스트리머 + 리소스 모니터 (refactoring.md §2.3).

`dev_camera_source.py`와 같은 ingest 프로토콜로 실제 웹캠 프레임을 정해진
시간만큼 스트리밍하면서, 동시에 vision-analysis 프로세스의 RSS/CPU를
주기적으로 샘플링해 CSV로 남긴다. 두 관심사(스트리밍/리소스 모니터링)를 한
스크립트에 묶은 이유는 벤치마크 1회 실행을 하나의 명령으로 재현 가능하게
하기 위해서다 — `dev_camera_source.py` 자체는 건드리지 않는다.

일부 Windows 환경에서는 OpenCV 기본 백엔드(MSMF)로 카메라를 열 수는 있어도
프레임 읽기(`read()`)가 실패하는 경우가 있다 — 그 경우 DirectShow로 재시도한다.

사용 예:
    python scripts/bench_stream_and_monitor.py --pid 12345 --duration-sec 40 \
        --rss-out docs/perf/run1_rss.csv --url ws://127.0.0.1:8760/ingest/bench-session
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
import uuid

import cv2
import psutil
from websockets.asyncio.client import connect


def _open_camera(index: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        ok, _ = cap.read()
        if ok:
            return cap
        cap.release()
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise SystemExit(f"failed to open camera index {index} (tried default backend and CAP_DSHOW)")
    return cap


def _monitor_resources(pid: int, out_path: str, stop_event: threading.Event, interval_sec: float) -> None:
    proc = psutil.Process(pid)
    proc.cpu_percent(interval=None)  # prime the internal counter, first call is always 0.0
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("elapsed_s,rss_bytes,cpu_percent\n")
        start = time.monotonic()
        while not stop_event.is_set():
            try:
                rss = proc.memory_info().rss
                cpu = proc.cpu_percent(interval=None)
            except psutil.NoSuchProcess:
                break
            fh.write(f"{time.monotonic() - start:.2f},{rss},{cpu:.1f}\n")
            fh.flush()
            stop_event.wait(interval_sec)


async def _stream(url: str, camera_index: int, duration_sec: float, target_fps: float) -> None:
    cap = _open_camera(camera_index)
    frame_interval = 1.0 / target_fps
    seq = 0
    deadline = time.monotonic() + duration_sec

    async with connect(url, max_size=None) as ws:
        print(f"connected to {url}")
        try:
            while time.monotonic() < deadline:
                loop_start = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    print("frame read failed, skipping")
                    await asyncio.sleep(frame_interval)
                    continue

                height, width = frame.shape[:2]
                payload = frame.tobytes()
                header = {
                    "schema_version": "1.0",
                    "session_id": url.rsplit("/", 1)[-1],
                    "frame_id": str(uuid.uuid4()),
                    "seq": seq,
                    "captured_at_ms": int(time.time() * 1000),
                    "width": width,
                    "height": height,
                    "channels": 3,
                    "dtype": "uint8",
                    "color_order": "BGR",
                    "byte_length": len(payload),
                    "rotation": 0,
                    "mirrored": False,
                }
                await ws.send(json.dumps(header))
                await ws.send(payload)
                seq += 1

                elapsed = time.monotonic() - loop_start
                await asyncio.sleep(max(0.0, frame_interval - elapsed))
        finally:
            cap.release()
            print(f"stream ended: sent {seq} frames")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stream real webcam frames while sampling RSS/CPU of a running vision-analysis process"
    )
    parser.add_argument("--url", required=True, help="ws://host:port/ingest/session-id")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--duration-sec", type=float, required=True)
    parser.add_argument("--pid", type=int, required=True, help="PID of the running vision-analysis process")
    parser.add_argument("--rss-out", required=True)
    parser.add_argument("--sample-interval-sec", type=float, default=0.5)
    args = parser.parse_args()

    stop_event = threading.Event()
    monitor_thread = threading.Thread(
        target=_monitor_resources, args=(args.pid, args.rss_out, stop_event, args.sample_interval_sec), daemon=True
    )
    monitor_thread.start()

    try:
        asyncio.run(_stream(args.url, args.camera, args.duration_sec, args.fps))
    finally:
        stop_event.set()
        monitor_thread.join(timeout=5)


if __name__ == "__main__":
    main()
