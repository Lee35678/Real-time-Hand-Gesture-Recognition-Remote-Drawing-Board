import json
import logging

import pytest

from app.observability.logging import (
    ConsoleFormatter,
    JsonFormatter,
    _ContextFilter,
    configure_logging,
    set_frame_id,
    set_session_id,
)


def _make_record(msg="hello", level=logging.INFO, exc_info=None):
    return logging.LogRecord(
        name="app.test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=exc_info,
    )


@pytest.fixture(autouse=True)
def _reset_context():
    set_session_id(None)
    set_frame_id(None)
    yield
    set_session_id(None)
    set_frame_id(None)


def test_context_filter_injects_session_and_frame_id():
    set_session_id("sess-1")
    set_frame_id(42)
    record = _make_record()

    _ContextFilter().filter(record)

    assert record.session_id == "sess-1"
    assert record.frame_id == 42


def test_context_filter_defaults_to_none_when_unset():
    record = _make_record()
    _ContextFilter().filter(record)
    assert record.session_id is None
    assert record.frame_id is None


def test_json_formatter_produces_valid_json_with_expected_fields():
    set_session_id("sess-2")
    set_frame_id(7)
    record = _make_record(msg="frame dropped")
    _ContextFilter().filter(record)
    record.event = "frame_dropped"

    line = JsonFormatter().format(record)
    payload = json.loads(line)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["session_id"] == "sess-2"
    assert payload["frame_id"] == 7
    assert payload["event"] == "frame_dropped"
    assert payload["message"] == "frame dropped"
    assert "ts" in payload


def test_json_formatter_includes_exception_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(msg="failed", level=logging.ERROR, exc_info=sys.exc_info())
    _ContextFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc_info"]


def test_console_formatter_includes_context_when_present():
    set_session_id("sess-3")
    record = _make_record(msg="hello")
    _ContextFilter().filter(record)

    line = ConsoleFormatter().format(record)
    assert "session=sess-3" in line
    assert "hello" in line


def test_console_formatter_omits_context_brackets_when_unset():
    record = _make_record(msg="hello")
    _ContextFilter().filter(record)

    line = ConsoleFormatter().format(record)
    assert "session=" not in line
    assert "frame=" not in line
    assert "event=" not in line


@pytest.fixture
def _isolated_root_handlers():
    """configure_logging() mutates the global root logger — snapshot/restore
    around each test that calls it so other test files' logging (e.g.
    caplog-based tests elsewhere) aren't affected by leftover handlers."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    for h in root.handlers:
        h.close()
    root.handlers = original_handlers
    root.setLevel(original_level)


def test_configure_logging_adds_only_stream_handler_by_default(_isolated_root_handlers):
    configure_logging(level="INFO", log_format="console")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)


def test_configure_logging_adds_rotating_file_handler_when_log_path_given(tmp_path, _isolated_root_handlers):
    log_file = tmp_path / "engine.log"
    configure_logging(level="INFO", log_format="json", log_path=str(log_file))
    root = logging.getLogger()
    assert len(root.handlers) == 2

    logging.getLogger("app.test").info("hello")
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    payload = json.loads(content)
    assert payload["message"] == "hello"
