"""Container B → C 결과 패킷 전송 클라이언트.

Container C가 준비되기 전에도 B는 독립적으로 기동/재시도할 수 있어야 한다
(마이크로서비스 경계 — 2장 핵심 참조). 연결이 끊기면 지수 백오프+지터로
재연결한다.

파이프라인이 만든 패킷을 받는 쪽(`_drain_into_spool`)과 C로 실제 전송하는 쪽
(`_send_loop`)을 분리해 로컬 스풀(deque)로 잇는다 (refactoring.md Pillar 2-4):
연결이 끊긴 동안에도 패킷은 계속 스풀에 쌓이고, 재연결되면 도착 순서 그대로
플러시된다. 스풀이 가득 차면 `collections.deque(maxlen=...)`가 가장 오래된
항목을 자동으로 버린다 — "최신 우선 유지" 정책 그대로다.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..contracts import LandmarkPacket

logger = logging.getLogger(__name__)


async def _drain_into_spool(
    out_queue: "asyncio.Queue[LandmarkPacket]",
    spool: "deque[LandmarkPacket]",
    spool_ready: asyncio.Condition,
) -> None:
    while True:
        packet = await out_queue.get()
        async with spool_ready:
            if len(spool) >= spool.maxlen:
                logger.warning(
                    "egress spool full (%d events); dropping oldest spooled packet for seq=%s",
                    spool.maxlen, packet.seq, extra={"event": "spool_overflow"},
                )
            spool.append(packet)  # maxlen deque auto-evicts the oldest (leftmost) entry
            spool_ready.notify_all()


async def _send_loop(
    settings: Settings,
    spool: "deque[LandmarkPacket]",
    spool_ready: asyncio.Condition,
) -> None:
    url = settings.transport.pattern_command_ws_url
    delay = settings.transport.egress_reconnect_min_delay
    max_delay = settings.transport.egress_reconnect_max_delay

    while True:
        try:
            async with connect(url) as ws:
                logger.info(
                    "egress connected to %s (%d spooled packet(s) pending)", url, len(spool),
                    extra={"event": "egress_connected"},
                )
                delay = settings.transport.egress_reconnect_min_delay
                while True:
                    async with spool_ready:
                        await spool_ready.wait_for(lambda: len(spool) > 0)
                        packet = spool.popleft()
                    await ws.send(packet.to_json())
        except asyncio.CancelledError:
            raise
        except (ConnectionClosed, OSError) as exc:
            jittered = delay + random.uniform(0, delay * 0.25)
            logger.warning(
                "egress connection to %s failed (%s); retrying in %.1fs", url, exc, jittered,
                extra={"event": "egress_disconnected"},
            )
            await asyncio.sleep(jittered)
            delay = min(delay * 2, max_delay)


async def run_egress_client(settings: Settings, out_queue: "asyncio.Queue[LandmarkPacket]") -> None:
    spool: "deque[LandmarkPacket]" = deque(maxlen=settings.transport.egress_spool_max_events)
    spool_ready = asyncio.Condition()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_drain_into_spool(out_queue, spool, spool_ready), name="egress-spool-drain")
        tg.create_task(_send_loop(settings, spool, spool_ready), name="egress-send")
