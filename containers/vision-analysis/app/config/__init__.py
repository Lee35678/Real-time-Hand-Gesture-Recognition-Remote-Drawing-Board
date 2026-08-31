"""Container B (vision-analysis) 런타임 설정.

값의 우선순위(refactoring.md Pillar 1-1): 환경변수 > config/vision-analysis.{APP_ENV}.yaml
> config/vision-analysis.yaml > 이 파일의 코드 기본값. 코드 기본값은 YAML 파일을 찾지
못하는 예외적인 상황(예: 배포 스크립트 오류)에서도 서비스가 PRD 4장 권장값으로 기동할
수 있도록 남겨둔 안전망이며, 정상 운영에서는 `config/vision-analysis.yaml`이 실제 값의
출처다.

기동 직후 `validate(settings)`를 호출해 Fail Fast 검증을 수행한다 (Pillar 1-2, `app/config/schema.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .loader import resolve_bool, resolve_float, resolve_int, resolve_str
from .schema import ConfigValidationError, validate

__all__ = [
    "ModelConfig",
    "PipelineConfig",
    "OneEuroConfig",
    "TransportConfig",
    "ObservabilityConfig",
    "Settings",
    "load_settings",
    "validate",
    "ConfigValidationError",
]


@dataclass(frozen=True)
class ModelConfig:
    """PRD 4장 — Hand Landmarker 설정 파라미터."""

    asset_path: str = field(default_factory=lambda: resolve_str(
        "HAND_LANDMARKER_MODEL_PATH", ("model", "asset_path"), "models/hand_landmarker.task"
    ))
    num_hands: int = field(
        default_factory=lambda: resolve_int("VISION_NUM_HANDS", ("model", "num_hands"), 1)
    )
    min_hand_detection_confidence: float = field(
        default_factory=lambda: resolve_float(
            "VISION_MIN_DETECTION_CONFIDENCE", ("model", "min_hand_detection_confidence"), 0.7
        )
    )
    min_hand_presence_confidence: float = field(
        default_factory=lambda: resolve_float(
            "VISION_MIN_PRESENCE_CONFIDENCE", ("model", "min_hand_presence_confidence"), 0.6
        )
    )
    min_tracking_confidence: float = field(
        default_factory=lambda: resolve_float(
            "VISION_MIN_TRACKING_CONFIDENCE", ("model", "min_tracking_confidence"), 0.5
        )
    )
    delegate: str = field(
        default_factory=lambda: resolve_str("VISION_DELEGATE", ("model", "delegate"), "CPU")
    )


@dataclass(frozen=True)
class PipelineConfig:
    """PRD 3장 — 전처리/후처리 파이프라인 설정."""

    target_width: int = field(
        default_factory=lambda: resolve_int("VISION_TARGET_WIDTH", ("pipeline", "target_width"), 640)
    )
    target_height: int = field(
        default_factory=lambda: resolve_int("VISION_TARGET_HEIGHT", ("pipeline", "target_height"), 480)
    )
    target_fps: float = field(
        default_factory=lambda: resolve_float("VISION_TARGET_FPS", ("pipeline", "target_fps"), 30.0)
    )
    enable_clahe: bool = field(
        default_factory=lambda: resolve_bool("VISION_ENABLE_CLAHE", ("pipeline", "enable_clahe"), False)
    )
    outlier_scale_multiplier: float = field(
        default_factory=lambda: resolve_float(
            "VISION_OUTLIER_SCALE_MULTIPLIER", ("pipeline", "outlier_scale_multiplier"), 4.0
        )
    )
    near_edge_margin: float = field(
        default_factory=lambda: resolve_float(
            "VISION_NEAR_EDGE_MARGIN", ("pipeline", "near_edge_margin"), 0.03
        )
    )
    egress_queue_max_size: int = field(
        default_factory=lambda: resolve_int(
            "VISION_EGRESS_QUEUE_MAX_SIZE", ("pipeline", "egress_queue_max_size"), 8
        )
    )
    drain_poll_timeout_sec: float = field(
        default_factory=lambda: resolve_float(
            "VISION_DRAIN_POLL_TIMEOUT_SEC", ("pipeline", "drain_poll_timeout_sec"), 0.5
        )
    )
    shutdown_join_timeout_sec: float = field(
        default_factory=lambda: resolve_float(
            "VISION_SHUTDOWN_JOIN_TIMEOUT_SEC", ("pipeline", "shutdown_join_timeout_sec"), 2.0
        )
    )
    max_consecutive_malformed_frames: int = field(
        default_factory=lambda: resolve_int(
            "VISION_MAX_CONSECUTIVE_MALFORMED_FRAMES", ("pipeline", "max_consecutive_malformed_frames"), 30
        )
    )


@dataclass(frozen=True)
class OneEuroConfig:
    """PRD 8.2 — One Euro Filter 튜닝 파라미터."""

    min_cutoff: float = field(
        default_factory=lambda: resolve_float("VISION_EURO_MIN_CUTOFF", ("one_euro", "min_cutoff"), 1.0)
    )
    beta: float = field(
        default_factory=lambda: resolve_float("VISION_EURO_BETA", ("one_euro", "beta"), 0.3)
    )
    d_cutoff: float = field(
        default_factory=lambda: resolve_float("VISION_EURO_D_CUTOFF", ("one_euro", "d_cutoff"), 1.0)
    )


@dataclass(frozen=True)
class TransportConfig:
    """Container A(ingest)/C(egress) 연결 설정.

    Container A는 이 서버로 프레임을 스트리밍하고(WebSocket 클라이언트),
    Container B는 결과 패킷을 Container C로 스트리밍한다(WebSocket 클라이언트).
    """

    ingest_host: str = field(
        default_factory=lambda: resolve_str("VISION_INGEST_HOST", ("transport", "ingest_host"), "0.0.0.0")
    )
    ingest_port: int = field(
        default_factory=lambda: resolve_int("VISION_INGEST_PORT", ("transport", "ingest_port"), 8760)
    )
    pattern_command_ws_url: str = field(
        default_factory=lambda: resolve_str(
            "PATTERN_COMMAND_WS_URL",
            ("transport", "pattern_command_ws_url"),
            "ws://pattern-command:8761/landmarks",
        )
    )
    egress_reconnect_min_delay: float = field(
        default_factory=lambda: resolve_float(
            "VISION_EGRESS_RECONNECT_MIN_DELAY", ("transport", "egress_reconnect_min_delay"), 0.5
        )
    )
    egress_reconnect_max_delay: float = field(
        default_factory=lambda: resolve_float(
            "VISION_EGRESS_RECONNECT_MAX_DELAY", ("transport", "egress_reconnect_max_delay"), 10.0
        )
    )
    egress_spool_max_events: int = field(
        default_factory=lambda: resolve_int(
            "VISION_EGRESS_SPOOL_MAX_EVENTS", ("transport", "egress_spool_max_events"), 1000
        )
    )
    metrics_host: str = field(
        default_factory=lambda: resolve_str("VISION_METRICS_HOST", ("transport", "metrics_host"), "0.0.0.0")
    )
    metrics_port: int = field(
        default_factory=lambda: resolve_int("VISION_METRICS_PORT", ("transport", "metrics_port"), 8763)
    )


@dataclass(frozen=True)
class ObservabilityConfig:
    """관측성 파라미터 (FR-B-17). 이전에는 metrics.py에 모듈 상수로 박혀 있었다."""

    metrics_window_size: int = field(
        default_factory=lambda: resolve_int(
            "VISION_METRICS_WINDOW_SIZE", ("observability", "metrics_window_size"), 300
        )
    )
    palm_redetect_spike_ratio: float = field(
        default_factory=lambda: resolve_float(
            "VISION_PALM_REDETECT_SPIKE_RATIO", ("observability", "palm_redetect_spike_ratio"), 2.0
        )
    )
    target_latency_budget_ms: float = field(
        default_factory=lambda: resolve_float(
            "VISION_TARGET_LATENCY_BUDGET_MS", ("observability", "target_latency_budget_ms"), 50.0
        )
    )
    stage_log_every_n_frames: int = field(
        default_factory=lambda: resolve_int(
            "VISION_STAGE_LOG_EVERY_N_FRAMES", ("observability", "stage_log_every_n_frames"), 100
        )
    )


@dataclass(frozen=True)
class Settings:
    model: ModelConfig = field(default_factory=ModelConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    one_euro: OneEuroConfig = field(default_factory=OneEuroConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    log_level: str = field(default_factory=lambda: resolve_str("VISION_LOG_LEVEL", ("log_level",), "INFO"))
    log_format: str = field(default_factory=lambda: resolve_str("VISION_LOG_FORMAT", ("log_format",), "console"))
    log_path: str = field(default_factory=lambda: resolve_str("VISION_LOG_PATH", ("log_path",), ""))
    log_max_bytes: int = field(
        default_factory=lambda: resolve_int("VISION_LOG_MAX_BYTES", ("log_rotation", "max_bytes"), 10 * 1024 * 1024)
    )
    log_backup_count: int = field(
        default_factory=lambda: resolve_int("VISION_LOG_BACKUP_COUNT", ("log_rotation", "backup_count"), 5)
    )


def load_settings() -> Settings:
    return Settings()
