import asyncio

import pytest

from app import main as main_module
from app.errors import ModelLoadError


class _FakeSettings:
    log_level = "INFO"
    log_format = "console"
    log_path = ""
    log_max_bytes = 10 * 1024 * 1024
    log_backup_count = 5
    model = object()


def test_main_exits_1_when_model_fails_to_load(monkeypatch):
    monkeypatch.setattr(main_module, "load_settings", lambda: _FakeSettings())
    monkeypatch.setattr(main_module, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(main_module, "validate", lambda settings: None)

    def _boom(model):
        raise ModelLoadError("simulated corrupt model")

    monkeypatch.setattr(main_module, "_verify_model_loads", _boom)

    def _run_should_not_be_called(settings):
        raise AssertionError("run(settings) must not start once model verification has failed")

    monkeypatch.setattr(main_module, "run", _run_should_not_be_called)
    monkeypatch.setattr(asyncio, "run", lambda coro: (_ for _ in ()).throw(AssertionError("asyncio.run must not be called")))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
