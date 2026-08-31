"""Container A: mobile/web gateway. Inference belongs to container B."""
from __future__ import annotations

import io
import json
import logging
import os
import struct
import uuid
from pathlib import Path

import cv2
import numpy as np
import qrcode
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from logging_setup import configure_logging, set_session_id

ROOT=Path(__file__).resolve().parent; WEB_DIR=ROOT/"web"
VISION_URL=os.getenv("VISION_ANALYSIS_WS_URL","ws://vision-analysis:8760/ingest/{session_id}")
APP_ENV=os.getenv("APP_ENV","dev")
TOKEN=os.getenv("SESSION_TOKEN","hand-board"); PUBLIC=os.getenv("PUBLIC_BASE_URL","").rstrip("/")
if APP_ENV=="prod" and TOKEN=="hand-board":
    # Fail Fast (Pillar 1-2): the default token is public (it's in this source file),
    # so leaving it in prod would let anyone stream frames into someone else's session.
    raise SystemExit("configuration rejected, refusing to start: SESSION_TOKEN must be set when APP_ENV=prod (the default 'hand-board' is not secret)")
configure_logging(
    level=os.getenv("WEB_LOG_LEVEL","DEBUG" if APP_ENV=="dev" else "INFO"),
    log_format=os.getenv("WEB_LOG_FORMAT","console" if APP_ENV=="dev" else "json"),
    log_path=os.getenv("WEB_LOG_PATH") or None,
    max_bytes=int(os.getenv("WEB_LOG_MAX_BYTES") or 10*1024*1024),
    backup_count=int(os.getenv("WEB_LOG_BACKUP_COUNT") or 5),
)
logger=logging.getLogger("web")
clients: dict[str,set[WebSocket]]={}

def pack(meta:dict,data:bytes)->bytes:
    raw=json.dumps(meta,ensure_ascii=False,separators=(",",":")).encode(); return struct.pack(">I",len(raw))+raw+data
def unpack(payload:bytes)->tuple[dict,bytes]:
    if len(payload)<5: raise ValueError("short frame")
    n=struct.unpack(">I",payload[:4])[0]
    if n<=0 or 4+n>=len(payload): raise ValueError("invalid header length")
    return json.loads(payload[4:4+n]),payload[4+n:]
async def publish(session:str,payload:bytes)->None:
    stale=[]
    for ws in set(clients.get(session,set())):
        try: await ws.send_bytes(payload)
        except Exception as exc:  # one dead client must not abort broadcast to the rest
            logger.warning("session %s: dropping unreachable monitor client (%s)",session,exc,extra={"event":"broadcast_failed"})
            stale.append(ws)
    for ws in stale: clients.get(session,set()).discard(ws)

app=FastAPI(title="Remote Drawing Web Gateway")
@app.get("/",include_in_schema=False)
@app.get("/index.html",include_in_schema=False)
@app.get("/monitor",include_in_schema=False)
async def monitor_page(): return FileResponse(WEB_DIR/"index.html")
@app.get("/capture.html",include_in_schema=False)
async def capture_page(): return FileResponse(WEB_DIR/"capture.html")
@app.get("/api/config",include_in_schema=False)
async def config(): return JSONResponse({"session_token":TOKEN,"public_base_url":PUBLIC})
@app.get("/qr",include_in_schema=False)
async def qr(u:str):
    if not u.startswith(("http://","https://")): raise HTTPException(400,"invalid URL")
    image=qrcode.make(u); out=io.BytesIO(); image.save(out,"PNG"); return Response(out.getvalue(),media_type="image/png")
@app.get("/health")
async def health(): return {"status":"ok","role":"A-web-gateway"}

@app.websocket("/ws/camera")
async def camera(ws:WebSocket,t:str=""):
    if t!=TOKEN: await ws.close(code=1008,reason="invalid token"); return
    set_session_id(t)
    await ws.accept(); vision_url=VISION_URL.format(session_id=t)
    logger.info("session %s: camera connected",t,extra={"event":"camera_session_started"})
    try:
        async with websockets.connect(vision_url,max_size=None) as vision:
            while True:
                meta,jpeg=unpack(await ws.receive_bytes())
                frame=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
                if frame is None: continue
                h,w=frame.shape[:2]; frame_id=str(meta.get("frame_id") or uuid.uuid4())
                header={"schema_version":"1.0","session_id":t,"frame_id":frame_id,"seq":int(meta.get("seq",0)),"captured_at_ms":int(meta.get("captured_at_ms",0)),"width":w,"height":h,"channels":3,"dtype":"uint8","color_order":"BGR","byte_length":int(frame.nbytes)}
                # A→B: exactly one TEXT JSON header, then one BINARY raw BGR frame.
                await vision.send(json.dumps(header,separators=(",",":"))); await vision.send(frame.tobytes(order="C"))
                await publish(t,pack({**header,"kind":"source"},jpeg))
    except WebSocketDisconnect:
        logger.info("session %s: camera disconnected",t,extra={"event":"camera_session_ended"})
    except Exception as exc:
        logger.exception("session %s: camera session failed",t,extra={"event":"camera_session_error"})
        await ws.send_text(json.dumps({"error":str(exc)}))
    finally:
        set_session_id(None)

@app.websocket("/ws/canvas-output/{session_id}")
async def canvas_output(ws:WebSocket,session_id:str):
    await ws.accept()
    try:
        while True: await publish(session_id,await ws.receive_bytes())
    except WebSocketDisconnect: pass
@app.websocket("/ws/monitor")
async def monitor(ws:WebSocket,t:str=""):
    if t!=TOKEN: await ws.close(code=1008,reason="invalid token"); return
    await ws.accept(); clients.setdefault(t,set()).add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: clients.get(t,set()).discard(ws)
