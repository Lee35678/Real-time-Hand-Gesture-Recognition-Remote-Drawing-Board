"""표준화된 로깅 설정 (refactoring.md Pillar 4).

containers/vision-analysis/app/observability/logging.py와 동일한 설계를
그대로 옮겼다 — 두 컨테이너가 공유하는 패키지가 없어 각자 자기 디렉터리
안에서 완결되는 모듈로 복제한다(config.py/config_loader.py/config_schema.py와
같은 이유, docs/00_hardcoded_inventory.md 참고).

모듈명이 `logging_setup.py`가 아니라 `canvas_logging_setup.py`인 이유는
`canvas_config.py`가 이미 같은 이유로 이름을 바꾼 것과 동일하다 — `drawing_canvas.py`가
`containers/pattern-command`를 `sys.path`에 얹는데, 그 디렉터리에도 동일 목적의
`logging_setup.py`가 있다. 이름이 같으면 sys.path 순서에 따라 엉뚱한 모듈이
로드될 수 있어(실제로 config.py에서 이 문제를 겪었다) 컨테이너 전용 이름으로
분리했다.

`session_id`는 `contextvars`로 주입한다 — 이 컨테이너는 세션(연결)마다 자신만의
asyncio 태스크로 실행되므로, 태스크 생성 시점에 컨텍스트가 자연스럽게 전파된다.

개인정보 보호(Pillar 4-4): 이 모듈은 원본 좌표나 이미지를 로깅하지 않는다 —
호출부(app.py)가 그런 값을 로그 인자로 넘기지 않는 것으로 보장한다.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys
from typing import Optional

_session_id_var: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("session_id", default=None)
_frame_id_var: "contextvars.ContextVar[Optional[object]]" = contextvars.ContextVar("frame_id", default=None)


def set_session_id(session_id: Optional[str]) -> None:
    _session_id_var.set(session_id)


def set_frame_id(frame_id: Optional[object]) -> None:
    _frame_id_var.set(frame_id)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = _session_id_var.get()  # type: ignore[attr-defined]
        record.frame_id = _frame_id_var.get()  # type: ignore[attr-defined]
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
    log_path: Optional[str] = None,
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
