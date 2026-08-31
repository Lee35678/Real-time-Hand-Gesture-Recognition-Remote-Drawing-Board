import asyncio
import json
import types

from app.transport import ingest_server


class _FakeWebSocket:
    """Minimal async-iterable stand-in for websockets.ServerConnection."""

    def __init__(self, path: str, messages: list):
        self.request = types.SimpleNamespace(path=path)
        self._messages = list(messages)
        self.closed_with = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

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
    handler = ingest_server._make_handler(_settings(max_malformed=3), metrics=None, out_queue=asyncio.Queue())

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

    handler = ingest_server._make_handler(_settings(max_malformed=2), metrics=None, out_queue=asyncio.Queue())

    payload = bytes(2 * 2 * 3)
    messages = [b"garbage", _valid_header_json(), payload, b"garbage"]
    ws = _FakeWebSocket("/ingest/sess-1", messages)
    asyncio.run(handler(ws))

    assert ws.closed_with is None
    assert len(fake_pipelines[0].offered) == 1
    assert fake_pipelines[0].closed is True


def test_unparseable_header_counts_as_malformed(monkeypatch):
    monkeypatch.setattr(ingest_server, "SessionPipeline", _FakePipeline)
    handler = ingest_server._make_handler(_settings(max_malformed=2), metrics=None, out_queue=asyncio.Queue())

    ws = _FakeWebSocket("/ingest/sess-1", ["not valid json", "still not valid"])
    asyncio.run(handler(ws))

    assert ws.closed_with == (1011, "too many malformed frames")
