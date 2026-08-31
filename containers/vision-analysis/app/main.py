"""Container B (영상 분석 엔진) 진입점.

- ingest server : Container A → B 프레임 수신 (ws://.../ingest/{session_id})
- egress client : B → Container C 좌표 패킷 전송
- metrics server: /health, /metrics (FR-B-17)
"""

from __future__ import annotations

import asyncio
import logging
import queue
import signal
import sys

from .config import ConfigValidationError, ModelConfig, Settings, load_settings, validate
from .contracts import LandmarkPacket
from .errors import ModelLoadError
from .observability.metrics import MetricsCollector, run_metrics_http_server
from .transport.egress_client import run_egress_client
from .transport.ingest_server import run_ingest_server
from .vision.landmarker import HandLandmarkerSession, LandmarkResult

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    metrics = MetricsCollector(
        window_size=settings.observability.metrics_window_size,
        redetect_spike_ratio=settings.observability.palm_redetect_spike_ratio,
    )
    run_metrics_http_server(metrics, settings.transport.metrics_host, settings.transport.metrics_port)

    out_queue: "asyncio.Queue[LandmarkPacket]" = asyncio.Queue(maxsize=settings.pipeline.egress_queue_max_size)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_ingest_server(settings, metrics, out_queue), name="ingest-server")
        tg.create_task(run_egress_client(settings, out_queue), name="egress-client")

        loop = asyncio.get_running_loop()
        stop = loop.create_future()

        def _request_shutdown() -> None:
            if not stop.done():
                logger.info("shutdown signal received")
                stop.set_result(None)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                pass  # Windows에서 SIGTERM 핸들러 등록 불가 — Ctrl+C(SIGINT)만 지원

        await stop
        raise SystemExit(0)


def _verify_model_loads(model: ModelConfig) -> None:
    """모델 파일이 존재해도 손상되어 있으면 로드에 실패할 수 있다 (PRD edge
    case #9). schema.py의 Fail-Fast는 파일 존재 여부만 확인하므로(mediapipe
    의존성을 피하려는 의도적 설계), 여기서 실제로 한 번 만들어보고 즉시
    닫아 검증한다. 세션당 재사용은 8.3 함정이므로 이 인스턴스는 검증
    용도로만 쓰고 버린다."""
    probe_queue: "queue.Queue[LandmarkResult]" = queue.Queue()
    session = HandLandmarkerSession(model, probe_queue)
    session.close()


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        validate(settings)
    except ConfigValidationError as exc:
        logger.critical("configuration rejected, refusing to start: %s", exc)
        sys.exit(1)
    try:
        _verify_model_loads(settings.model)
    except ModelLoadError as exc:
        logger.critical("model failed to load, refusing to start: %s", exc)
        sys.exit(1)
    try:
        asyncio.run(run(settings))
    except (SystemExit, KeyboardInterrupt):
        logger.info("vision-analysis shutting down")


if __name__ == "__main__":
    main()
