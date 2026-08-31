"""Container A → B 프레임 수신 서버.

프로토콜: ws://<host>:<port>/ingest/{session_id}
  1) TEXT  프레임 — IngestFrameHeader의 JSON 직렬화
  2) BINARY 프레임 — width*height*3 바이트의 RGB/BGR 픽셀 데이터 (직후에 이어짐)

세션(웹소켓 연결) 하나당 SessionPipeline 하나를 생성하고, 연결이 끊기면 해제한다.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..contracts import ContractError, IngestFrameHeader, LandmarkPacket
from ..errors import CameraReadError
from ..observability.logging import set_frame_id, set_session_id
from ..observability.metrics import MetricsCollector
from ..pipeline.runner import SessionPipeline

logger = logging.getLogger(__name__)


def _parse_session_id(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    if len(parts) == 2 and parts[0] == "ingest":
        return parts[1]
    return None


def _make_handler(settings: Settings, metrics: MetricsCollector, out_queue: "asyncio.Queue[LandmarkPacket]"):
    async def handler(websocket: ServerConnection) -> None:
        session_id = _parse_session_id(websocket.request.path)
        if session_id is None:
            await websocket.close(code=1008, reason="expected path /ingest/{session_id}")
            return

        set_session_id(session_id)
        loop = asyncio.get_running_loop()
        pipeline = SessionPipeline(settings, session_id, metrics, loop, out_queue)
        logger.info("ingest session started: %s", session_id, extra={"event": "session_started"})

        pending_header: IngestFrameHeader | None = None
        consecutive_malformed = 0
        max_malformed = settings.pipeline.max_consecutive_malformed_frames

        def _malformed(reason: str, *args: object) -> None:
            nonlocal consecutive_malformed
            consecutive_malformed += 1
            logger.warning(
                "session %s: " + reason, session_id, *args, extra={"event": "frame_dropped"}
            )
            if consecutive_malformed >= max_malformed:
                raise CameraReadError(
                    f"session {session_id}: {consecutive_malformed} consecutive malformed frames "
                    f"(limit {max_malformed}) — closing session"
                )

        try:
            async for message in websocket:
                if isinstance(message, (bytes, bytearray)):
                    if pending_header is None:
                        _malformed("binary frame received without header, dropping")
                        continue
                    header, pending_header = pending_header, None

                    if len(message) != header.expected_payload_size:
                        _malformed(
                            "seq=%s: payload size mismatch (expected %d, got %d)",
                            header.seq, header.expected_payload_size, len(message),
                        )
                        continue

                    set_frame_id(header.seq)
                    frame = np.frombuffer(message, dtype=np.uint8).reshape(header.height, header.width, 3)
                    pipeline.offer_frame(
                        seq=header.seq,
                        capture_ts=header.capture_ts,
                        width=header.width,
                        height=header.height,
                        raw_frame=frame,
                        pixel_format=header.pixel_format,
                        rotation=header.rotation,
                        mirrored=header.mirrored,
                    )
                    consecutive_malformed = 0
                else:
                    try:
                        pending_header = IngestFrameHeader.from_json(message)
                    except ContractError as exc:
                        pending_header = None
                        _malformed("%s", exc)
        except ConnectionClosed:
            pass
        except CameraReadError as exc:
            logger.error("session %s: %s", session_id, exc, extra={"event": "session_aborted"})
            await websocket.close(code=1011, reason="too many malformed frames")
        finally:
            pipeline.close()
            logger.info("ingest session ended: %s", session_id, extra={"event": "session_ended"})
            set_session_id(None)
            set_frame_id(None)

    return handler


async def run_ingest_server(
    settings: Settings, metrics: MetricsCollector, out_queue: "asyncio.Queue[LandmarkPacket]"
) -> None:
    handler = _make_handler(settings, metrics, out_queue)
    async with serve(handler, settings.transport.ingest_host, settings.transport.ingest_port, max_size=None) as server:
        logger.info(
            "ingest server listening on ws://%s:%d/ingest/{session_id}",
            settings.transport.ingest_host,
            settings.transport.ingest_port,
        )
        await server.wait_closed()
