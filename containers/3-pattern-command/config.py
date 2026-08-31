"""Container C (pattern-command) 런타임 설정.

값 우선순위: 환경변수 > 코드 기본값 (refactoring.md Pillar 1-1).

제스처 판정 임계값(GestureConfig)의 기본값은 리팩토링 이전 `gesture_classifier.py`/
`index_finger.py`의 하드코딩 값과 동일하다 — golden output 회귀 테스트가 아직 없는
상태이므로 값 자체는 바꾸지 않고, "코드에 박힌 상수"를 "환경변수로 오버라이드 가능한
기본값"으로만 승격한다 (refactoring.md 8절 금지사항 2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class GestureConfig:
    open_pip_angle_deg: float = field(
        default_factory=lambda: _env_float("GESTURE_OPEN_PIP_ANGLE_DEG", 120.0)
    )
    thumb_active_ratio: float = field(
        default_factory=lambda: _env_float("GESTURE_THUMB_ACTIVE_RATIO", 0.65)
    )
    zoom_start_closed_ratio: float = field(
        default_factory=lambda: _env_float("GESTURE_ZOOM_START_CLOSED_RATIO", 0.80)
    )
    zoom_start_open_ratio: float = field(
        default_factory=lambda: _env_float("GESTURE_ZOOM_START_OPEN_RATIO", 1.00)
    )
    zoom_start_confirm_frames: int = field(
        default_factory=lambda: _env_int("GESTURE_ZOOM_START_CONFIRM_FRAMES", 3)
    )
    zoom_motion_ratio: float = field(
        default_factory=lambda: _env_float("GESTURE_ZOOM_MOTION_RATIO", 0.05)
    )
    zoom_filter_alpha: float = field(
        default_factory=lambda: _env_float("GESTURE_ZOOM_FILTER_ALPHA", 1.0)
    )
    release_confirm_frames: int = field(
        default_factory=lambda: _env_int("GESTURE_RELEASE_CONFIRM_FRAMES", 3)
    )
    finger_window_size: int = field(
        default_factory=lambda: _env_int("GESTURE_FINGER_WINDOW_SIZE", 5)
    )
    finger_required_open_votes: int = field(
        default_factory=lambda: _env_int("GESTURE_FINGER_REQUIRED_OPEN_VOTES", 4)
    )


@dataclass(frozen=True)
class TransportConfig:
    canvas_ws_url: str = field(
        default_factory=lambda: _env_str("CANVAS_WS_URL", "ws://canvas:8762/commands/{session_id}")
    )


@dataclass(frozen=True)
class Settings:
    gesture: GestureConfig = field(default_factory=GestureConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)


def load_settings() -> Settings:
    return Settings()
