import json
import logging

import pytest
from logging_setup import (
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
    set_frame_id(3)
    record = _make_record()

    _ContextFilter().filter(record)

    assert record.session_id == "sess-1"
    assert record.frame_id == 3


def test_json_formatter_produces_valid_json_with_expected_fields():
    set_session_id("sess-2")
    record = _make_record(msg="canvas connected")
    _ContextFilter().filter(record)
    record.event = "canvas_connected"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["session_id"] == "sess-2"
    assert payload["event"] == "canvas_connected"
    assert payload["message"] == "canvas connected"


def test_console_formatter_includes_context_when_present():
    set_session_id("sess-3")
    record = _make_record(msg="hello")
    _ContextFilter().filter(record)

    line = ConsoleFormatter().format(record)
    assert "session=sess-3" in line
    assert "hello" in line


@pytest.fixture
def _isolated_root_handlers():
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


def test_configure_logging_adds_rotating_file_handler_when_log_path_given(tmp_path, _isolated_root_handlers):
    log_file = tmp_path / "pattern-command.log"
    configure_logging(level="INFO", log_format="json", log_path=str(log_file))
    root = logging.getLogger()
    assert len(root.handlers) == 2

    logging.getLogger("app.test").info("hello")
    payload = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert payload["message"] == "hello"
