"""세션 단위 처리 파이프라인 (PRD 3장 전체, FR-B-04/09/11~16).

프레임 도착(동기, asyncio 루프 스레드) → 전처리 → MediaPipe 비동기 추론 제출.
추론 결과는 MediaPipe 내부 스레드의 콜백으로 도착하므로, 백그라운드 드레인 스레드가
이를 소비해 패킷으로 변환한 뒤 asyncio 루프로 안전하게 넘긴다.

동시에 하나의 프레임만 추론 중이도록 유지하고(latest-frame-wins, FR-B-04),
그 사이 도착한 프레임은 가장 최근 것만 남기고 버린다.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from ..config import Settings
from ..contracts import Handedness, LandmarkPacket, Quality
from ..observability.metrics import MetricsCollector
from ..vision.geometry import (
    LetterboxParams,
    Point,
    hand_scale,
    is_near_edge,
    max_displacement,
    unletterbox_landmarks,
)
from ..vision.landmarker import HandLandmarkerSession, LandmarkResult, make_mp_image
from ..vision.preprocess import prepare_for_inference
from ..vision.smoothing import HandLandmarksFilter

logger = logging.getLogger(__name__)


@dataclass
class _PendingFrame:
    session_id: str
    seq: int
    capture_ts: int
    width: int
    height: int
    mp_image: object
    params: LetterboxParams
    received_at_ns: int


class SessionPipeline:
    """카메라 세션 하나에 대응하는 처리 파이프라인. 세션 시작 시 생성, 종료 시 close()."""

    def __init__(
        self,
        settings: Settings,
        session_id: str,
        metrics: MetricsCollector,
        loop: asyncio.AbstractEventLoop,
        out_queue: asyncio.Queue[LandmarkPacket],
    ):
        self._settings = settings
        self._session_id = session_id
        self._metrics = metrics
        self._loop = loop
        self._out_queue = out_queue

        self._result_queue: queue.Queue[LandmarkResult] = queue.Queue()
        self._landmarker = HandLandmarkerSession(settings.model, self._result_queue)
        self._filter = HandLandmarksFilter(
            min_cutoff=settings.one_euro.min_cutoff,
            beta=settings.one_euro.beta,
            d_cutoff=settings.one_euro.d_cutoff,
        )

        self._lock = threading.Lock()
        self._inflight = False
        self._pending_frame: _PendingFrame | None = None
        self._context_by_ts: dict[int, _PendingFrame] = {}

        self._prev_landmarks: list[Point] | None = None
        self._hand_was_present = False

        self._closed = False
        self._drain_thread = threading.Thread(target=self._drain_loop, name=f"vision-drain-{session_id}", daemon=True)
        self._drain_thread.start()

    def offer_frame(
        self,
        seq: int,
        capture_ts: int,
        width: int,
        height: int,
        raw_frame: np.ndarray,
        pixel_format: str,
        rotation: int,
        mirrored: bool,
    ) -> None:
        """프레임 도착 시 호출된다. 처리 중이면 이전 대기 프레임을 버리고 최신 것으로 교체한다."""
        received_at_ns = time.perf_counter_ns()
        prepared, params = prepare_for_inference(
            raw_frame,
            pixel_format,
            rotation,
            mirrored,
            self._settings.pipeline.target_width,
            self._settings.pipeline.target_height,
            enable_clahe=self._settings.pipeline.enable_clahe,
        )
        self._metrics.record_stage("preprocess", (time.perf_counter_ns() - received_at_ns) / 1e6)
        pending = _PendingFrame(
            session_id=self._session_id,
            seq=seq,
            capture_ts=capture_ts,
            width=width,
            height=height,
            mp_image=make_mp_image(prepared),
            params=params,
            received_at_ns=received_at_ns,
        )

        with self._lock:
            if self._inflight:
                self._pending_frame = pending
                return
            self._submit_locked(pending)

    def _submit_locked(self, pending: _PendingFrame) -> None:
        self._inflight = True
        ts = self._landmarker.submit(pending.mp_image, pending.capture_ts)
        self._context_by_ts[ts] = pending

    def _drain_loop(self) -> None:
        poll_timeout = self._settings.pipeline.drain_poll_timeout_sec
        while not self._closed:
            try:
                result = self._result_queue.get(timeout=poll_timeout)
            except queue.Empty:
                continue

            packet = self._handle_result(result)

            with self._lock:
                self._inflight = False
                next_pending = self._pending_frame
                self._pending_frame = None
                if next_pending is not None:
                    self._submit_locked(next_pending)

            if packet is not None:
                self._loop.call_soon_threadsafe(self._enqueue_packet, packet)

    def _enqueue_packet(self, packet: LandmarkPacket) -> None:
        try:
            self._out_queue.put_nowait(packet)
        except asyncio.QueueFull:
            logger.warning("session %s: egress queue full, dropping packet seq=%s", self._session_id, packet.seq)

    def _handle_result(self, result: LandmarkResult) -> LandmarkPacket | None:
        ctx = self._context_by_ts.pop(result.timestamp_ms, None)
        if ctx is None:
            logger.warning("session %s: no context for timestamp %s", self._session_id, result.timestamp_ms)
            return None

        self._metrics.record_inference(result.inference_ms, result.hand_present)
        processed_ts = int(time.time() * 1000)

        if not result.hand_present:
            if self._hand_was_present:
                self._filter.reset()
                self._prev_landmarks = None
            self._hand_was_present = False
            packet = LandmarkPacket.absent(
                session_id=ctx.session_id,
                seq=ctx.seq,
                capture_ts=ctx.capture_ts,
                processed_ts=processed_ts,
                frame_w=ctx.width,
                frame_h=ctx.height,
            )
            self._metrics.record_stage("total", (time.perf_counter_ns() - ctx.received_at_ns) / 1e6)
            return packet

        # hand_present=True는 이 필드들이 채워졌음을 보장한다 (LandmarkResult 참고).
        assert result.landmarks is not None
        assert result.world_landmarks is not None
        assert result.handedness_label is not None
        assert result.handedness_score is not None
        landmarks = unletterbox_landmarks(result.landmarks, ctx.params)

        smoothing_start_ns = time.perf_counter_ns()
        filtered = self._filter.apply(landmarks, ctx.capture_ts)
        self._metrics.record_stage("smoothing", (time.perf_counter_ns() - smoothing_start_ns) / 1e6)

        postprocess_start_ns = time.perf_counter_ns()
        scale = hand_scale(filtered)
        near_edge = is_near_edge(filtered, self._settings.pipeline.near_edge_margin)

        outlier = False
        if self._prev_landmarks is not None and scale > 0:
            displacement = max_displacement(self._prev_landmarks, filtered)
            outlier = displacement > scale * self._settings.pipeline.outlier_scale_multiplier
        self._metrics.record_stage("postprocess", (time.perf_counter_ns() - postprocess_start_ns) / 1e6)

        if not outlier:
            self._prev_landmarks = filtered
        self._hand_was_present = True

        packet = LandmarkPacket.present(
            session_id=ctx.session_id,
            seq=ctx.seq,
            capture_ts=ctx.capture_ts,
            processed_ts=processed_ts,
            frame_w=ctx.width,
            frame_h=ctx.height,
            handedness=Handedness(result.handedness_label, result.handedness_score),
            landmarks=filtered,
            world_landmarks=list(result.world_landmarks),
            hand_scale=scale,
            quality=Quality(near_edge=near_edge, filtered=True, outlier_dropped=outlier),
        )
        self._metrics.record_stage("total", (time.perf_counter_ns() - ctx.received_at_ns) / 1e6)
        return packet

    def close(self) -> None:
        self._closed = True
        self._drain_thread.join(timeout=self._settings.pipeline.shutdown_join_timeout_sec)
        self._landmarker.close()
