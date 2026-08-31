"""설정 스키마 검증 — Fail Fast (containers/vision-analysis/app/config/schema.py와 동일 패턴).

잘못된 설정은 첫 세션이 연결됐을 때 조용히 오작동하거나 `ValueError`로 죽는 게
아니라 **기동 즉시**(uvicorn이 `app.py`를 import하는 시점) 명확한 메시지와 함께
실패해야 한다. `GestureClassifier`/`IndexFingerClassifier` 생성자 자체에도 일부
검증이 있지만, 이 컨테이너는 세션이 처음 연결될 때(`SessionState.__init__`)
비로소 그 생성자를 호출하므로 그 검증만으로는 Fail Fast가 되지 않는다 — 여기서
기동 시점에 동일한 제약을 선제 검증한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ValidationError, model_validator

if TYPE_CHECKING:
    from config import Settings


class ConfigValidationError(ValueError):
    """설정 검증 실패. 모듈 임포트 시점(uvicorn 기동)에 그대로 전파되어 프로세스를 죽인다."""


class _GestureSchema(BaseModel):
    open_pip_angle_deg: float
    thumb_active_ratio: float
    zoom_start_closed_ratio: float
    zoom_start_open_ratio: float
    zoom_start_confirm_frames: int
    zoom_motion_ratio: float
    zoom_filter_alpha: float
    release_confirm_frames: int
    finger_window_size: int
    finger_required_open_votes: int

    @model_validator(mode="after")
    def _check_ranges(self) -> "_GestureSchema":
        if not 0.0 < self.open_pip_angle_deg < 180.0:
            raise ValueError(f"gesture.open_pip_angle_deg must be within (0, 180), got {self.open_pip_angle_deg}")
        if self.thumb_active_ratio <= 0.0:
            raise ValueError("gesture.thumb_active_ratio must be > 0")
        if self.zoom_start_open_ratio <= self.zoom_start_closed_ratio:
            raise ValueError(
                "gesture.zoom_start_open_ratio must be > zoom_start_closed_ratio "
                f"(got open={self.zoom_start_open_ratio}, closed={self.zoom_start_closed_ratio})"
            )
        if self.zoom_start_confirm_frames < 1:
            raise ValueError("gesture.zoom_start_confirm_frames must be >= 1")
        if self.zoom_motion_ratio <= 0.0:
            raise ValueError("gesture.zoom_motion_ratio must be > 0")
        if not 0.0 < self.zoom_filter_alpha <= 1.0:
            raise ValueError(f"gesture.zoom_filter_alpha must be within (0, 1], got {self.zoom_filter_alpha}")
        if self.release_confirm_frames < 1:
            raise ValueError("gesture.release_confirm_frames must be >= 1")
        if self.finger_window_size < 1:
            raise ValueError("gesture.finger_window_size must be >= 1")
        if not 1 <= self.finger_required_open_votes <= self.finger_window_size:
            raise ValueError(
                "gesture.finger_required_open_votes must be within [1, finger_window_size] "
                f"(got votes={self.finger_required_open_votes}, window={self.finger_window_size})"
            )
        return self


class _TransportSchema(BaseModel):
    canvas_ws_url: str

    @model_validator(mode="after")
    def _check_ranges(self) -> "_TransportSchema":
        if not self.canvas_ws_url:
            raise ValueError("transport.canvas_ws_url must not be empty")
        if "{session_id}" not in self.canvas_ws_url:
            raise ValueError(
                f"transport.canvas_ws_url must contain a '{{session_id}}' placeholder, got {self.canvas_ws_url!r}"
            )
        return self


class _SettingsSchema(BaseModel):
    gesture: _GestureSchema
    transport: _TransportSchema
    log_level: Literal["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"]
    log_format: Literal["console", "json"]
    log_path: str
    log_max_bytes: int
    log_backup_count: int

    @model_validator(mode="after")
    def _check_logging_ranges(self) -> "_SettingsSchema":
        if self.log_max_bytes < 1:
            raise ValueError("log_max_bytes must be >= 1")
        if self.log_backup_count < 0:
            raise ValueError("log_backup_count must be >= 0")
        return self


def _settings_to_dict(settings: "Settings") -> dict:
    return {
        "gesture": vars(settings.gesture),
        "transport": vars(settings.transport),
        "log_level": settings.log_level,
        "log_format": settings.log_format,
        "log_path": settings.log_path,
        "log_max_bytes": settings.log_max_bytes,
        "log_backup_count": settings.log_backup_count,
    }


def validate(settings: "Settings") -> None:
    """설정을 검증한다. 실패 시 `ConfigValidationError`를 던진다."""
    try:
        _SettingsSchema.model_validate(_settings_to_dict(settings))
    except ValidationError as exc:
        messages = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigValidationError(f"invalid configuration - {messages}") from exc
