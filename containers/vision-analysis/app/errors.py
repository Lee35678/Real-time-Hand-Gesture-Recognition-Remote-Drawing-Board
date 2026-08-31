"""도메인 예외 계층 (refactoring.md Pillar 2-1).

- `RecoverableError`: 재시도/우회로 복구 가능 — 프로세스는 계속 살아있어야 한다.
- `FatalError`: 복구 불가능 — 즉시 종료 대상(Fail Fast).

규칙: `except Exception: pass`는 어디에도 쓰지 않는다. 모든 예외는 이 계층
중 하나로 분류해 로깅한 뒤 처리한다 (경계 catch가 필요한 곳도 항상 구체적인
타입을 잡고 `logger.exception`/`logger.warning`으로 남긴다).

이 컨테이너(vision-analysis)는 카메라를 직접 열지 않는다 — 카메라는
Container A(web)가 담당하고, 이미 캡처된 프레임을 WebSocket으로 수신한다.
`CameraReadError`/`DeviceUnavailableError`는 refactoring.md 원본 어휘를
그대로 쓰되, 실제 의미는 "수신한 프레임 데이터가 손상됨"/"모델 로드에 필요한
런타임 자체를 쓸 수 없음"으로 재해석했다 — 각 클래스 docstring 참고.
"""

from __future__ import annotations


class EngineError(Exception):
    """모든 vision-analysis 도메인 예외의 루트."""


# --- 복구 가능 (Recoverable) — 재시도/우회 대상 ---


class RecoverableError(EngineError):
    """재시도/우회로 복구 가능한 오류. 프로세스는 죽지 않는다."""


class CameraReadError(RecoverableError):
    """Container A로부터 수신한 프레임이 연속으로 손상됨(헤더 파싱 실패,
    페이로드 크기 불일치 등) — 물리 카메라가 아니라 ingest 스트림 자체가
    대상이다. 세션 하나를 계속 살려두되 원인 파악을 위해 WARN 이상으로 로깅한다.
    """


class InferenceTimeoutError(RecoverableError):
    """MediaPipe 추론이 예상 지연 예산을 초과함."""


class SinkUnavailableError(RecoverableError):
    """Container C(pattern-command) 연결 끊김. 재연결 루프(egress_client)가
    처리하며, 그동안 발생한 패킷은 로컬 스풀에 버퍼링한다."""


# --- 치명적 (Fatal) — 즉시 종료 대상 ---


class FatalError(EngineError):
    """복구 불가능한 오류. 기동 즉시 또는 감지 즉시 프로세스를 종료해야 한다."""


class ModelLoadError(FatalError):
    """MediaPipe Hand Landmarker 모델 파일이 없거나 손상되어 로드에 실패함."""


class DeviceUnavailableError(FatalError):
    """이 컨테이너에서는 발생하지 않는다(카메라 미보유) — refactoring.md
    원본 계층과의 이름 호환을 위해서만 정의해 둔다."""
