"""Container C 스탠드인 (측정 전용) — Phase 0 §2.3 베이스라인 성능 측정.

`dev_pattern_sink.py`는 사람이 읽는 콘솔 출력용이라 측정에 쓸 수 없다. 이 스크립트는
수신한 각 LandmarkPacket의 seq/capture_ts/processed_ts/hand_present를 JSONL로
그대로 기록만 한다 — 지연시간 백분위수/드롭률 계산은 별도 분석 스크립트가 한다
(측정과 분석을 분리해 실시간 처리 중 계산 오버헤드가 측정값을 왜곡하지 않도록 함).

사용 예:
    python scripts/bench_e2e_sink.py --out docs/perf/run1.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from websockets.asyncio.server import ServerConnection, serve


def _make_handler(out_path: str):
    async def _handler(websocket: ServerConnection) -> None:
        # Single-connection measurement tool, not a scaled service — blocking
        # writes of one small JSON line per packet (<=30/s) never meaningfully
        # stall anything else on this event loop.
        with open(out_path, "a", encoding="utf-8") as fh:
            async for message in websocket:
                packet = json.loads(message)
                record = {
                    "recv_ts_ms": int(time.time() * 1000),
                    "seq": packet.get("seq"),
                    "capture_ts": packet.get("capture_ts"),
                    "processed_ts": packet.get("processed_ts"),
                    "hand_present": packet.get("hand_present"),
                }
                fh.write(json.dumps(record) + "\n")
                fh.flush()

    return _handler


async def run(host: str, port: int, out_path: str) -> None:
    handler = _make_handler(out_path)
    async with serve(handler, host, port) as server:
        print(f"bench sink listening on ws://{host}:{port}/landmarks -> {out_path}")
        await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Container C stand-in that logs raw packet timestamps for perf analysis"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8761)
    parser.add_argument("--out", required=True, help="JSONL output path (appended)")
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port, args.out))


if __name__ == "__main__":
    main()
