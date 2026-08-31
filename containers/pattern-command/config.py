"""Container C (pattern-command) 런타임 설정.

값의 우선순위(refactoring.md Pillar 1-1): 환경변수 > config/pattern-command.{APP_ENV}.yaml
> config/pattern-command.yaml > 이 파일의 코드 기본값. 코드 기본값은 YAML 파일을 찾지
못하는 예외적인 상황에서도 서비스가 리팩토링 이전과 동일한 값으로 기동할 수 있도록
남겨둔 안전망이며, 정상 운영에서는 `config/pattern-command.yaml`이 실제 값의 출처다
(containers/vision-analysis/app/config/__init__.py와 동일 패턴).

제스처 판정 임계값(GestureConfig)의 기본값은 리팩토링 이전 `gesture_classifier.py`/
`index_finger.py`의 하드코딩 값과 동일하다 — characterization 스냅샷
(tests/fixtures/characterization.json)이 이 값을 기준으로 고정되어 있으므로 값
자체는 바꾸지 않고, "코드에 박힌 상수"를 "환경변수/YAML로 오버라이드 가능한
기본값"으로만 승격한다 (refactoring.md 8절 금지사항 2).

`app.py` 임포트 시점에 `validate(settings)`를 호출해 Fail Fast 검증을 수행한다
(Pillar 1-2, `config_schema.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config_loader import resolve_float, resolve_int, resolve_str
from config_schema import ConfigValidationError, validate

__all__ = [
    "GestureConfig",
    "TransportConfig",
    "Settings",
    "load_settings",
    "validate",
    "ConfigValidationError",
]


@dataclass(frozen=True)
class GestureConfig:
    open_pip_angle_deg: float = field(
        default_factory=lambda: resolve_float(
            "GESTURE_OPEN_PIP_ANGLE_DEG", ("gesture", "open_pip_angle_deg"), 120.0
        )
    )
    thumb_active_ratio: float = field(
        default_factory=lambda: resolve_float(
            "GESTURE_THUMB_ACTIVE_RATIO", ("gesture", "thumb_active_ratio"), 0.65
        )
    )
    zoom_start_closed_ratio: float = field(
        default_factory=lambda: resolve_float(
            "GESTURE_ZOOM_START_CLOSED_RATIO", ("gesture", "zoom_start_closed_ratio"), 0.80
        )
    )
    zoom_start_open_ratio: float = field(
        default_factory=lambda: resolve_float(
            "GESTURE_ZOOM_START_OPEN_RATIO", ("gesture", "zoom_start_open_ratio"), 1.00
        )
    )
    zoom_start_confirm_frames: int = field(
        default_factory=lambda: resolve_int(
            "GESTURE_ZOOM_START_CONFIRM_FRAMES", ("gesture", "zoom_start_confirm_frames"), 3
        )
    )
    zoom_motion_ratio: float = field(
        default_factory=lambda: resolve_float(
            "GESTURE_ZOOM_MOTION_RATIO", ("gesture", "zoom_motion_ratio"), 0.05
        )
    )
    zoom_filter_alpha: float = field(
        default_factory=lambda: resolve_float(
            "GESTURE_ZOOM_FILTER_ALPHA", ("gesture", "zoom_filter_alpha"), 1.0
        )
    )
    release_confirm_frames: int = field(
        default_factory=lambda: resolve_int(
            "GESTURE_RELEASE_CONFIRM_FRAMES", ("gesture", "release_confirm_frames"), 3
        )
    )
    finger_window_size: int = field(
        default_factory=lambda: resolve_int(
            "GESTURE_FINGER_WINDOW_SIZE", ("gesture", "finger_window_size"), 5
        )
    )
    finger_required_open_votes: int = field(
        default_factory=lambda: resolve_int(
            "GESTURE_FINGER_REQUIRED_OPEN_VOTES", ("gesture", "finger_required_open_votes"), 4
        )
    )


@dataclass(frozen=True)
class TransportConfig:
    canvas_ws_url: str = field(
        default_factory=lambda: resolve_str(
            "CANVAS_WS_URL", ("transport", "canvas_ws_url"), "ws://canvas:8762/commands/{session_id}"
        )
    )


@dataclass(frozen=True)
class Settings:
    gesture: GestureConfig = field(default_factory=GestureConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    log_level: str = field(
        default_factory=lambda: resolve_str("PATTERN_COMMAND_LOG_LEVEL", ("log_level",), "INFO")
    )
    log_format: str = field(
        default_factory=lambda: resolve_str("PATTERN_COMMAND_LOG_FORMAT", ("log_format",), "console")
    )
    log_path: str = field(
        default_factory=lambda: resolve_str("PATTERN_COMMAND_LOG_PATH", ("log_path",), "")
    )
    log_max_bytes: int = field(
        default_factory=lambda: resolve_int(
            "PATTERN_COMMAND_LOG_MAX_BYTES", ("log_rotation", "max_bytes"), 10 * 1024 * 1024
        )
    )
    log_backup_count: int = field(
        default_factory=lambda: resolve_int(
            "PATTERN_COMMAND_LOG_BACKUP_COUNT", ("log_rotation", "backup_count"), 5
        )
    )


def load_settings() -> Settings:
    return Settings()
