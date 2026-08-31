"""표준화된 로깅 설정 (refactoring.md Pillar 4).

containers/vision-analysis/app/observability/logging.py와 동일한 설계를
그대로 옮겼다 — 컨테이너 간 공유 패키지가 없어 각자 자기 디렉터리 안에서
완결되는 모듈로 복제한다. 이 컨테이너(web)는 다른 컨테이너의 디렉터리를
sys.path에 얹지 않으므로 `canvas_logging_setup.py`처럼 이름을 바꿀 필요는
없다 — 그래도 파일 내용 자체는 동일하게 유지해 세 컨테이너의 로그 포맷이
어긋나지 않게 한다.

`session_id`(세션 토큰 `t`)는 `contextvars`로 주입한다 — 각 WebSocket 연결이
자신만의 asyncio 태스크로 실행되므로 태스크 생성 시점에 컨텍스트가 자연스럽게
전파된다.

개인정보 보호(Pillar 4-4): 이 모듈은 원본 프레임 이미지나 세션 토큰 원문을
로깅하지 않는다 — 호출부(app.py)가 그런 값을 로그 인자로 넘기지 않는 것으로
보장한다.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys

_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)
_frame_id_var: contextvars.ContextVar[object | None] = contextvars.ContextVar("frame_id", default=None)


def set_session_id(session_id: str | None) -> None:
    _session_id_var.set(session_id)


def set_frame_id(frame_id: object | None) -> None:
    _frame_id_var.set(frame_id)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = _session_id_var.get()
        record.frame_id = _frame_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "session_id": getattr(record, "session_id", None),
            "frame_id": getattr(record, "frame_id", None),
            "event": getattr(record, "event", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m",
}
_RESET = "\033[0m"


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, "")
        session_id = getattr(record, "session_id", None)
        frame_id = getattr(record, "frame_id", None)
        event = getattr(record, "event", None)
        ctx_parts = []
        if session_id is not None:
            ctx_parts.append(f"session={session_id}")
        if frame_id is not None:
            ctx_parts.append(f"frame={frame_id}")
        if event is not None:
            ctx_parts.append(f"event={event}")
        ctx = (" [" + " ".join(ctx_parts) + "]") if ctx_parts else ""
        prefix = f"{color}{record.levelname:<8}{_RESET}"
        base = f"{self.formatTime(record, '%H:%M:%S')} {prefix} {record.name}{ctx}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(
    *,
    level: str = "INFO",
    log_format: str = "console",
    log_path: str | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """루트 로거에 stdout 핸들러(+선택적 파일 로테이션 핸들러)를 붙인다.
    프로세스당 한 번, 기동 초입에서만 호출한다."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    formatter: logging.Formatter = JsonFormatter() if log_format == "json" else ConsoleFormatter()
    context_filter = _ContextFilter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    root.addHandler(stream_handler)

    if log_path:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)
