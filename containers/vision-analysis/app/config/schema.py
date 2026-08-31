"""설정 스키마 검증 — Fail Fast (refactoring.md Pillar 1-2).

잘못된 설정은 프레임을 처리하다가 예외로 죽는 게 아니라 **기동 즉시** 명확한 메시지와
함께 실패해야 한다. `pydantic`으로 타입/범위/논리적 제약을 검증하고, 실패 시 어떤 키가
왜 잘못됐는지 사람이 읽을 수 있는 메시지로 변환한다.

모델 파일 존재 여부(`check_model_file`)는 기본적으로 검증하지만, 단위 테스트처럼
모델 바이너리 없이 설정 구조만 검증하고 싶은 경우 끌 수 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ValidationError, model_validator

if TYPE_CHECKING:
    from . import Settings


class ConfigValidationError(ValueError):
    """설정 검증 실패. main()은 이 예외를 잡아 즉시 종료해야 한다."""


class _ModelSchema(BaseModel):
    asset_path: str
    num_hands: int
    min_hand_detection_confidence: float
    min_hand_presence_confidence: float
    min_tracking_confidence: float
    delegate: Literal["CPU", "GPU"]

    @model_validator(mode="after")
    def _check_ranges(self) -> "_ModelSchema":
        for name in (
            "min_hand_detection_confidence",
            "min_hand_presence_confidence",
            "min_tracking_confidence",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"model.{name} must be within [0.0, 1.0], got {value}")
        if self.num_hands < 1:
            raise ValueError(f"model.num_hands must be >= 1, got {self.num_hands}")
        return self


class _PipelineSchema(BaseModel):
    target_width: int
    target_height: int
    target_fps: float
    enable_clahe: bool
    outlier_scale_multiplier: float
    near_edge_margin: float
    egress_queue_max_size: int
    drain_poll_timeout_sec: float
    shutdown_join_timeout_sec: float
    max_consecutive_malformed_frames: int

    @model_validator(mode="after")
    def _check_ranges(self) -> "_PipelineSchema":
        if self.target_width <= 0 or self.target_height <= 0:
            raise ValueError("pipeline.target_width/target_height must be positive")
        if self.target_fps <= 0.0:
            raise ValueError(f"pipeline.target_fps must be positive, got {self.target_fps}")
        if not 0.0 <= self.near_edge_margin < 0.5:
            raise ValueError(f"pipeline.near_edge_margin must be within [0.0, 0.5), got {self.near_edge_margin}")
        if self.egress_queue_max_size < 1:
            raise ValueError("pipeline.egress_queue_max_size must be >= 1")
        if self.max_consecutive_malformed_frames < 1:
            raise ValueError("pipeline.max_consecutive_malformed_frames must be >= 1")
        return self


class _OneEuroSchema(BaseModel):
    min_cutoff: float
    beta: float
    d_cutoff: float

    @model_validator(mode="after")
    def _check_ranges(self) -> "_OneEuroSchema":
        if self.min_cutoff <= 0.0 or self.d_cutoff <= 0.0:
            raise ValueError("one_euro.min_cutoff/d_cutoff must be positive")
        if self.beta < 0.0:
            raise ValueError("one_euro.beta must be >= 0")
        return self


class _TransportSchema(BaseModel):
    ingest_host: str
    ingest_port: int
    pattern_command_ws_url: str
    egress_reconnect_min_delay: float
    egress_reconnect_max_delay: float
    metrics_host: str
    metrics_port: int

    @model_validator(mode="after")
    def _check_ranges(self) -> "_TransportSchema":
        for name in ("ingest_port", "metrics_port"):
            port = getattr(self, name)
            if not 1 <= port <= 65535:
                raise ValueError(f"transport.{name} must be within [1, 65535], got {port}")
        if self.egress_reconnect_max_delay < self.egress_reconnect_min_delay:
            raise ValueError(
                "transport.egress_reconnect_max_delay must be >= egress_reconnect_min_delay "
                f"(got max={self.egress_reconnect_max_delay}, min={self.egress_reconnect_min_delay})"
            )
        return self


class _ObservabilitySchema(BaseModel):
    metrics_window_size: int
    palm_redetect_spike_ratio: float

    @model_validator(mode="after")
    def _check_ranges(self) -> "_ObservabilitySchema":
        if self.metrics_window_size < 1:
            raise ValueError("observability.metrics_window_size must be >= 1")
        if self.palm_redetect_spike_ratio <= 1.0:
            raise ValueError("observability.palm_redetect_spike_ratio must be > 1.0")
        return self


class _SettingsSchema(BaseModel):
    model: _ModelSchema
    pipeline: _PipelineSchema
    one_euro: _OneEuroSchema
    transport: _TransportSchema
    observability: _ObservabilitySchema
    log_level: Literal["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"]


def _settings_to_dict(settings: "Settings") -> dict:
    return {
        "model": vars(settings.model),
        "pipeline": vars(settings.pipeline),
        "one_euro": vars(settings.one_euro),
        "transport": vars(settings.transport),
        "observability": vars(settings.observability),
        "log_level": settings.log_level,
    }


def validate(settings: "Settings", *, check_model_file: bool = True) -> None:
    """설정을 검증한다. 실패 시 `ConfigValidationError`를 던진다.

    Args:
        check_model_file: True면 `model.asset_path`가 실제로 존재하는 파일인지도 확인한다
            (PRD FR-B-09, 9번 edge-case: `ModelLoadError`로 승격되기 전 단계의 선제 방어).
            단위 테스트에서 모델 바이너리 없이 설정 구조만 검증할 때는 False로 끈다.
    """
    try:
        _SettingsSchema.model_validate(_settings_to_dict(settings))
    except ValidationError as exc:
        messages = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigValidationError(f"invalid configuration - {messages}") from exc

    if check_model_file and not Path(settings.model.asset_path).is_file():
        raise ConfigValidationError(
            f"model.asset_path does not exist: {settings.model.asset_path} "
            "(run download_model.ps1 or check HAND_LANDMARKER_MODEL_PATH)"
        )
