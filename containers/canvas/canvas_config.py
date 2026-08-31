"""Container D (canvas) 런타임 설정.

값의 우선순위(refactoring.md Pillar 1-1): 환경변수 > config/canvas.{APP_ENV}.yaml >
config/canvas.yaml > 이 파일의 코드 기본값 (containers/vision-analysis/app/config/__init__.py
와 동일 패턴).

`CanvasConfig`의 기본값은 리팩토링 이전 `drawing_canvas.py::DrawingCanvas.__init__`
및 `app.py`(360x640, JPEG quality 88)의 하드코딩 값과 동일하다 — 값 자체는 바꾸지
않고 오버라이드 가능하게만 승격한다 (refactoring.md 8절 금지사항 2).

`app.py` 임포트 시점에 `validate(settings)`를 호출해 Fail Fast 검증을 수행한다
(Pillar 1-2, `canvas_config_schema.py`).

모듈명이 `config.py`가 아니라 `canvas_config.py`인 이유: `drawing_canvas.py`가
`containers/pattern-command`를 `sys.path`에 얹어 `gesture_classifier`를 가져오는데,
그 디렉터리에도 동일 목적의 `config.py`/`config_loader.py`/`config_schema.py`가
있다 — 이름이 같으면 어느 쪽이 임포트될지가 sys.path 순서에 좌우되어 엉뚱한
`TransportConfig`(canvas_ws_url)가 로드될 수 있다. 파일명을 이 컨테이너 전용으로
분리해 그 충돌을 원천 차단한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from canvas_config_loader import resolve_float, resolve_int, resolve_str
from canvas_config_schema import ConfigValidationError, validate

__all__ = [
    "CanvasConfig",
    "TransportConfig",
    "Settings",
    "load_settings",
    "validate",
    "ConfigValidationError",
]


@dataclass(frozen=True)
class CanvasConfig:
    width: int = field(default_factory=lambda: resolve_int("CANVAS_WIDTH", ("canvas", "width"), 360))
    height: int = field(default_factory=lambda: resolve_int("CANVAS_HEIGHT", ("canvas", "height"), 640))
    zoom_step: float = field(
        default_factory=lambda: resolve_float("CANVAS_ZOOM_STEP", ("canvas", "zoom_step"), 1.05)
    )
    min_zoom: float = field(
        default_factory=lambda: resolve_float("CANVAS_MIN_ZOOM", ("canvas", "min_zoom"), 1.0)
    )
    max_zoom: float = field(
        default_factory=lambda: resolve_float("CANVAS_MAX_ZOOM", ("canvas", "max_zoom"), 4.0)
    )
    pen_thickness: int = field(
        default_factory=lambda: resolve_int("CANVAS_PEN_THICKNESS", ("canvas", "pen_thickness"), 4)
    )
    eraser_radius: int = field(
        default_factory=lambda: resolve_int("CANVAS_ERASER_RADIUS", ("canvas", "eraser_radius"), 24)
    )
    min_draw_distance: float = field(
        default_factory=lambda: resolve_float(
            "CANVAS_MIN_DRAW_DISTANCE", ("canvas", "min_draw_distance"), 2.0
        )
    )
    jpeg_quality: int = field(
        default_factory=lambda: resolve_int("CANVAS_JPEG_QUALITY", ("canvas", "jpeg_quality"), 88)
    )


@dataclass(frozen=True)
class TransportConfig:
    web_canvas_output_url: str = field(
        default_factory=lambda: resolve_str(
            "WEB_CANVAS_OUTPUT_URL",
            ("transport", "web_canvas_output_url"),
            "ws://web:8000/ws/canvas-output/{session_id}",
        )
    )


@dataclass(frozen=True)
class Settings:
    canvas: CanvasConfig = field(default_factory=CanvasConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)


def load_settings() -> Settings:
    return Settings()
