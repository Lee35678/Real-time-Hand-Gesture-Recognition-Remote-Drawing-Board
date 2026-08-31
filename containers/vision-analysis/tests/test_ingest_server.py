import asyncio
import contextlib
import json
import types

from app.transport import ingest_server


class _FakeWebSocket:
    """Minimal async-iterable stand-in for websockets.ServerConnection.

    `hang=True` makes __anext__ block forever once messages run out, instead
    of ending iteration — simulating an open, idle connection so a test can
    cancel the handler task the way TaskGroup cancellation would.
    """

    def __init__(self, path: str, messages: list, hang: bool = False):
        self.request = types.SimpleNamespace(path=path)
        self._messages = list(messages)
        self._hang = hang
        self.closed_with: tuple | None = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self._hang:
            await asyncio.Event().wait()
        raise StopAsyncIteration

    async def close(self, code=None, reason=None):
        self.closed_with = (code, reason)


class _FakePipeline:
    """Stands in for SessionPipeline so no real MediaPipe/HandLandmarker is built."""

    def __init__(self, *args, **kwargs):
        self.offered = []
        self.closed = False

    def offer_frame(self, **kwargs):
        self.offered.append(kwargs)

    def close(self) -> None:
        self.closed = True


def _settings(max_malformed: int):
    return types.SimpleNamespace(pipeline=types.SimpleNamespace(max_consecutive_malformed_frames=max_malformed))


def _valid_header_json(width: int = 2, height: int = 2) -> str:
    return json.dumps(
        {
            "session_id": "sess-1",
            "seq": 1,
            "captured_at_ms": 0,
            "width": width,
            "height": height,
            "dtype": "uint8",
            "channels": 3,
            "color_order": "BGR",
        }
    )


def test_session_closes_after_max_consecutive_malformed_frames(monkeypatch):
    monkeypatch.setattr(ingest_server, "SessionPipeline", _FakePipeline)
    handler = ingest_server._make_handler(_settings(max_malformed=3), metrics=None, out_queue=asyncio.Queue())  # type: ignore[arg-type]  # _FakePipeline은 metrics를 쓰지 않음

    ws = _FakeWebSocket("/ingest/sess-1", [b"garbage"] * 5)
    asyncio.run(handler(ws))

    assert ws.closed_with == (1011, "too many malformed frames")


def test_valid_frame_resets_the_malformed_counter(monkeypatch):
    monkeypatch.setattr(ingest_server, "SessionPipeline", _FakePipeline)
    fake_pipelines: list[_FakePipeline] = []
    original_init = _FakePipeline.__init__

    def _track_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        fake_pipelines.append(self)

    monkeypatch.setattr(_FakePipeline, "__init__", _track_init)

    handler = ingest_server._make_handler(_settings(max_malformed=2), metrics=None, out_queue=asyncio.Queue())  # type: ignore[arg-type]  # _FakePipeline은 metrics를 쓰지 않음

    payload = bytes(2 * 2 * 3)
    messages = [b"garbage", _valid_header_json(), payload, b"garbage"]
    ws = _FakeWebSocket("/ingest/sess-1", messages)
    asyncio.run(handler(ws))

    assert ws.closed_with is None
    assert len(fake_pipelines[0].offered) == 1
    assert fake_pipelines[0].closed is True


def test_unparseable_header_counts_as_malformed(monkeypatch):
    monkeypatch.setattr(ingest_server, "SessionPipeline", _FakePipeline)
    handler = ingest_server._make_handler(_settings(max_malformed=2), metrics=None, out_queue=asyncio.Queue())  # type: ignore[arg-type]  # _FakePipeline은 metrics를 쓰지 않음

    ws = _FakeWebSocket("/ingest/sess-1", ["not valid json", "still not valid"])
    asyncio.run(handler(ws))

    assert ws.closed_with == (1011, "too many malformed frames")


def test_cancelling_the_handler_still_closes_the_pipeline(monkeypatch):
    """Graceful shutdown (Pillar 2-5) relies on `finally: pipeline.close()`
    actually running when the process-wide TaskGroup cancels an in-flight
    session on SIGINT/SIGTERM — this proves that mechanism, rather than
    trusting it by inspection."""
    fake_pipelines: list[_FakePipeline] = []
    original_init = _FakePipeline.__init__

    def _track_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        fake_pipelines.append(self)

    monkeypatch.setattr(_FakePipeline, "__init__", _track_init)
    monkeypatch.setattr(ingest_server, "SessionPipeline", _FakePipeline)
    handler = ingest_server._make_handler(_settings(max_malformed=30), metrics=None, out_queue=asyncio.Queue())  # type: ignore[arg-type]  # _FakePipeline은 metrics를 쓰지 않음
    ws = _FakeWebSocket("/ingest/sess-1", messages=[], hang=True)

    async def scenario():
        task = asyncio.ensure_future(handler(ws))
        await asyncio.sleep(0.02)  # let the handler reach the hanging `async for`
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert len(fake_pipelines) == 1
    assert fake_pipelines[0].closed is True
