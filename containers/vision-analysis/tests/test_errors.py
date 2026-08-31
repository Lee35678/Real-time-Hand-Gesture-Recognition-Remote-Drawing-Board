import pytest

from app.errors import (
    CameraReadError,
    DeviceUnavailableError,
    EngineError,
    FatalError,
    InferenceTimeoutError,
    ModelLoadError,
    RecoverableError,
    SinkUnavailableError,
)


@pytest.mark.parametrize(
    "recoverable_cls", [CameraReadError, InferenceTimeoutError, SinkUnavailableError]
)
def test_recoverable_errors_are_recoverable_and_engine_errors(recoverable_cls):
    assert issubclass(recoverable_cls, RecoverableError)
    assert issubclass(recoverable_cls, EngineError)
    assert not issubclass(recoverable_cls, FatalError)


@pytest.mark.parametrize("fatal_cls", [ModelLoadError, DeviceUnavailableError])
def test_fatal_errors_are_fatal_and_engine_errors(fatal_cls):
    assert issubclass(fatal_cls, FatalError)
    assert issubclass(fatal_cls, EngineError)
    assert not issubclass(fatal_cls, RecoverableError)


def test_recoverable_and_fatal_are_disjoint_branches():
    assert not issubclass(RecoverableError, FatalError)
    assert not issubclass(FatalError, RecoverableError)
