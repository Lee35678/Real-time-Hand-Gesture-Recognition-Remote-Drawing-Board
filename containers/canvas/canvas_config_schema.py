"""설정 스키마 검증 — Fail Fast (containers/vision-analysis/app/config/schema.py와 동일 패턴).

잘못된 설정은 첫 명령이 도착했을 때 캔버스가 이상하게 그려지거나 죽는 게 아니라
**기동 즉시**(uvicorn이 `app.py`를 import하는 시점) 명확한 메시지와 함께 실패해야
한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError, model_validator

if TYPE_CHECKING:
    from canvas_config import Settings


class ConfigValidationError(ValueError):
    """설정 검증 실패. 모듈 임포트 시점(uvicorn 기동)에 그대로 전파되어 프로세스를 죽인다."""


class _CanvasSchema(BaseModel):
    width: int
    height: int
    zoom_step: float
    min_zoom: float
    max_zoom: float
    pen_thickness: int
    eraser_radius: int
    min_draw_distance: float
    jpeg_quality: int

    @model_validator(mode="after")
    def _check_ranges(self) -> "_CanvasSchema":
        if self.width <= 0 or self.height <= 0:
            raise ValueError("canvas.width/height must be positive")
        if self.zoom_step <= 1.0:
            raise ValueError(f"canvas.zoom_step must be > 1.0 (each ZOOM_IN multiplies by it), got {self.zoom_step}")
        if self.min_zoom <= 0.0:
            raise ValueError("canvas.min_zoom must be > 0")
        if self.max_zoom <= self.min_zoom:
            raise ValueError(
                f"canvas.max_zoom must be > min_zoom (got max={self.max_zoom}, min={self.min_zoom})"
            )
        if self.pen_thickness < 1:
            raise ValueError("canvas.pen_thickness must be >= 1")
        if self.eraser_radius < 1:
            raise ValueError("canvas.eraser_radius must be >= 1")
        if self.min_draw_distance < 0.0:
            raise ValueError("canvas.min_draw_distance must be >= 0")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError(f"canvas.jpeg_quality must be within [1, 100], got {self.jpeg_quality}")
        return self


class _TransportSchema(BaseModel):
    web_canvas_output_url: str

    @model_validator(mode="after")
    def _check_ranges(self) -> "_TransportSchema":
        if not self.web_canvas_output_url:
            raise ValueError("transport.web_canvas_output_url must not be empty")
        if "{session_id}" not in self.web_canvas_output_url:
            raise ValueError(
                "transport.web_canvas_output_url must contain a '{session_id}' placeholder, "
                f"got {self.web_canvas_output_url!r}"
            )
        return self


class _SettingsSchema(BaseModel):
    canvas: _CanvasSchema
    transport: _TransportSchema


def _settings_to_dict(settings: "Settings") -> dict:
    return {
        "canvas": vars(settings.canvas),
        "transport": vars(settings.transport),
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
