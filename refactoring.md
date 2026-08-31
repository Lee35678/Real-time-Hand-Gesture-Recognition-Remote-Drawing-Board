# 프로덕션 레벨 파이프라인 구축
## MediaPipe Hand Tracking 기반 비접촉식 실시간 제스처 드로잉 인터페이스

> **PoC를 넘어 실무형 아키텍처로 — 개인 프로젝트 고도화(Refining) 청사진**

---

## 0. 이 문서의 목적 (Claude Code 작업 지시서)

이 문서는 **신규 기능 개발 지시서가 아니다.**
이미 동작하는 PoC 코드를 **실무 환경에서 즉시 운영(Operate) 가능한 수준의 프로덕션 레벨 코드로 승격**시키기 위한 리팩토링 작업 지시서다.

### Claude Code에게 주는 지침

```
1. 이 문서의 Phase 0부터 순서대로 진행한다. Phase를 건너뛰지 않는다.
2. 각 Phase는 반드시 "커밋 가능한 상태"로 끝나야 한다.
3. 기존 코드의 "동작 결과"를 바꾸지 않는다. 구조와 견고성만 바꾼다.
   - 제스처 인식 정확도/판정 로직은 회귀 테스트 없이 변경 금지.
4. 새로운 기능(신규 제스처, 신규 UI 등)을 추가하지 않는다.
5. 각 Phase 완료 시 변경 요약과 다음 Phase 진입 가능 여부를 보고한다.
6. CD(자동 배포)는 이 프로젝트 범위에서 제외한다. CI만 구축한다.
```

### 핵심 원칙: 20 / 80

| 구분 | 비중 | 내용 |
|---|---|---|
| 돌아가는 코드 (Working Code) | **20%** | MediaPipe 추론, 제스처 판정 로직 — **이미 완료됨** |
| 실무를 지탱하는 기반 (Production Infrastructure) | **80%** | 파라미터화, 예외 처리, 성능/메모리, 로깅, 자동 검증 — **이번 작업 범위** |

**"무엇을 만들 것인가"에서 "어떻게 벼려낼 것인가"로 포커스 이동.**

---

## 1. 프로젝트 컨텍스트

### 1.1 대상 시스템

**Container B — 영상 분석 엔진 (Video Analysis Engine)**

3-Container 아키텍처 중 본 저장소가 담당하는 영역:

```
[Container A]              [Container B — 본 저장소]              [Container C]
 프론트엔드/입력    ──►     프레임 수신                              드로잉 렌더러
                            → MediaPipe Hand Landmarker
                            → One Euro Filter 스무딩          ──►   좌표/이벤트 수신
                            → 제스처 상태 판정                        캔버스 렌더링
                            → 정규화 좌표 + 이벤트 발행
```

### 1.2 현재 확정된 기술 결정 (변경 금지)

이미 검증된 설계 결정이므로 **리팩토링 과정에서 임의로 교체하지 않는다.**

| 항목 | 결정 사항 | 이유 |
|---|---|---|
| 랜드마크 추출 | MediaPipe **Hand Landmarker (Tasks API)** | Solutions API는 deprecated |
| 실행 모드 | **`LIVE_STREAM`** | 비동기 콜백 기반, 실시간 처리에 필수 |
| 스무딩 | **One Euro Filter** | 저속 시 지터 억제 + 고속 시 지연 최소화 |
| 거리 측정 기준 | **`hand_world_landmarks`** | 카메라 거리에 무관한 미터 단위 측정 (핀치 판정의 근거) |
| 인터페이스 | Container A/C와의 **엄격한 계약(Contract)** | 스키마 버전 명시, 임의 변경 금지 |

> ⚠️ `hand_landmarks`(정규화 좌표)와 `hand_world_landmarks`(미터 단위)를 혼용하지 말 것.
> **화면 표시 좌표 = `hand_landmarks`, 핀치/거리 판정 = `hand_world_landmarks`**

---

## 2. Phase 0 — 진단 및 베이스라인 확보 (최우선)

> **리팩토링 전에 반드시 현재 상태를 계측한다. 측정 없는 최적화는 금지.**

### 2.1 코드 인벤토리 작성

`docs/00_baseline.md` 파일을 생성하고 아래 내용을 채운다.

- [ ] 전체 파일 목록 / 파일별 LoC / 각 파일의 책임 1줄 요약
- [ ] 진입점(entrypoint) 및 실행 흐름 다이어그램(텍스트)
- [ ] 외부 의존성 목록 (`requirements.txt` 또는 실제 import 기준)
- [ ] Container A/C와 주고받는 데이터의 **현재 실제 스키마** (코드에서 역추출)

### 2.2 하드코딩 전수 조사

아래 항목을 **전부 grep으로 찾아 목록화**한다. 이 목록이 Pillar 1의 작업 대상이 된다.

```bash
# 예시 탐색 대상
- 숫자 리터럴: 0.5, 640, 480, 30, 21, 0.035 등 (매직 넘버)
- 경로 문자열: "model.task", "./output", "C:\\..." 등
- 네트워크 주소: localhost, 127.0.0.1, ws://, 포트 번호
- 카메라 인덱스: cv2.VideoCapture(0)
- 임계값: threshold, confidence, min_/max_ 접두 변수
```

산출물: `docs/00_hardcoded_inventory.md` (파일:라인 / 현재값 / 제안 설정키 / 우선순위)

### 2.3 베이스라인 성능 측정

리팩토링 전 수치를 반드시 기록한다. Phase 3의 개선 근거이자 회귀 판단 기준이다.

- [ ] **E2E 지연 시간**: 프레임 획득 → 좌표 발행까지 (p50 / p95 / p99, ms)
- [ ] **단계별 지연 분해**: 캡처 / 전처리 / 추론 / 스무딩 / 판정 / 전송
- [ ] **처리 FPS**: 입력 FPS 대비 실제 처리 FPS, 드롭률
- [ ] **메모리**: 시작 시 RSS, 10분 연속 구동 후 RSS (증가량 확인)
- [ ] **CPU 점유율**: 평균 / 피크

산출물: `docs/00_baseline_metrics.md`

> **측정 방법 (테스트 영상 없음 전제)**: 실 웹캠으로 측정하되, 재현성을 위해 아래 규칙을 지킨다.
>
> - **고정 프레임 수**로 측정한다 (예: 1,000프레임). "몇 분간" 같은 시간 기준은 쓰지 않는다.
> - 동일 조건으로 **3회 반복**하고 **중앙값**을 기록한다. 회차 간 편차가 20%를 넘으면 측정 환경부터 정리한다.
> - 조명 / 카메라 거리 / 배경 조건을 `docs/00_baseline_metrics.md`에 함께 기록한다.
> - 추론을 제외한 **파이프라인 순수 오버헤드**는 `SyntheticSource`(합성 프레임)로 별도 측정해 분리 기록한다.
>   이 값은 카메라 환경과 무관하므로 완전히 재현 가능하다.
>
> 실측 특성상 완벽한 재현은 불가능하므로, **성능 판정은 절대값이 아니라 "베이스라인 대비 악화 여부"로만
> 내린다.** 5% 내외의 미세한 개선/악화는 유의미한 결과로 취급하지 않는다.

### 2.4 특성화 테스트(Characterization Test) 작성 — 영상 없는 안전장치

**가장 중요한 안전장치.** 리팩토링이 동작을 바꾸지 않았음을 증명하는 근거.

테스트 영상이 없으므로 **실영상 기반 E2E 회귀는 구축하지 않는다.** 대신 이 프로젝트의 판정 로직은
결국 **랜드마크 좌표 배열 → 스무딩 → 상태 전이**라는 순수 계산이므로, 입력 좌표를 **코드로 합성**하면
카메라도 영상도 없이 결정론적으로 검증할 수 있다.

**Step 1. 합성 랜드마크 시퀀스 생성기 작성** → `tests/fixtures/synthetic_sequences.py`

`numpy`로 21개 랜드마크의 시간축 궤적을 직접 만든다. 아래 6종은 필수로 구현한다.

| 시퀀스 | 내용 | 검증 목적 |
|---|---|---|
| `pinch_approach_release` | 엄지–검지 거리 0.08m → 0.02m → 0.08m 선형 변화 | 핀치 진입/해제 판정 |
| `threshold_chatter` | 임계값 부근에서 ±0.003m 진동 | **히스테리시스 + 디바운스** 동작 |
| `hand_lost_midway` | 중간 20프레임이 빈 결과(`[]`) | 손 소실 타임아웃, 스트로크 강제 종료 |
| `fast_swipe` | 프레임당 큰 변위로 급격히 이동 | One Euro Filter 지연 특성 |
| `static_jitter` | 정지 상태 + 가우시안 노이즈 | 스무딩의 지터 억제량 |
| `out_of_bounds` | 정규화 좌표가 `[0,1]`을 벗어남 | 클램프 및 경계 방어 |

> 좌표는 랜덤이 아니라 **고정 시드 또는 결정론적 수식**으로 생성한다. 매 실행 동일해야 한다.

**Step 2. 현재 코드의 출력을 스냅샷으로 고정**

- [ ] 위 6종 시퀀스를 **현재(리팩토링 전) 스무딩 함수 · 제스처 판정 로직**에 그대로 통과시킨다
- [ ] 프레임별 출력(스무딩된 좌표, 제스처 상태, 발행 이벤트)을 `tests/fixtures/characterization.json`으로 덤프
- [ ] 부동소수점 비교 허용 오차를 명시한다 (좌표 `atol=1e-6`, 상태·이벤트는 **완전 일치**)

**Step 3. 회귀 테스트로 고정**

- [ ] `tests/unit/test_characterization.py` 작성 — 스냅샷과 현재 출력을 비교
- [ ] 이후 **모든 Phase에서 이 테스트가 통과해야만 커밋**한다

> ⚠️ 현재 코드가 순수 함수로 분리되어 있지 않아 시퀀스를 주입할 수 없다면, **Phase 0에서 그 함수만
> 최소한으로 추출**한다. 이때는 로직을 한 줄도 바꾸지 말고 시그니처만 분리한다.

### 2.5 수동 스모크 테스트 절차 수립

자동 E2E 검증이 없는 만큼, 사람이 확인하는 절차를 문서로 고정해 공백을 메운다.

- [ ] `docs/smoke_test_checklist.md` 작성 — 실제 카메라로 매 Phase 종료 시 수행할 항목
  - 손 진입 → 핀치 → 드로잉 → 해제 → 손 이탈 정상 동작
  - 손을 프레임 밖으로 완전히 빼도 크래시/스트로크 잔류 없음
  - Container C 연결 없이 기동해도 엔진이 살아 있음
  - `Ctrl+C` 종료 시 예외 스택 없이 정상 종료
- [ ] 수행 결과는 `docs/smoke_test_log.md`에 Phase별로 누적 기록

---

## 3. 4대 핵심 엔지니어링 축 (Pillars)

---

## Pillar 1. 파라미터화 및 가독성

> ### **나만 쓰는 코드가 아니다. 누구나 환경설정만 바꿔서 쓸 수 있어야 한다.**

### 1-1. 하드코딩 전면 제거 및 설정 파일 분리

**작업**: Phase 0에서 만든 하드코딩 목록을 전부 `config/config.yaml`로 이관한다.

```yaml
# config/config.yaml
app:
  name: gesture-drawing-engine
  env: dev                        # dev | prod (APP_ENV 환경변수로 오버라이드)

camera:
  source: 0                       # int(장치 인덱스) 또는 str(영상 파일 경로)
  width: 640
  height: 480
  fps: 30
  reconnect:
    max_retries: 5
    backoff_base_sec: 0.5
    backoff_max_sec: 8.0
    jitter: true

mediapipe:
  model_asset_path: models/hand_landmarker.task
  running_mode: LIVE_STREAM       # 변경 금지
  num_hands: 1
  min_hand_detection_confidence: 0.5
  min_hand_presence_confidence: 0.5
  min_tracking_confidence: 0.5
  delegate: CPU                   # CPU | GPU

smoothing:
  one_euro:
    freq: 30.0
    min_cutoff: 1.0
    beta: 0.007
    d_cutoff: 1.0

gesture:
  # hand_world_landmarks 기준, 단위: 미터
  pinch_enter_threshold_m: 0.035  # 이 값 미만이면 PINCH 진입
  pinch_exit_threshold_m: 0.045   # 이 값 초과해야 PINCH 해제 (히스테리시스)
  debounce_frames: 3              # 상태 전이 확정에 필요한 연속 프레임 수
  hand_lost_timeout_ms: 500       # 손 미검출 지속 시 스트로크 강제 종료

pipeline:
  queue_max_size: 2               # 백프레셔 상한
  drop_policy: latest             # latest | oldest | block
  target_latency_budget_ms: 50

output:
  protocol: websocket
  endpoint: ws://container-c:8080/stroke
  schema_version: "1.0"
  send_timeout_ms: 100
  spool:
    enabled: true
    max_events: 1000              # 전송 실패 시 로컬 버퍼 상한

logging:
  level: INFO                     # DEBUG | INFO | WARN | ERROR
  format: json                    # json | console
  path: logs/engine.log
  rotation:
    max_bytes: 10485760           # 10MB
    backup_count: 5
```

**체크리스트**

- [ ] `config/config.yaml` (기본값) + `config/config.dev.yaml` + `config/config.prod.yaml` 생성
- [ ] `.env` 지원: 민감 정보(엔드포인트, 키)는 환경변수로 주입, `.env.example` 커밋 / `.env`는 `.gitignore`
- [ ] **설정 우선순위 확정**: `CLI 인자 > 환경변수 > config.{env}.yaml > config.yaml > 코드 기본값`
- [ ] 코드 내 매직 넘버 잔존 여부 재검증 (grep 재실행)

### 1-2. 설정 스키마 검증 (Fail Fast)

잘못된 설정은 **실행 30분 후가 아니라 기동 즉시** 실패해야 한다.

- [ ] `pydantic` (v2) 기반 설정 스키마 클래스 정의 → `src/engine/config/schema.py`
- [ ] 타입, 범위(예: confidence는 0.0~1.0), 파일 존재 여부(`model_asset_path`) 검증
- [ ] **논리적 제약 검증**: `pinch_exit_threshold_m > pinch_enter_threshold_m` 아니면 기동 거부
- [ ] 검증 실패 시 **어떤 키가 왜 잘못됐는지** 명확히 출력 후 종료

### 1-3. 클린 아키텍처 도입 (모듈 간 결합도 최소화)

**목표 디렉토리 구조** — 기존 코드를 아래 구조로 재배치한다.

```
gesture-drawing-engine/
├── .github/
│   └── workflows/
│       └── ci.yml                    # CI 전용 (CD 없음)
├── config/
│   ├── config.yaml
│   ├── config.dev.yaml
│   └── config.prod.yaml
├── models/
│   └── hand_landmarker.task          # LFS 또는 다운로드 스크립트 사용
├── src/engine/
│   ├── __init__.py
│   ├── main.py                       # 조립(Composition Root)만 담당
│   ├── errors.py                     # 예외 계층 정의
│   ├── config/
│   │   ├── loader.py
│   │   └── schema.py
│   ├── io/
│   │   ├── frame_source.py           # ★ 추상 인터페이스 (CI의 핵심)
│   │   └── sink.py                   # Container C 전송 추상화
│   ├── vision/
│   │   ├── landmarker.py             # MediaPipe 래핑
│   │   └── smoothing.py              # One Euro Filter
│   ├── gesture/
│   │   ├── metrics.py                # world landmarks 기반 거리 계산
│   │   └── state_machine.py          # 제스처 상태 전이 (순수 로직)
│   ├── pipeline/
│   │   ├── runner.py
│   │   └── bounded_queue.py
│   └── observability/
│       ├── logging.py
│       └── metrics.py                # 지연 시간 계측
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── synthetic_sequences.py    # 코드로 생성하는 결정론적 랜드마크 시퀀스
│   │   └── characterization.json     # 리팩토링 전 순수 로직 출력 스냅샷
│   ├── unit/
│   ├── integration/
│   └── perf/
├── docs/
├── scripts/
│   └── download_model.sh
├── .env.example
├── .gitignore
├── pyproject.toml
├── Dockerfile
└── README.md
```

**리팩토링 원칙**

- [ ] **의존성 역전**: 상위 로직(`pipeline`, `gesture`)이 하위 구현(`cv2`, `mediapipe`)을 직접 import 하지 않는다. 인터페이스에 의존시킨다.
- [ ] **순수 함수 분리**: `gesture/state_machine.py`와 `vision/smoothing.py`는 **I/O 없는 순수 로직**이어야 한다. → 테스트 가능성의 핵심
- [ ] `main.py`는 설정 로드 → 객체 생성 → 조립 → 실행만 담당. 비즈니스 로직 금지.
- [ ] 전역 변수 제거, 함수 길이 50줄 이내, 타입 힌트 전면 적용

**★ 가장 중요한 리팩토링: `FrameSource` 추상화**

CI 환경에는 웹캠이 없다. 이 추상화 없이는 자동화 테스트가 불가능하므로 **최우선으로 처리한다.**

```python
# src/engine/io/frame_source.py
from abc import ABC, abstractmethod
from typing import Iterator
import numpy as np

class FrameSource(ABC):
    """프레임 공급원 추상 인터페이스."""

    @abstractmethod
    def frames(self) -> Iterator[tuple[int, int, np.ndarray]]:
        """(frame_id, timestamp_ms, BGR frame) 를 순차 반환."""

    @abstractmethod
    def close(self) -> None: ...


class CameraSource(FrameSource):      # 운영: cv2.VideoCapture(device_index)
    ...

class SyntheticSource(FrameSource):   # ★ 테스트/CI 기본 경로: numpy로 합성 프레임 생성 (필수)
    ...

# VideoFileSource 는 지금 구현하지 않는다. 영상 픽스처를 확보하면 그때 추가한다.
```

동일하게 `LandmarkProvider` 인터페이스도 분리하여, CI에서는 **코드로 생성한 합성 랜드마크 시퀀스**를
공급하는 `SyntheticLandmarkProvider`로 대체할 수 있게 한다.
→ **MediaPipe 런타임도, 카메라도, 영상 파일도 없이 파이프라인 전체를 테스트할 수 있다.**

> 참고: 나중에 실제 구동 중 랜드마크를 JSON으로 덤프하는 `--dump-landmarks` 플래그를 붙이면
> 실데이터 기반 `ReplayLandmarkProvider`를 추가할 수 있다. 영상이 아니라 좌표 배열이라 용량 부담이
> 거의 없다. 다만 **이번 작업의 필수 범위는 아니다.**

---

## Pillar 2. 예외 처리 및 안정성

> ### **단 한 번의 에러로 24시간 도는 시스템을 멈추게 할 수는 없다.**

### 2-1. 예외 계층 정의

- [ ] `src/engine/errors.py`에 도메인 예외 계층을 정의한다.

```python
class EngineError(Exception):
    """모든 엔진 예외의 루트."""

# --- 복구 가능 (Recoverable) — 재시도/우회 대상 ---
class RecoverableError(EngineError): ...
class CameraReadError(RecoverableError): ...       # 일시적 프레임 획득 실패
class InferenceTimeoutError(RecoverableError): ...  # 추론 지연/타임아웃
class SinkUnavailableError(RecoverableError): ...   # Container C 연결 끊김

# --- 치명적 (Fatal) — 즉시 종료 대상 ---
class FatalError(EngineError): ...
class ConfigValidationError(FatalError): ...        # 잘못된 설정
class ModelLoadError(FatalError): ...               # 모델 파일 없음/손상
class DeviceUnavailableError(FatalError): ...       # 카메라 장치 자체가 없음
```

**규칙: `except Exception: pass` 는 전면 금지.** 모든 예외는 분류되고 로깅되어야 한다.

### 2-2. Edge-case 방어 로직 및 입력값 유효성 검사 강화

MediaPipe 파이프라인에서 **반드시 방어해야 할 케이스** 전수 처리:

| # | 상황 | 요구 동작 |
|---|---|---|
| 1 | 손이 검출되지 않음 (`result.hand_landmarks == []`) | 크래시 금지. 마지막 상태 유지 → `hand_lost_timeout_ms` 초과 시 스트로크 정상 종료(`STROKE_END` 발행) |
| 2 | 손이 프레임 경계를 벗어나 랜드마크가 화면 밖 좌표로 나옴 | 정규화 좌표를 `[0.0, 1.0]`으로 클램프, 경계 이탈 플래그 부여 |
| 3 | 검출 손 개수가 설정값 초과 (`num_hands` 초과 반환) | 신뢰도 최상위 1개만 채택, 나머지 무시 후 DEBUG 로깅 |
| 4 | `hand_world_landmarks`가 비어 있음 (world만 누락되는 케이스) | 거리 판정 스킵, 직전 제스처 상태 유지 (오판정 방지) |
| 5 | 프레임이 `None` / 크기 0 / 채널 수 불일치 | 해당 프레임 드롭, 카운터 증가, 연속 N회 시 `CameraReadError` 승격 |
| 6 | 타임스탬프 역행 또는 중복 (LIVE_STREAM은 단조 증가 필수) | 단조 증가 보정 후 WARN 로깅. MediaPipe에 역행 타임스탬프 전달 금지 |
| 7 | 핀치 임계값 경계에서 상태 떨림(chattering) | **히스테리시스 + N프레임 디바운스**로 억제 (설정값 사용) |
| 8 | One Euro Filter 첫 프레임 (이전 값 없음) | 초기화 분기 명시, 0으로 나누기 방지 |
| 9 | 모델 파일 경로 오류 / 손상 | `ModelLoadError` → **기동 즉시 실패** (Fail Fast) |
| 10 | Container C 연결 끊김 | 파이프라인은 계속 동작, 이벤트는 로컬 스풀에 버퍼링 (2-4 참조) |

- [ ] 위 10개 케이스를 코드에 반영하고, **각 케이스마다 대응 단위 테스트를 1개씩 작성**한다.

### 2-3. 우아한 저하 (Graceful Degradation) 구현

시스템 상태를 명시적으로 모델링한다. 에러 = 즉시 종료가 아니다.

| 레벨 | 상태 | 트리거 | 동작 |
|---|---|---|---|
| L0 | `NORMAL` | 정상 | 전체 기능 동작 |
| L1 | `DEGRADED` | 손 미검출 지속 / 신뢰도 저하 | 추론 유지, 좌표 발행 중단, `HOLD` 이벤트만 전송 |
| L2 | `RECOVERING` | 프레임 획득 실패 / Sink 단절 | 재시도 루프 진입, 스풀 버퍼링, 파이프라인은 살아있음 |
| L3 | `FAILED` | Fatal 예외 / 재시도 한도 초과 | 리소스 정리 후 종료 이벤트 발행, non-zero exit |

- [ ] 상태 전이를 명시적 상태 머신으로 구현, 전이 시마다 로그 기록
- [ ] **L1/L2에서 절대 프로세스가 죽지 않아야 한다.** 이것이 이 Pillar의 합격 기준.

### 2-4. 재시도(Retry) 메커니즘 구축

- [ ] **지수 백오프 + 지터** 재시도 유틸 구현 (`base * 2^n`, `max` 상한, 랜덤 지터)
- [ ] 적용 대상: 카메라 재연결, Container C WebSocket 재연결
- [ ] **적용 금지 대상**: 설정 오류, 모델 로드 실패 → 재시도 무의미, 즉시 실패
- [ ] Sink 단절 시 이벤트 **로컬 스풀** (상한 `output.spool.max_events`), 재연결 시 순서 보장 플러시
- [ ] 스풀 오버플로 시 **최신 우선 유지**(오래된 것 폐기) + WARN 로깅
- [ ] 재시도 한도 초과 시에만 L3로 승격

### 2-5. 안전한 종료 (Graceful Shutdown)

- [ ] `SIGINT` / `SIGTERM` 핸들러 등록
- [ ] 종료 순서: 프레임 수신 중단 → 큐 드레인 → 진행 중 스트로크 `STROKE_END` 발행 → 스풀 플러시 → MediaPipe 리소스 해제 → `cv2` 릴리스 → 로그 플러시
- [ ] 모든 리소스는 `contextlib` / `try...finally`로 해제 보장 (특히 `HandLandmarker`와 `VideoCapture`)

---

## Pillar 3. 성능 및 메모리 관리

> ### **모델보다 전처리가 지연 시간을 더 잡아먹는 일은 없어야 한다.**

> ⚠️ **Phase 0의 베이스라인 측정이 완료되지 않았다면 이 Pillar를 시작하지 않는다.**

### 3-1. 지연 시간 계측 체계부터 구축

- [ ] `src/engine/observability/metrics.py`에 단계별 타이머 구현 (`time.perf_counter_ns` 사용)
- [ ] 계측 구간: `capture → preprocess → inference → smoothing → gesture → sink`
- [ ] 각 구간 p50/p95/p99를 주기적으로(예: 100프레임마다) INFO 로그로 출력
- [ ] `pipeline.target_latency_budget_ms` 초과 시 WARN 발생

### 3-2. LIVE_STREAM 비동기 콜백 규칙 (가장 흔한 병목 지점)

MediaPipe `LIVE_STREAM` 모드의 결과 콜백은 **MediaPipe 내부 스레드에서 실행된다.**

- [ ] **콜백 안에서 무거운 작업 금지.** 콜백은 결과를 바운디드 큐에 넣고 즉시 반환만 한다.
- [ ] 스무딩/제스처 판정/전송은 콜백 밖의 소비자 루프에서 처리한다.
- [ ] 콜백 내 `print`, 파일 I/O, 네트워크 전송, `cv2.imshow` **전면 금지**
- [ ] 타임스탬프는 **반드시 단조 증가**하도록 소스에서 생성 (프레임 카운터 기반 권장)

### 3-3. 병렬 처리를 통한 전처리 지연 최소화

- [ ] 전처리(리사이즈/색공간 변환)가 병목으로 확인된 경우에만 병렬화한다. **추측으로 도입 금지.**
- [ ] I/O 바운드(캡처, 전송) → **스레드**, CPU 바운드(전처리) → **프로세스 풀** 원칙 적용
- [ ] MediaPipe 인스턴스는 스레드 간 공유하지 않는다 (스레드별 인스턴스 또는 단일 소비자 구조)
- [ ] **바운디드 큐 + drop-latest 정책** 적용: 실시간 시스템은 프레임을 쌓는 것보다 버리는 것이 옳다
  - `queue_max_size: 2` 유지, 가득 차면 가장 오래된 프레임 폐기 후 드롭 카운터 증가

### 3-4. 프레임 처리 최적화 (불필요한 복사 제거)

- [ ] `cv2.cvtColor(BGR→RGB)` 중복 호출 제거 — 프레임당 정확히 1회
- [ ] `np.array` / `mp.Image` 생성 시 불필요한 `.copy()` 제거, 가능하면 버퍼 재사용
- [ ] 리사이즈는 캡처 단계에서 `cap.set()`으로 처리 (프레임마다 소프트웨어 리사이즈 회피)
- [ ] 매 프레임 발생하는 리스트/딕셔너리 신규 할당을 사전 할당 구조로 대체
- [ ] 시각화(`imshow`, 랜드마크 오버레이 드로잉)는 **디버그 모드 전용 플래그**로 분리 — 운영 경로에서 완전 제거

### 3-5. 메모리 누수 점검 및 가비지 컬렉션 최적화

- [ ] 프레임 버퍼 / 랜드마크 히스토리는 **반드시 `collections.deque(maxlen=N)`** 사용 (무한 증가 리스트 금지)
- [ ] 궤적(trajectory) 저장 구조에 상한 설정 — 스트로크 종료 시 명시적 해제
- [ ] `tracemalloc` 기반 장시간 구동 테스트: **10,000 프레임 처리 후 RSS 증가량 < 50MB** 검증
- [ ] MediaPipe `HandLandmarker`는 반드시 `close()` 또는 컨텍스트 매니저로 해제
- [ ] 순환 참조 발생 지점(콜백 ↔ 객체 상호 참조) 점검, 필요 시 `weakref` 적용

### 3-6. 성능 수용 기준

Phase 0 베이스라인 대비 아래를 만족해야 Phase 3 완료로 인정한다.

| 지표 | 기준 |
|---|---|
| E2E 지연 p95 | 베이스라인 이하 (악화 금지), 목표 ≤ 50ms |
| 처리 FPS | 입력 FPS의 90% 이상 유지 |
| 프레임 드롭률 | 정상 부하에서 < 5% |
| 10분 구동 후 RSS 증가 | < 50MB |
| 특성화 테스트 | 전항 통과 (순수 로직 출력 불변) |

---

## Pillar 4. 로깅

> ### **문제 발생 시 책임 소재를 밝히는 '법적 흔적'이자 디버깅의 유일한 열쇠다.**

### 4-1. 표준화된 로그 포맷 및 체계적 레벨링

- [ ] **`print()` 전면 제거.** 표준 `logging` 모듈 기반 중앙 설정 (`src/engine/observability/logging.py`)
- [ ] JSON 구조화 로깅 (운영) / 컬러 콘솔 로깅 (개발) 을 설정으로 전환
- [ ] 로그 레벨 정책을 아래와 같이 **엄격히** 적용한다.

| 레벨 | 용도 | 제스처 엔진 적용 예시 |
|---|---|---|
| `DEBUG` | 프레임 단위 상세 | 랜드마크 좌표, 필터 내부값, 프레임별 지연 |
| `INFO` | 상태 전이 / 수명주기 | 기동/종료, 설정 로드 완료, 스트로크 시작·종료, 주기적 성능 요약 |
| `WARN` | 저하되었으나 동작 지속 | 프레임 드롭, 손 미검출 지속, Sink 재연결 시도, 지연 예산 초과 |
| `ERROR` | 기능 실패 (프로세스는 생존) | 추론 실패, Sink 전송 최종 실패, 스풀 오버플로 |
| `CRITICAL` | 프로세스 종료 유발 | 모델 로드 실패, 설정 검증 실패, 재시도 한도 초과 |

> ⚠️ **`DEBUG`는 프레임당 로그를 발생시키므로 운영 기본값은 반드시 `INFO`.**
> 프레임 루프 내 로깅은 반드시 샘플링(예: N프레임마다 1회) 또는 레벨 가드(`logger.isEnabledFor`)를 적용한다.

### 4-2. 역추적(Traceback) 가능한 맥락 데이터 포함

모든 로그 레코드에 아래 컨텍스트 필드를 자동 주입한다 (`LoggerAdapter` 또는 `contextvars` 사용).

```json
{
  "ts": "2026-08-31T10:14:02.115Z",
  "level": "WARN",
  "logger": "engine.pipeline.runner",
  "session_id": "sess_9f2a",
  "frame_id": 10432,
  "frame_ts_ms": 347733,
  "state": "DEGRADED",
  "event": "frame_dropped",
  "reason": "queue_full",
  "queue_size": 2,
  "latency_ms": 63.2
}
```

- [ ] `session_id`(프로세스 1회 구동 단위), `frame_id`(단조 증가)를 **모든 로그에 필수 포함**
  → Container A/C 로그와 `frame_id`로 상호 대조 가능해야 한다
- [ ] 예외 로깅은 반드시 `logger.exception(...)` 또는 `exc_info=True`로 스택 트레이스 포함
- [ ] `event` 필드에 스네이크 케이스 이벤트명을 부여하여 기계 판독 가능하게 유지

### 4-3. 로그 로테이션을 통한 스토리지 관리

- [ ] `RotatingFileHandler` 적용 (`max_bytes`, `backup_count`는 설정에서 주입)
- [ ] 24시간 연속 구동 시 로그 총량이 상한을 넘지 않음을 계산으로 검증
- [ ] 컨테이너 환경 대비: 파일 핸들러와 stdout 핸들러 동시 지원 (설정으로 선택)

### 4-4. 개인정보 보호 (필수)

카메라 기반 시스템이므로 **법적 리스크 영역이다.**

- [ ] **원본 프레임 이미지를 로그/디스크에 절대 저장하지 않는다.**
- [ ] 랜드마크 원시 좌표는 `DEBUG` 레벨에서만 허용, 운영에서 비활성
- [ ] 파일 경로, 사용자명 등 환경 정보가 로그에 노출되지 않도록 마스킹

---

## 4. The Engine — CI 자동화 (CD 제외)

> 앞의 4가지 축은 **개발자의 수작업으로 단 한 번 달성하는 데 그쳐서는 안 된다.**
> 코드가 변경될 때마다 이 기준이 **자동으로 검증되고 유지되도록** 만드는 것이 CI의 역할이다.

```
Step 1: Code Push  →  Step 2: GitHub Actions  →  Step 3: Pytest (4대 축 검증)  →  [CD 없음]
```

### 4-1. pytest 테스트 전략

**CI 환경에는 웹캠도 GPU도 없다.** Pillar 1에서 만든 `FrameSource` / `LandmarkProvider` 추상화가
테스트 가능성의 전제조건이다.

```
tests/
├── conftest.py                       # 공용 픽스처
├── fixtures/
│   ├── synthetic_sequences.py        # 결정론적 랜드마크 시퀀스 생성기 (6종)
│   └── characterization.json         # 리팩토링 전 순수 로직 출력 스냅샷
├── unit/
│   ├── test_config_schema.py         # [P1] 설정 검증, 잘못된 값 거부
│   ├── test_config_precedence.py     # [P1] CLI > env > yaml 우선순위
│   ├── test_one_euro_filter.py       # [P3] 스무딩 수학적 정확성, 초기화 분기
│   ├── test_gesture_metrics.py       # [P2] world landmarks 거리 계산
│   ├── test_gesture_state_machine.py # [P2] 히스테리시스, 디바운스, 상태 전이
│   ├── test_edge_cases.py            # [P2] 2-2의 10개 케이스 전수
│   ├── test_retry_backoff.py         # [P2] 지수 백오프 + 한도 초과 동작
│   ├── test_logging_context.py       # [P4] frame_id/session_id 주입, 마스킹
│   └── test_characterization.py      # ★ 리팩토링 전후 순수 로직 출력 일치 검증
├── integration/
│   ├── test_pipeline_synthetic.py    # 합성 시퀀스로 파이프라인 E2E (카메라·영상 불필요)
│   ├── test_graceful_degradation.py  # Sink 강제 단절 → L2 진입 → 복구 검증
│   └── test_shutdown.py              # SIGTERM 시 리소스 해제/스트로크 종료
└── perf/                             # @pytest.mark.slow — CI 기본 제외
    ├── test_latency_budget.py
    └── test_memory_leak.py           # 10,000 프레임 RSS 증가량 검증
```

**테스트 작성 규칙**

- [ ] 실제 카메라 장치나 영상 파일을 요구하는 테스트 **금지** — 전부 `SyntheticSource` / 합성 시퀀스 사용
- [ ] 모든 픽스처는 **코드로 생성**한다. 영상·이미지 등 바이너리 픽스처를 리포에 넣지 않는다
- [ ] MediaPipe 런타임에 의존하는 테스트는 `@pytest.mark.mediapipe`로 분리 (CI에서 선택 실행)
- [ ] `perf` 테스트는 `@pytest.mark.slow`로 마킹, 기본 CI에서는 제외 (러너 성능 편차로 flaky)
- [ ] **특성화 테스트가 이 프로젝트의 안전벨트다.** 순수 로직 출력이 리팩토링 전후 동일함을 반드시 검증
- [ ] 실영상 기반 자동 E2E 검증이 없는 만큼, **각 Phase 종료 시 실제 카메라로 수동 스모크 테스트**를
      수행하고 결과를 `docs/smoke_test_log.md`에 기록한다 (2.5절 체크리스트 사용)

### 4-2. GitHub Actions 워크플로우 (CI 전용)

`.github/workflows/ci.yml` 생성:

```yaml
name: CI

on:
  push:
    branches: [main, develop, "feature/**"]
  pull_request:
    branches: [main, develop]

jobs:
  quality:
    name: Lint & Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - name: Ruff (lint)
        run: ruff check src tests
      - name: Ruff (format check)
        run: ruff format --check src tests
      - name: Mypy (type check)
        run: mypy src

  test:
    name: Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
      - name: Install OpenCV headless deps
        run: sudo apt-get update && sudo apt-get install -y libgl1 libglib2.0-0
      - run: pip install -e ".[dev]"
      - name: Run tests
        run: pytest -m "not slow" --cov=src/engine --cov-report=xml --cov-report=term-missing
      - name: Coverage gate
        run: coverage report --fail-under=70

  config-validation:
    name: Config Schema Validation
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -e ".[dev]"
      - name: Validate all config files
        run: |
          python -m engine.config.loader --validate config/config.yaml
          python -m engine.config.loader --validate config/config.dev.yaml
          python -m engine.config.loader --validate config/config.prod.yaml

  docker-build:
    name: Docker Build Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image (no push)
        run: docker build -t gesture-drawing-engine:ci .
```

> **CD는 구축하지 않는다.** `deploy`, `release`, `push to registry`, 환경 secret 기반 배포 job을
> 절대 추가하지 말 것. `docker-build`는 **빌드 가능 여부 검증(CI)** 목적이며 이미지를 푸시하지 않는다.

### 4-3. CI 환경 주의사항

- [ ] `opencv-python` 대신 **`opencv-python-headless`** 사용 (GUI 의존성 회피)
- [ ] `models/*.task` 파일은 리포에 직접 커밋하지 말고 `scripts/download_model.sh`로 획득 + CI 캐싱
- [ ] 바이너리 테스트 픽스처 없음 — 모든 입력은 `numpy`로 합성 생성 (리포 용량 증가 0, Git LFS 불필요)
- [ ] 헤드리스 환경에서 `cv2.imshow` 호출 경로가 실행되지 않도록 디버그 플래그 기본 `false`

### 4-4. 개발 도구 설정 (`pyproject.toml`)

- [ ] `ruff` (lint + format), `mypy` (strict 모드 점진 적용), `pytest` + `pytest-cov` 설정 통합
- [ ] `[project.optional-dependencies] dev = [...]`로 개발 의존성 분리
- [ ] `pre-commit` 훅 구성 (선택) — CI와 동일한 규칙을 로컬에서 선반영

---

## 5. 인터페이스 계약 (Container A / C)

리팩토링 중에도 **외부 계약은 깨지지 않아야 한다.** 변경이 필요하면 `schema_version`을 올리고 문서화한다.

### 5-1. 출력 이벤트 스키마 (Container B → C)

```json
{
  "schema_version": "1.0",
  "session_id": "sess_9f2a",
  "frame_id": 10432,
  "timestamp_ms": 347733,
  "event": "STROKE_MOVE",
  "state": "NORMAL",
  "point": { "x": 0.4213, "y": 0.6087 },
  "confidence": 0.94
}
```

- `event`: `STROKE_START` | `STROKE_MOVE` | `STROKE_END` | `HOLD` | `CLEAR`
- `point`: **정규화 좌표 `[0.0, 1.0]`** (`hand_landmarks` 기준). 렌더링 해상도는 Container C 책임
- 거리 판정에 쓰인 미터 단위 값은 **내부 전용**, 외부로 노출하지 않음

**작업 항목**

- [ ] 현재 코드의 실제 출력 스키마를 위 형식으로 정규화 (Phase 0 조사 결과 반영)
- [ ] 출력 직전 스키마 검증 레이어 추가 — 계약 위반 시 ERROR 로깅 후 해당 이벤트 드롭
- [ ] 계약 변경 시 `docs/contract.md` 갱신 및 버전 증가 필수
- [ ] `STROKE_START` 없이 `STROKE_MOVE`가 발행되는 시퀀스 오류를 테스트로 방지

---

## 6. 단계별 실행 계획

각 Phase는 **독립 커밋 + CI 통과**로 마감한다. 이전 Phase가 끝나기 전에 다음으로 넘어가지 않는다.

| Phase | 작업 | 산출물 | 완료 조건 |
|---|---|---|---|
| **0** | 진단 · 베이스라인 · 특성화 스냅샷 | `docs/00_*.md`, `synthetic_sequences.py`, `characterization.json`, `smoke_test_checklist.md` | 측정치 문서화 + 스냅샷 고정 완료 |
| **1** | 구조 재편 + 설정 분리 (Pillar 1) | 디렉토리 구조, `config/*.yaml`, `FrameSource` 추상화 | 하드코딩 0건, 기존 동작 동일 |
| **2** | 예외 처리 · 안정성 (Pillar 2) | `errors.py`, 상태 머신, 재시도, 스풀 | Edge-case 10종 방어, L1/L2에서 무중단 |
| **3** | 성능 · 메모리 (Pillar 3) | 계측 모듈, 큐/드롭 정책, 누수 제거 | 3-6 수용 기준 전항 충족 |
| **4** | 로깅 (Pillar 4) | 구조화 로깅, 로테이션, 컨텍스트 주입 | `print` 0건, `frame_id` 전 로그 포함 |
| **5** | CI 구축 | `pyproject.toml`, `tests/`, `ci.yml` | 커버리지 ≥ 70%, CI 전 job green |
| **6** | 문서화 마감 | `README`, `docs/contract.md`, `docs/operations.md` | 신규 개발자 온보딩 가능 수준 |

> **Phase 1이 가장 위험하다.** 대규모 파일 이동이 발생하는데, 실영상 기반 자동 E2E 회귀 검증이 없기
> 때문이다. 반드시 ① Phase 0의 **특성화 테스트 통과**와 ② 실제 카메라 **수동 스모크 테스트**,
> 두 가지를 모두 확인한 뒤 커밋한다. 또한 Phase 1은 한 번에 끝내지 말고
> **"파일 이동" → "설정 분리" → "인터페이스 추출"** 처럼 작은 커밋으로 쪼갠다.

---

## 7. Definition of Done

아래를 **전부** 만족해야 "프로덕션 레벨"로 인정한다.

**Pillar 1 — 파라미터화**
- [ ] 코드 내 매직 넘버/하드코딩 경로 **0건**
- [ ] 설정 파일만 교체하여 dev/prod 전환 가능
- [ ] 잘못된 설정 시 기동 즉시 명확한 메시지와 함께 실패
- [ ] 전 모듈 타입 힌트, mypy 통과

**Pillar 2 — 안정성**
- [ ] `except Exception: pass` **0건**
- [ ] Edge-case 10종 전부 방어 + 각 케이스 테스트 존재
- [ ] Sink를 강제 종료해도 엔진 프로세스가 죽지 않고 복구됨
- [ ] `SIGTERM` 수신 시 리소스 누수 없이 종료

**Pillar 3 — 성능**
- [ ] E2E p95 지연이 베이스라인 이하
- [ ] 10,000 프레임 처리 후 RSS 증가 < 50MB
- [ ] LIVE_STREAM 콜백 내 블로킹 작업 **0건**

**Pillar 4 — 로깅**
- [ ] `print()` **0건**
- [ ] 모든 로그에 `session_id` + `frame_id` 포함
- [ ] 로그 로테이션 동작 확인, 원본 이미지 미저장

**CI**
- [ ] `main` 브랜치 push 시 전 job green
- [ ] 커버리지 ≥ 70%
- [ ] 특성화 테스트 통과 (순수 로직 출력 불변)
- [ ] 전 테스트가 카메라·영상 파일 없이 실행됨
- [ ] Phase별 수동 스모크 테스트 기록 존재 (`docs/smoke_test_log.md`)
- [ ] **CD 관련 job 미존재**

---

## 8. 금지 사항

작업 중 아래는 **절대 하지 않는다.**

1. ❌ 신규 기능 추가 (새 제스처, 새 UI, 새 모델) — 이번 작업은 **고도화 전용**
2. ❌ 회귀 테스트 없이 제스처 판정 알고리즘 변경
3. ❌ `Solutions API`로의 회귀, `LIVE_STREAM` 외 모드로 변경
4. ❌ **CD 워크플로우 생성** (deploy / release / registry push job)
5. ❌ 모델 파일 등 대용량 바이너리의 Git 직접 커밋 (`scripts/download_model.sh`로 획득)
6. ❌ 테스트용 영상·이미지 픽스처를 만들어 커밋 — **모든 테스트 입력은 코드로 생성**한다
7. ❌ 카메라나 영상 파일이 있어야만 통과하는 테스트 작성
8. ❌ 측정 없는 성능 "최적화" — Phase 0 베이스라인 없이 Pillar 3 착수 금지
9. ❌ 여러 Phase를 한 커밋에 섞기
10. ❌ 원본 카메라 프레임을 디스크/로그에 저장

---

## 9. 결론

> **본 작업의 목표는 기능의 추가가 아닌, 엔지니어링 기준(Standard)의 확립이다.**
>
> PoC 수준의 아이디어를 실무 환경의 혹독한 조건을 견뎌내는 견고한 시스템으로 진화시키는 과정 —
> 즉, **'돌아가는 코드'를 짜는 코더(Coder)에서 '지속 가능한 시스템'을 설계하는
> 엔지니어(Engineer)로의 도약**을 증명하는 청사진이다.

```
파라미터화  ─┐
예외 처리    ─┤
성능 최적화  ─┼─►  Automation (CI)  ─►  Production-Grade System
로깅 시스템  ─┘
```

---

### 부록: 작업 시작 명령

Claude Code에게 아래와 같이 지시하여 시작한다.

```
refactoring.md를 읽고 Phase 0(진단 및 베이스라인 확보)만 먼저 수행해줘.

1) 현재 코드베이스를 분석해서 docs/00_baseline.md, docs/00_hardcoded_inventory.md 작성
2) 2.4절 기준으로 tests/fixtures/synthetic_sequences.py (합성 시퀀스 6종) 작성
3) 현재 로직에 그 시퀀스를 통과시켜 characterization.json 스냅샷 생성
4) docs/smoke_test_checklist.md 작성

테스트 영상은 없으니 카메라나 영상 파일에 의존하는 코드는 만들지 마.
2번에서 순수 함수 분리가 필요하면 시그니처만 추출하고 로직은 한 줄도 바꾸지 마.
끝나면 Phase 1 리팩토링 계획을 보고하고, 그 전까지 기존 코드는 수정하지 마.
```