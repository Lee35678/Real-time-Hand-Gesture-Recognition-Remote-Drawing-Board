"""Container C: pattern/command engine.

Receives Container B's landmark packets on /landmarks (PRD 6.1 schema) and turns
hand pose into DRAW/ERASE/ZOOM_IN/ZOOM_OUT/IDLE commands using the existing rule
engine (gesture_classifier.py, index_finger.py), then forwards each command to the
canvas service for the same session.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from gesture_classifier import GestureClassifier
from logging_setup import configure_logging, set_session_id

from config import ConfigValidationError, load_settings, validate

settings = load_settings()
try:
    validate(settings)  # Fail Fast: 잘못된 설정이면 uvicorn 기동 자체가 실패한다 (Pillar 1-2)
except ConfigValidationError as exc:
    logging.basicConfig(level=logging.CRITICAL, format="%(message)s")
    # configure_logging() hasn't run yet here (config validation happens first,
    # deliberately) so there's no named logger to use.
    logging.critical("configuration rejected, refusing to start: %s", exc)
    raise SystemExit(1) from exc

configure_logging(
    level=settings.log_level,
    log_format=settings.log_format,
    log_path=settings.log_path or None,
    max_bytes=settings.log_max_bytes,
    backup_count=settings.log_backup_count,
)
logger = logging.getLogger("pattern-command")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    # Graceful shutdown (Pillar 2-5): close every session's canvas connection
    # instead of leaving them to drop silently when the process exits.
    logger.info(
        "shutting down: closing %d active session(s)", len(_sessions),
        extra={"event": "shutdown_requested"},
    )
    for state in list(_sessions.values()):
        await state.close()
    _sessions.clear()


app = FastAPI(title="Pattern Command", lifespan=_lifespan)


@dataclass
class Landmark:
    # frozen=True로 하지 않는다: index_finger.Landmark Protocol이 쓰기 가능한
    # x/y/z 속성을 요구해서, frozen dataclass는 구조적으로 이를 만족시키지 못한다.
    x: float
    y: float
    z: float


def _to_landmarks(raw: list[dict]) -> list[Landmark]:
    return [Landmark(p["x"], p["y"], p["z"]) for p in raw]


class SessionState:
    """Per-session gesture classifier state plus its outbound canvas connection."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.classifier = GestureClassifier(**dataclasses.asdict(settings.gesture))
        self._canvas_ws: websockets.ClientConnection | None = None

    async def _canvas(self):
        if self._canvas_ws is None:
            url = settings.transport.canvas_ws_url.format(session_id=self.session_id)
            self._canvas_ws = await websockets.connect(url, max_size=None)
            logger.info(
                "session %s: connected to canvas at %s", self.session_id, url,
                extra={"event": "canvas_connected"},
            )
        return self._canvas_ws

    async def handle_packet(self, packet: dict) -> None:
        if not packet.get("hand_present"):
            self.classifier.reset()
            await self._send_command("IDLE", None, None, None, packet, mode="IDLE")
            return

        world_landmarks = _to_landmarks(packet["world_landmarks"])
        state = self.classifier.update(world_landmarks)

        image_landmarks = packet["landmarks"]
        tip, pip = image_landmarks[8], image_landmarks[6]  # INDEX_TIP, INDEX_PIP
        index_tip = {"x": tip["x"], "y": tip["y"]}
        direction = {"x": tip["x"] - pip["x"], "y": tip["y"] - pip["y"]}

        await self._send_command(state.command, index_tip, direction, image_landmarks, packet, mode=state.mode)

    async def _send_command(self, command, index_tip, direction, landmarks, packet, mode) -> None:
        message = {
            "command": command,
            "mode": mode,
            "seq": packet.get("seq"),
            "index_tip": index_tip,
            "index_direction": direction,
            "landmarks": landmarks,  # 21 normalized {x,y,z} points, for a skeleton overlay on the monitor
        }
        try:
            ws = await self._canvas()
            await ws.send(json.dumps(message))
        except OSError as exc:
            logger.warning(
                "session %s: canvas send failed (%s); will reconnect next packet", self.session_id, exc,
                extra={"event": "canvas_send_failed"},
            )
            self._canvas_ws = None

    async def close(self) -> None:
        if self._canvas_ws is not None:
            await self._canvas_ws.close()
            self._canvas_ws = None


_sessions: dict[str, SessionState] = {}


def _session(session_id: str) -> SessionState:
    state = _sessions.get(session_id)
    if state is None:
        state = SessionState(session_id)
        _sessions[session_id] = state
    return state


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(_sessions)}


@app.websocket("/landmarks")
async def landmarks(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("Container B connected", extra={"event": "ingest_connected"})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                packet = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(
                    "dropping malformed packet: %.200s", raw, extra={"event": "packet_dropped"}
                )
                continue

            session_id = packet.get("session_id")
            if not session_id:
                continue

            set_session_id(session_id)
            try:
                await _session(session_id).handle_packet(packet)
            except Exception:
                logger.exception(
                    "session %s: failed to handle packet", session_id,
                    extra={"event": "packet_handling_failed"},
                )
    except WebSocketDisconnect:
        logger.info("Container B disconnected", extra={"event": "ingest_disconnected"})
    finally:
        set_session_id(None)
