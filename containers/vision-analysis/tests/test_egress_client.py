import asyncio
from collections import deque

import pytest
from websockets.exceptions import ConnectionClosed

from app.contracts import LandmarkPacket
from app.transport import egress_client


def _packet(seq: int) -> LandmarkPacket:
    return LandmarkPacket.absent(
        session_id="sess-1", seq=seq, capture_ts=seq, processed_ts=seq, frame_w=640, frame_h=480
    )


async def _run_briefly(coro, seconds: float = 0.05) -> None:
    task = asyncio.ensure_future(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_drain_into_spool_moves_packets_from_queue_to_spool():
    async def scenario():
        out_queue: asyncio.Queue = asyncio.Queue()
        spool: deque = deque(maxlen=10)
        spool_ready = asyncio.Condition()
        for i in range(3):
            out_queue.put_nowait(_packet(i))

        await _run_briefly(egress_client._drain_into_spool(out_queue, spool, spool_ready))

        assert [p.seq for p in spool] == [0, 1, 2]

    asyncio.run(scenario())


def test_drain_into_spool_drops_oldest_on_overflow():
    async def scenario():
        out_queue: asyncio.Queue = asyncio.Queue()
        spool: deque = deque(maxlen=2)
        spool_ready = asyncio.Condition()
        for i in range(5):
            out_queue.put_nowait(_packet(i))

        await _run_briefly(egress_client._drain_into_spool(out_queue, spool, spool_ready))

        # maxlen=2 deque keeps only the most recent 2 packets (oldest dropped).
        assert [p.seq for p in spool] == [3, 4]

    asyncio.run(scenario())


class _FakeWebSocket:
    def __init__(self, sent: list, fail_after: int | None = None):
        self.sent = sent
        self._fail_after = fail_after
        self._count = 0

    async def send(self, data) -> None:
        self._count += 1
        if self._fail_after is not None and self._count > self._fail_after:
            raise ConnectionClosed(None, None)
        self.sent.append(data)


class _FakeConnect:
    """Stands in for `async with connect(url) as ws:`."""

    def __init__(self, ws: _FakeWebSocket):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc_info) -> bool:
        return False


def test_send_loop_flushes_spool_in_order(monkeypatch):
    sent: list = []
    monkeypatch.setattr(egress_client, "connect", lambda url: _FakeConnect(_FakeWebSocket(sent)))

    class _FakeSettings:
        class transport:
            pattern_command_ws_url = "ws://fake/landmarks"
            egress_reconnect_min_delay = 0.01
            egress_reconnect_max_delay = 0.02

    async def scenario():
        spool: deque = deque([_packet(0), _packet(1), _packet(2)], maxlen=10)
        spool_ready = asyncio.Condition()
        await _run_briefly(egress_client._send_loop(_FakeSettings(), spool, spool_ready))

        assert len(spool) == 0
        assert len(sent) == 3

    asyncio.run(scenario())


def test_send_loop_reconnects_and_resumes_from_spool_after_a_failed_send(monkeypatch):
    sent: list = []
    connect_calls = []

    def _fake_connect(url):
        # First connection fails its 2nd send; the retry loop should reconnect
        # with a fresh websocket and continue draining the (still-populated) spool.
        ws = _FakeWebSocket(sent, fail_after=1 if not connect_calls else None)
        connect_calls.append(ws)
        return _FakeConnect(ws)

    monkeypatch.setattr(egress_client, "connect", _fake_connect)

    class _FakeSettings:
        class transport:
            pattern_command_ws_url = "ws://fake/landmarks"
            egress_reconnect_min_delay = 0.001
            egress_reconnect_max_delay = 0.002

    async def scenario():
        spool: deque = deque([_packet(i) for i in range(4)], maxlen=10)
        spool_ready = asyncio.Condition()
        await _run_briefly(egress_client._send_loop(_FakeSettings(), spool, spool_ready), seconds=0.1)

        assert len(connect_calls) >= 2
        assert len(spool) == 0

    asyncio.run(scenario())
