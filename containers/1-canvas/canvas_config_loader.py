"""YAML + 환경변수 설정 로더 (containers/2-vision-analysis/app/config/loader.py와 동일 패턴).

우선순위(refactoring.md Pillar 1-1): 환경변수 > config/canvas.{APP_ENV}.yaml >
config/canvas.yaml > 코드 기본값.

`config/` 디렉토리 위치는 실행 환경에 따라 다르다:
- 로컬 개발(리포지토리에서 직접 실행): 리포지토리 루트의 `config/`
- Docker 이미지: `WORKDIR /app` 기준 `/app/config/`
  (Dockerfile이 `COPY config/canvas*.yaml ./config/`로 배치 — 이 컨테이너는
  vision-analysis와 달리 `app/` 하위 패키지 없이 파일이 `/app/` 바로 아래 평평하게 놓인다)

`CANVAS_CONFIG_DIR` 환경변수로 명시적으로 지정할 수도 있다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

_SERVICE_NAME = "canvas"


def _app_env() -> str:
    return os.environ.get("APP_ENV", "dev")


def _find_config_dir() -> Optional[Path]:
    override = os.environ.get("CANVAS_CONFIG_DIR")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_dir() else None

    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "config" if len(here.parents) > 2 else None,  # repo root (local dev)
        here.parents[0] / "config",  # /app/config (Docker: config_loader.py -> /app)
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def _merged_yaml() -> dict[str, Any]:
    config_dir = _find_config_dir()
    if config_dir is None:
        return {}
    base = _load_yaml_file(config_dir / f"{_SERVICE_NAME}.yaml")
    env_specific = _load_yaml_file(config_dir / f"{_SERVICE_NAME}.{_app_env()}.yaml")
    return _deep_merge(base, env_specific)


def yaml_value(*path: str) -> Any:
    """병합된 YAML 설정에서 점 경로(`path`)를 따라간 값을 반환한다. 없으면 None."""
    node: Any = _merged_yaml()
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def resolve_str(env_name: str, yaml_path: tuple[str, ...], default: str) -> str:
    if env_name in os.environ:
        return os.environ[env_name]
    value = yaml_value(*yaml_path)
    return str(value) if value is not None else default


def resolve_int(env_name: str, yaml_path: tuple[str, ...], default: int) -> int:
    if env_name in os.environ:
        return int(os.environ[env_name])
    value = yaml_value(*yaml_path)
    return int(value) if value is not None else default


def resolve_float(env_name: str, yaml_path: tuple[str, ...], default: float) -> float:
    if env_name in os.environ:
        return float(os.environ[env_name])
    value = yaml_value(*yaml_path)
    return float(value) if value is not None else default
