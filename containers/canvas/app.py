"""Canvas service on 8762. Consumes C command JSON without changing gesture rules."""
from __future__ import annotations

import json
import logging
import struct

import cv2
import websockets
from canvas_config import ConfigValidationError, load_settings, validate
from canvas_logging_setup import configure_logging, set_session_id
from drawing_canvas import DrawingCanvas
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

settings=load_settings()
try:
    validate(settings)  # Fail Fast: 잘못된 설정이면 uvicorn 기동 자체가 실패한다 (Pillar 1-2)
except ConfigValidationError as exc:
    raise SystemExit(f"configuration rejected, refusing to start: {exc}") from exc
configure_logging(level=settings.log_level,log_format=settings.log_format,log_path=settings.log_path or None,max_bytes=settings.log_max_bytes,backup_count=settings.log_backup_count)
logger=logging.getLogger("canvas")
OUTPUT=settings.transport.web_canvas_output_url
app=FastAPI(title="Drawing Canvas"); canvases:dict[str,DrawingCanvas]={}
def pack(meta,data):
    raw=json.dumps(meta,separators=(",",":")).encode(); return struct.pack(">I",len(raw))+raw+data
def point(packet):
    p=packet.get("index_tip") or packet.get("pointer")
    if not isinstance(p,dict) or not all(isinstance(p.get(k),(int,float)) for k in ("x","y")): return None
    x,y=p["x"],p["y"]
    return (round(x*(settings.canvas.width-1)),round(y*(settings.canvas.height-1))) if 0<=x<=1 and 0<=y<=1 else (round(x),round(y))
def _new_canvas():
    c=settings.canvas
    return DrawingCanvas(c.width,c.height,zoom_step=c.zoom_step,min_zoom=c.min_zoom,max_zoom=c.max_zoom,pen_thickness=c.pen_thickness,eraser_radius=c.eraser_radius,min_draw_distance=c.min_draw_distance)
@app.get("/health")
async def health(): return {"status":"ok","sessions":len(canvases)}
@app.websocket("/commands/{session_id}")
async def commands(ws:WebSocket,session_id:str):
    set_session_id(session_id)
    await ws.accept(); canvas=canvases.setdefault(session_id,_new_canvas())
    logger.info("session %s: connected",session_id,extra={"event":"session_started"})
    try:
        async with websockets.connect(OUTPUT.format(session_id=session_id),max_size=None) as output:
            while True:
                raw=await ws.receive_text()
                try:
                    packet=json.loads(raw); command=str(packet.get("command","IDLE")); p=point(packet)
                    d=packet.get("index_direction") or {}; direction=(float(d["x"]),float(d["y"])) if "x" in d and "y" in d else None
                    canvas.apply(command,p,direction); ok,jpeg=cv2.imencode(".jpg",canvas.render(),[cv2.IMWRITE_JPEG_QUALITY,settings.canvas.jpeg_quality])
                    if ok: await output.send(pack({"kind":"canvas","session_id":session_id,"frame_id":packet.get("frame_id"),"seq":packet.get("seq"),"command":command,"mode":packet.get("mode","IDLE"),"zoom":round(canvas.zoom,3),"inference_ms":packet.get("inference_ms"),"landmarks":packet.get("landmarks")},jpeg.tobytes()))
                except (json.JSONDecodeError,KeyError,TypeError,ValueError):
                    # 명령 패킷 하나가 깨졌다고 세션 전체를 끊지 않는다 — 다음 패킷을 계속 기다린다.
                    logger.warning("session %s: dropping malformed command packet: %.200s",session_id,raw,extra={"event":"packet_dropped"})
    except WebSocketDisconnect:
        canvas.hide_cursor()
        logger.info("session %s: disconnected",session_id,extra={"event":"session_ended"})
    finally:
        set_session_id(None)
