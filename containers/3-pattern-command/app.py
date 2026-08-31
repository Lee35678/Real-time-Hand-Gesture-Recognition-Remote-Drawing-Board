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
from dataclasses import dataclass

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from config import load_settings
from gesture_classifier import GestureClassifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pattern-command")

settings = load_settings()

app = FastAPI(title="Pattern Command")


@dataclass(frozen=True)
class Landmark:
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
        self._canvas_ws = None

    async def _canvas(self):
        if self._canvas_ws is None:
            url = settings.transport.canvas_ws_url.format(session_id=self.session_id)
            self._canvas_ws = await websockets.connect(url, max_size=None)
            logger.info("session %s: connected to canvas at %s", self.session_id, url)
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
            logger.warning("session %s: canvas send failed (%s); will reconnect next packet", self.session_id, exc)
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
    logger.info("Container B connected")
    try:
        while True:
            raw = await ws.receive_text()
            try:
                packet = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("dropping malformed packet: %.200s", raw)
                continue

            session_id = packet.get("session_id")
            if not session_id:
                continue

            try:
                await _session(session_id).handle_packet(packet)
            except Exception:
                logger.exception("session %s: failed to handle packet", session_id)
    except WebSocketDisconnect:
        logger.info("Container B disconnected")
