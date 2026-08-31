import asyncio

import app as app_module


async def _run_shutdown() -> None:
    """Drives app.py's real `_lifespan` context manager through the shutdown
    half (everything after `yield`) the same way FastAPI/uvicorn would."""
    async with app_module._lifespan(app_module.app):
        pass


class _FakeCanvasWebSocket:
    def __init__(self):
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_shutdown_closes_every_session_and_clears_the_registry():
    app_module._sessions.clear()

    session_a = app_module.SessionState("sess-a")
    ws_a = _FakeCanvasWebSocket()
    session_a._canvas_ws = ws_a  # type: ignore[assignment]  # 덕타이핑 fake
    session_b = app_module.SessionState("sess-b")
    ws_b = _FakeCanvasWebSocket()
    session_b._canvas_ws = ws_b  # type: ignore[assignment]  # 덕타이핑 fake
    app_module._sessions["sess-a"] = session_a
    app_module._sessions["sess-b"] = session_b

    asyncio.run(_run_shutdown())

    assert ws_a.closed is True
    assert ws_b.closed is True
    assert session_a._canvas_ws is None
    assert session_b._canvas_ws is None
    assert app_module._sessions == {}


def test_shutdown_is_a_no_op_when_no_sessions_are_active():
    app_module._sessions.clear()

    asyncio.run(_run_shutdown())

    assert app_module._sessions == {}
