"""표준화된 로깅 설정 (refactoring.md Pillar 4).

- `log_format="json"`: 운영 환경 — 구조화된 JSON 한 줄씩
  (ts/level/logger/session_id/frame_id/event/message).
- `log_format="console"`: 개발 환경 — 사람이 읽기 쉬운 컬러 텍스트.

`session_id`/`frame_id`는 `contextvars`로 주입한다 — MediaPipe 콜백 스레드와
asyncio 이벤트 루프 경계를 넘나드는 이 코드베이스에서 매번 `LoggerAdapter`를
넘겨 다니는 것보다 contextvars가 더 자연스럽게 전파된다. 아직 값이 설정되지
않은 컨텍스트(기동 직후 등)에서는 필드를 비워둔다.

개인정보 보호(Pillar 4-4): 이 모듈은 원본 프레임 이미지나 랜드마크 원시 좌표를
로깅하지 않는다 — 호출부(pipeline/runner.py 등)가 애초에 그런 값을 로그 인자로
넘기지 않는 것으로 보장한다. 이 파일은 포맷/전송만 담당한다.
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
    """모든 로그 레코드에 현재 session_id/frame_id를 붙인다."""

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

    프로세스당 한 번, 기동 초입에서만 호출한다. `log_path`가 주어지면 컨테이너
    환경에서도 파일 핸들러를 쓸 수 있지만(4-3), stdout 핸들러는 항상 붙는다 —
    컨테이너 오케스트레이터는 보통 stdout을 수집하기 때문이다.
    """
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
        # 파일은 항상 구조화 — 수집/파싱 대상이지 사람이 tail하는 용도가 아니다
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(context_filter)
        root.addHandler(file_handler)
