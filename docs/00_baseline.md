# 00. 코드 인벤토리 및 베이스라인 (Phase 0 / §2.1)

> 대상: 저장소의 working tree 현재 상태 (uncommitted 변경 포함). `git status` 기준
> 이미 Pillar 1 일부(설정 파일 분리, pydantic 스키마 검증)가 container 2/3에
> 부분적으로 반영되어 있다 — 이 문서는 "PoC 원형"이 아니라 **지금 실제로 존재하는
> 코드**를 있는 그대로 기록한다.

## 0. 중요 정정 — refactoring.md의 전제와 실제 코드의 차이

refactoring.md는 범용 PRD 템플릿을 기반으로 "카메라 → MediaPipe → 핀치 거리
임계값 기반 상태 머신 → 좌표 발행"이라는 **단일 컨테이너** 모델을 가정한다.
실제 저장소는 이미 **4-컨테이너 구조**로 분리되어 있고, 제스처 판정 로직도
단순 핀치 거리 임계값이 아니라 **관절 각도 기반 손가락 open/closed 분류 +
엄지-검지 간격 비율 기반 줌 락**이다. 아래는 그 구조적 차이를 요약한다.

| refactoring.md의 가정 | 실제 코드 |
|---|---|
| 단일 컨테이너("Container B")가 카메라~좌표발행 전부 처리 | **4개 컨테이너**(web, canvas, vision-analysis, pattern-command)로 분리 완료 |
| `pinch_enter_threshold_m` / `pinch_exit_threshold_m` 히스테리시스로 DRAW 판정 | DRAW/ERASE는 **PIP 관절 각도**(`open_pip_angle_deg=120°`) + **5프레임 다수결 디바운스**(`window_size=5`, `required_open_votes=4`)로 판정. 두 임계값 히스테리시스는 **줌 락 진입**(`zoom_start_closed_ratio=0.80` / `zoom_start_open_ratio=1.00`)에만 존재 |
| 정규화 좌표를 `[0,1]`로 클램프 (edge-case #2) | `contracts.py`/`geometry.py`가 **명시적으로 클램프하지 않는다** (계약 규칙 6.2-2, `unletterbox_point` 독스트링 참조) |
| `hand_lost_timeout_ms` 기반 타임아웃 후 스트로크 종료 | 손 소실은 **프레임 단위 즉시 반영**(`hand_present=False`) — 별도 타임아웃 타이머 없음. Container 3의 `SessionState`가 즉시 `classifier.reset()` 호출 |
| CD 제외, CI만 구축 (아직 미착수) | `.github/workflows/`, `pyproject.toml`, `ruff`/`mypy` 설정 **없음** — Phase 0 시점 기준 미착수 확인 |

이 문서 이후의 모든 절은 **실제 코드**를 기준으로 작성한다.

## 1. 실행 흐름 (텍스트 다이어그램)

```
[브라우저/폰 카메라]
      │ JPEG (WebSocket, /ws/camera?t=TOKEN)
      ▼
┌─────────────────────────┐
│ Container A: web      │  containers/web/app.py (FastAPI, port 8000)
│  - JPEG 디코드(cv2)      │  QR/모니터 페이지, 세션 토큰 검증
│  - BGR raw 프레임 재인코딩│
└─────────────────────────┘
      │ TEXT(JSON 헤더) + BINARY(raw BGR bytes)
      │ ws://vision-analysis:8760/ingest/{session_id}
      ▼
┌───────────────────────────────────────┐
│ Container B: vision-analysis        │  app/main.py (port 8760 ingest, 8763 /health·/metrics)
│  ingest_server → SessionPipeline      │
│   ① to_rgb ② rotate/mirror ③ CLAHE(옵션) │  preprocess.py
│   ④ letterbox resize                  │
│   ⑤ MediaPipe HandLandmarker.detect_async (LIVE_STREAM) │  landmarker.py
│   ⑥ (콜백 스레드) 결과 큐 적재          │
│   ⑦ drain 스레드: unletterbox → One Euro Filter → hand_scale/outlier/near_edge │ geometry.py, one_euro_filter.py
│   ⑧ LandmarkPacket 조립                │  contracts.py
└───────────────────────────────────────┘
      │ TEXT(JSON, LandmarkPacket.to_json())
      │ ws://pattern-command:8761/landmarks
      ▼
┌───────────────────────────────────────┐
│ Container C: pattern-command        │  app.py (FastAPI, port 8761)
│  SessionState.handle_packet           │
│   - hand_present=False → classifier.reset() → IDLE 발행 │
│   - hand_present=True  → GestureClassifier.update(world_landmarks) │ gesture_classifier.py, index_finger.py
│     → command ∈ {DRAW, ERASE, ZOOM_IN, ZOOM_OUT, IDLE}   │
└───────────────────────────────────────┘
      │ TEXT(JSON: command/mode/index_tip/direction/landmarks)
      │ ws://canvas:8762/commands/{session_id}
      ▼
┌───────────────────────────────────────┐
│ Container D: canvas                 │  app.py (FastAPI, port 8762) + drawing_canvas.py
│  DrawingCanvas.apply() → render()     │  펜/지우개/줌 렌더링 (cv2)
└───────────────────────────────────────┘
      │ BINARY(JPEG 캔버스 프레임, pack()) 
      │ ws://web:8000/ws/canvas-output/{session_id}
      ▼
Container A가 /ws/monitor 구독자에게 재전송 (모니터 화면에 표시)
```

로컬 단독 실행 보조 도구(카메라/영상 파일 필요, 자동 테스트에는 쓰지 않음):
- `containers/vision-analysis/scripts/dev_camera_source.py` — Container A 스탠드인 (웹캠/영상 파일 → ingest 프로토콜)
- `containers/vision-analysis/scripts/dev_pattern_sink.py` — Container C 스탠드인 (수신 패킷 로깅)
- `containers/canvas/drawing_canvas.py:main()` — 로컬 웹캠으로 캔버스 단독 구동(디버그 CLI, `--camera` 인자로 cv2.VideoCapture 오픈)
- `app.py`(레포 루트) — `containers/canvas/drawing_canvas.py`를 로드하는, README에 문서화된 로컬 웹캠 단독 실행 진입점(레거시 아님, §2 참고)

## 2. 파일 인벤토리 / LoC / 책임

### Container A — `containers/web/` (게이트웨이, Python, FastAPI)

| 파일 | LoC | 책임 |
|---|---|---|
| `app.py` | 74 | 카메라 WS(JPEG 수신→BGR 디코드→B로 전달), 모니터 WS 팬아웃, QR/정적 페이지, 세션 토큰 검증 |
| `Dockerfile` | - | port 8000 |

### Container D — `containers/canvas/` (캔버스 렌더러, Python, FastAPI)

| 파일 | LoC | 책임 |
|---|---|---|
| `app.py` | 27 | `/commands/{session_id}` WS 수신, `DrawingCanvas` 상태 갱신, JPEG 인코딩 후 A로 전달 |
| `drawing_canvas.py` | 523 | `DrawingCanvas`(펜/지우개/줌 렌더링, 순수 상태+cv2 렌더링), `PerformanceMonitor`, 좌표 변환 순수 함수(`drawing_area_for_frame`, `camera_to_canvas_point`), **로컬 웹캠 디버그 CLI**(`main()`, MediaPipe 직접 로드) |
| `Dockerfile` | - | port 8762, opencv-python→headless로 교체 설치 |

### Container B — `containers/vision-analysis/` (비전 분석 엔진, Python, asyncio)

| 파일 | LoC | 책임 |
|---|---|---|
| `app/__init__.py` | 0 | (empty) |
| `app/main.py` | 73 | 조립(Composition Root): 설정 로드 → 검증(Fail Fast) → ingest/egress/metrics 기동 → SIGINT/SIGTERM 대기 |
| `app/config/__init__.py` | 186 | `Settings` 데이터클래스 트리(Model/Pipeline/OneEuro/Transport/Observability), 환경변수>YAML>코드기본값 우선순위 |
| `app/config/loader.py` | 109 | YAML 병합 로더(`config/vision-analysis.yaml` + `.{APP_ENV}.yaml`), env/타입 변환 헬퍼 |
| `app/config/schema.py` | 163 | pydantic v2 기반 Fail-Fast 검증(`validate()`), 범위/논리 제약, 모델 파일 존재 확인 |
| `app/contracts.py` | 217 | `IngestFrameHeader`(A→B), `LandmarkPacket`/`Handedness`/`Quality`(B→C), 계약 규칙 강제(`__post_init__`) |
| `app/geometry.py` | 120 | 랜드마크 인덱스 상수, letterbox 계산/역매핑(비클램프), `hand_scale`, `is_near_edge`, `max_displacement` — **순수 함수** |
| `app/landmarker.py` | 124 | MediaPipe `HandLandmarker` 래핑(LIVE_STREAM), 단조 타임스탬프 보정, 결과 콜백→스레드세이프 큐 |
| `app/metrics.py` | 117 | 추론 시간/검출률/팜 재검출 휴리스틱 수집, `/health`·`/metrics` HTTP 서버 |
| `app/one_euro_filter.py` | 95 | One Euro Filter(`_Axis1DFilter`, `HandLandmarksFilter`) — **순수 함수/클래스**, z축 미필터링 |
| `app/pipeline.py` | 203 | `SessionPipeline`: 프레임 수신→전처리→추론 제출(latest-frame-wins)→드레인 스레드→필터/기하 연산→`LandmarkPacket` 조립 |
| `app/preprocess.py` | 81 | RGB 변환, 회전/미러 보정, CLAHE(옵션), letterbox 리사이즈 조합 |
| `app/transport/__init__.py` | 0 | (empty) |
| `app/transport/ingest_server.py` | 97 | `/ingest/{session_id}` WS 서버, 헤더+바이너리 프레임 파싱, 세션당 `SessionPipeline` 생성/해제 |
| `app/transport/egress_client.py` | 40 | C로의 WS 송신, 지수 백오프 재연결(스풀 없음 — 큐잉된 패킷은 재연결 중 그대로 대기) |
| `scripts/dev_camera_source.py` | 91 | (테스트 인프라 아님) Container A 스탠드인 — 카메라/영상 필요 |
| `scripts/dev_pattern_sink.py` | 58 | (테스트 인프라 아님) Container C 스탠드인 |
| `tests/test_contracts.py` | 160 | 계약 검증 단위 테스트 |
| `tests/test_geometry.py` | 83 | letterbox/hand_scale/near_edge/displacement 단위 테스트 |
| `tests/test_landmarker.py` | 20 | `MonotonicTimestampGuard` 등 |
| `tests/test_metrics.py` | 38 | `MetricsCollector` 단위 테스트 |
| `tests/test_one_euro_filter.py` | 64 | One Euro Filter 단위 테스트(초기화/스무딩/reset) |
| `tests/test_preprocess.py` | 53 | 전처리 단위 테스트 |
| `Dockerfile` | - | port 8760(ingest)/8763(metrics), 모델을 빌드 시점에 다운로드, `config/vision-analysis*.yaml` 이미지에 포함 |

기존 `app/config.py`(단일 파일, 하드코딩 기본값)는 **삭제되고** `app/config/`
패키지(스키마 검증 포함)로 대체되는 중이다(현재 working tree, 미커밋).

### Container C — `containers/pattern-command/` (제스처 판정, Python, FastAPI)

| 파일 | LoC | 책임 |
|---|---|---|
| `app.py` | 130 | `/landmarks` WS 수신, 세션별 `GestureClassifier` 보유, 좌표/방향 계산 후 D로 명령 전달 |
| `config.py` | 77 | `GestureConfig`/`TransportConfig` — 환경변수>코드 기본값(YAML 없음, B와 다른 패턴) |
| `gesture_classifier.py` | 241 | `GestureClassifier`: DRAW/ERASE/ZOOM_IN/ZOOM_OUT/IDLE 상태 머신 — **순수 함수**(I/O 없음) |
| `index_finger.py` | 104 | `IndexFingerClassifier`: PIP 각도 + 다수결 윈도우로 손가락 open/closed 판정 — **순수 함수** |
| `requirements.txt` | - | fastapi, uvicorn, websockets |
| `Dockerfile` | - | port 8761 |

### 레포 루트의 `app.py` — 레거시가 아니라 문서화된 기능

Phase 1 초반에는 이 파일을 "레거시 하위호환 진입점"으로 오분류했으나,
`README.md`("프로토타입 단독 실행" 절)가 `python app.py [--camera N]
[--output 폴더]`를 **실제로 지원하는 독립 실행 경로**로 명시하고 있다 —
Docker 없이 로컬 웹캠만으로 캔버스를 띄우는 유일한 방법이다. `containers/canvas/drawing_canvas.py`를 동적으로 로드해 `DrawingCanvas`/`PerformanceMonitor`/좌표 변환 함수/`main()`을 재노출하는 4개 함수만 있는
얇은 진입점이며, Phase 1 디렉토리 재편(컨테이너 번호 접두사 제거) 이후에도
그대로 유지했다(경로만 `containers/canvas/...`로 갱신).

### Phase 1에서 제거한 죽은 코드

리팩토링 전에는 아래 shim이 `containers/pattern_command/{gesture_classifier,index_finger}.py`
(8줄, `sys.path` 조작 후 `containers/3-pattern-command`의 동일 모듈을 `import *`)로
존재했고, 레포 루트 `tests/test_gesture_classifier.py`·`test_index_finger.py`·
`test_drawing_canvas.py`(279 LoC)가 이 shim과 루트 `app.py`를 통해 실제 로직을
간접적으로 테스트하고 있었다. 디렉터리 재편 과정에서 이 shim이 이미 깨져
있었음을 발견했다(§"Phase 1에서 새로 발견/해결한 이슈" 참고) — 세 테스트
파일을 각자가 실제로 검증하는 컨테이너의 `tests/`로 옮기고 import를 직접
참조로 바꾼 뒤, shim과 `containers/__init__.py`를 삭제했다. 현재 각 컨테이너의
테스트는 해당 컨테이너의 코드를 간접 경로 없이 직접 import한다.

### 합계

| 구분 | LoC |
|---|---|
| Container A (web) | 74 |
| Container D (canvas) app + tests | 550 + 87 |
| Container B (vision-analysis) app/ | 1,213 |
| Container B tests/ + scripts/ | 464 |
| Container C (pattern-command) app + tests | 452 + 132 |
| 레포 루트 `app.py`(문서화된 독립 실행 진입점) | 24 |
| 레포 루트 `tests/fixtures/`(특성화 스냅샷 생성기) | ~600 |
| **총계 (대략)** | **~3,600** |

## 3. 외부 의존성 (실제 import 기준)

| 컨테이너 | 런타임 의존성 | 비고 |
|---|---|---|
| web | `fastapi`, `uvicorn[standard]`, `websockets`, `opencv-python`(GUI 빌드!), `numpy`, `qrcode[pil]` | 레포 루트 `requirements.txt` 사용 — headless 아님 |
| canvas | web과 동일 `requirements.txt` + `containers/pattern-command`(gesture_classifier 소스 복사) | Dockerfile에서 opencv-python-headless로 **재설치**해 GUI 의존성 제거 |
| vision-analysis | `mediapipe==1.0.1`, `numpy==2.5.2`, `opencv-python-headless==5.0.0.93`, `websockets==17.0.1`, `PyYAML==6.0.3`, `pydantic==2.13.4` | PyYAML/pydantic은 working tree에서 신규 추가(미커밋) |
| pattern-command | `fastapi`, `uvicorn[standard]`, `websockets` | numpy/mediapipe 불필요 — 순수 파이썬 판정 로직 |
| 개발 전용 | `pytest==9.1.1` (vision-analysis/requirements-dev.txt) | 루트/pattern-command에는 dev 의존성 파일 없음 |

CI/포매터/타입체커(`ruff`, `mypy`, `pytest-cov`) 설정, `pyproject.toml`,
`.github/workflows/`는 저장소 어디에도 없음 — Phase 5(§4) 전면 신규 작업.

## 4. Container 간 실제 스키마 (코드에서 역추출)

### A → B: `IngestFrameHeader` (TEXT JSON, 직후 BINARY raw 프레임)

`containers/vision-analysis/app/contracts.py:IngestFrameHeader.from_json`이
실제로 요구/검증하는 필드 (Container A가 보내는 초과 필드 `schema_version`,
`frame_id`, `byte_length`는 파싱하지 않고 무시):

```json
{
  "session_id": "string (필수)",
  "seq": "int (필수)",
  "captured_at_ms": "int (필수, 필드명 capture_ts 아님에 주의)",
  "width": "int > 0 (필수)",
  "height": "int > 0 (필수)",
  "dtype": "\"uint8\" 고정",
  "channels": "3 고정",
  "color_order": "\"BGR\" | \"RGB\" (내부적으로 bgr8/rgb8로 매핑)",
  "rotation": "0 | 90 | 180 | 270 (기본 0)",
  "mirrored": "bool (기본 false)"
}
```
직후 `width*height*3` 바이트의 raw 픽셀 데이터(BINARY 프레임)가 이어져야 한다.

### B → C: `LandmarkPacket.to_dict()` (TEXT JSON)

```json
{
  "session_id": "string",
  "seq": "int",
  "capture_ts": "int (A가 보낸 captured_at_ms 그대로)",
  "processed_ts": "int (B가 처리 완료한 시각, epoch ms)",
  "hand_present": "bool",
  "frame": {"w": "int", "h": "int"},
  "handedness": "{label, score} | null",
  "landmarks": "[{x,y,z} x21] | null  (정규화 이미지 좌표, 클램프 없음)",
  "world_landmarks": "[{x,y,z} x21] | null  (미터 단위)",
  "hand_scale": "float | null",
  "quality": {"near_edge": "bool", "filtered": "bool", "outlier_dropped": "bool"}
}
```
계약 규칙(`__post_init__`, 6.2-5): `hand_present=false`이면
`landmarks`/`world_landmarks`는 반드시 `null`이어야 하고, `true`면 반드시
둘 다 있어야 한다 — 위반 시 `ContractError`.

refactoring.md §5-1이 가정한 `schema_version`/`event`(STROKE_START 등)/`point`
필드는 **이 스키마에 존재하지 않는다.** 대신 "이벤트"에 해당하는 것은 아래
C→D의 `command`다.

### C → D: 명령 메시지 (TEXT JSON, `containers/pattern-command/app.py:_send_command`)

```json
{
  "command": "DRAW | ERASE | ZOOM_IN | ZOOM_OUT | IDLE",
  "mode": "DRAW | ERASE | ZOOM | IDLE",
  "seq": "int | null",
  "index_tip": "{x,y} | null  (정규화 이미지 좌표, landmarks[8])",
  "index_direction": "{x,y} | null  (landmarks[8]-landmarks[6], 미정규화 벡터)",
  "landmarks": "[{x,y,z} x21] | null  (정규화 이미지 좌표 그대로 전달, 스켈레톤 오버레이용)"
}
```

### D → A: 캔버스 프레임 (BINARY, `pack()` 프레이밍 — 4바이트 길이 + JSON 메타 + JPEG)

```json
{"kind": "canvas", "session_id": "...", "frame_id": "...", "seq": "...",
 "command": "...", "mode": "...", "zoom": "float(3자리)",
 "inference_ms": "... (packet에서 전달된 값, 현재 항상 null — B가 채우지 않음)",
 "landmarks": "..."}
```

## 5. Phase 0에서 발견된 현재 상태의 결함

Phase 0 작성 시점에는 "수정하지 않고 기록만" 했으나, 아래 1~3번은 Phase 1
커밋 1에서 실제로 수정했다(회귀 없음 — 46+26개 기존 테스트 + characterization
스냅샷 불변으로 확인). 4번은 Phase 1 범위 밖으로 남아 있다.

1. ~~**[P0] `containers/pattern-command/app.py`가 working tree에서 깨져
   있다.**~~ **[수정 완료, Phase 1 커밋 1]** `CANVAS_WS_URL`이 정의되지 않은
   채 참조되던 버그를 `settings.transport.canvas_ws_url`로 교체했다.
2. ~~**[P0] `containers/pattern-command/config.py`의 `GestureConfig`가
   `GestureClassifier`에 전달되지 않는다.**~~ **[수정 완료, Phase 1 커밋 1]**
   `GestureClassifier(**dataclasses.asdict(settings.gesture))`로 배선.
3. ~~**[P0] `containers/canvas/app.py`의 캔버스 해상도가 두 곳에 다른
   표현으로 중복 하드코딩되어 있다.**~~ **[수정 완료, Phase 1 커밋 1+3]**
   `CANVAS_WIDTH-1`/`CANVAS_HEIGHT-1`로 단일화(커밋 1) 후 `canvas_config.py`의
   `config/canvas.yaml`로 이관(커밋 3).
4. **줌 락 방향 결정은 "근접 시작 시점"이 아니라 "손가락 안정 판정이 끝난
   시점"의 간격 비율로 결정된다.** `characterization.json`의
   `pinch_approach_release`가 이를 실제로 보여준다 — 아래 §6 참고. (동작
   자체이지 버그가 아니므로 수정 대상 아님 — 기록 목적)
5. **`egress_client.py`는 재연결 중 큐에 쌓인 패킷을 스풀하지 않는다** —
   `out_queue.get()`이 블로킹으로 대기만 하며, 큐 자체의 `maxsize`(기본 8)를
   넘으면 `ingest_server`/`pipeline.py` 쪽에서 `QueueFull`로 드롭될 뿐 재연결
   전용 로컬 스풀은 없다. refactoring.md Pillar 2-4의 "로컬 스풀"은 Phase 2 범위.
6. **`inference_ms`가 C→D 경로에 항상 `null`로 전달된다** — B가
   `LandmarkPacket`에 추론 시간을 싣지 않기 때문. `drawing_canvas.py`의
   `PerformanceMonitor`는 로컬 디버그 CLI 전용이며 실제 배포 경로와 무관.

### Phase 1에서 새로 발견/해결한 이슈

- **루트 `pytest` 실행이 컨테이너 간 모듈명 충돌로 깨져 있었다.** 저장소
  루트에서 그냥 `pytest`를 실행하면 레거시 `tests/`와
  `containers/vision-analysis/tests/`가 한 세션에 동시 수집되면서
  `app`/`containers` 모듈 해석이 꼬였다 — 루트 `pytest.ini`(`testpaths=tests`,
  `pythonpath=.`)로 해결. 각 컨테이너 테스트는 여전히 독립 실행이 원칙이다
  (`cd containers/<이름> && pytest`).
- **동일한 이유로 `containers/canvas`에 `config.py`를 그대로 도입할 수
  없었다.** `drawing_canvas.py`가 `GestureClassifier` 재사용을 위해
  `containers/pattern-command`를 `sys.path`에 얹는데, 그 디렉터리에도
  (Phase 1 커밋 2에서 추가한) 동일 이름의 `config.py`가 있어 sys.path 순서에
  따라 엉뚱한 설정이 로드되는 실제 충돌이 재현됐다 — `canvas_config.py`로
  이름을 바꿔 해결(Phase 1 커밋 3). 컨테이너 간에 sys.path를 공유시키는
  기존 관행(`drawing_canvas.py`, `containers/pattern_command/` shim)이 있는 한,
  새 모듈을 추가할 때는 이름 충돌 여부를 항상 확인해야 한다.
- **디렉터리 번호 접두사 제거 시 `containers/pattern_command/` shim이 이미
  깨져 있었다는 것을 발견했다.** 이 shim은 루트 `tests/test_gesture_classifier.py`가
  단독 실행될 때는 `ModuleNotFoundError`로 실패했고, 전체 루트 `pytest` 세션에서만
  `test_drawing_canvas.py`가 먼저 `gesture_classifier` 모듈을 `sys.modules`에
  적재해주는 우연한 순서 덕에 "통과"하고 있었다(실행 순서 의존적 거짓 양성).
  세 개의 루트 테스트를 각자가 실제로 검증하는 컨테이너의 `tests/`로 옮기고
  shim을 완전히 삭제해 해결했다 — §2 "Phase 1에서 제거한 죽은 코드" 참고.
- **`containers/vision-analysis/models/hand_landmarker.task`(7.8MB)가 git에
  커밋되어 있다.** `.gitignore`가 `*.task`를 제외하도록 되어 있는데도 이미
  추적 중인 상태로 남아 있다 — refactoring.md 8절 금지사항 5("모델 파일 등
  대용량 바이너리의 Git 직접 커밋 금지")에 해당하지만, 다른 클론이 이 파일에
  의존하고 있을 수 있어 이번 디렉터리 재편에서는 **건드리지 않았다**. 제거하려면
  별도로 논의 후 진행할 것.

## 6. §2.4 특성화(characterization) 대상 매핑

refactoring.md §2.4가 요구하는 6종 시퀀스는 실제 코드의 아래 순수 함수/클래스를
직접 구동한다(카메라·영상·MediaPipe 런타임 불필요):

| 시퀀스 | 공간 | 구동 대상 | 실제 검증 포인트 |
|---|---|---|---|
| `pinch_approach_release` | world_meters | `gesture_classifier.GestureClassifier` | 줌 락 진입/방향 결정/모션 명령/해제(release_confirm_frames) — **엄지-검지 간격이 refactoring.md의 "핀치"에 가장 가까운 실제 아날로그** |
| `threshold_chatter` | world_meters | `index_finger.IndexFingerClassifier`(경유 `GestureClassifier`) | PIP 각도 120° 경계에서 raw 값이 매 프레임 뒤집혀도 5프레임/4표 다수결로 `stable_label`이 전혀 뒤집히지 않음(디바운스, 히스테리시스 아님) |
| `hand_lost_midway` | world_meters | `GestureClassifier.reset()`/`update()` | 손 소실 20프레임 동안 `IDLE` 유지, 재검출 후 디바운스 윈도우가 다시 채워질 때까지 DRAW 재시작 지연 |
| `fast_swipe` | normalized_image | `one_euro_filter.HandLandmarksFilter` + `geometry` | 6프레임 만에 x=0.15→0.85 이동 시 필터 지연(lag) 곡선 |
| `static_jitter` | normalized_image | `one_euro_filter.HandLandmarksFilter` | 고정 시드 가우시안 노이즈(σ=0.004) 억제량 |
| `out_of_bounds` | normalized_image | `geometry.is_near_edge` + 필터 | 프레임 밖으로 나가도 **클램프하지 않음**(계약 규칙 6.2-2)을 스냅샷으로 고정 |

생성기: `tests/fixtures/synthetic_sequences.py` (고정 시드 `SEED=20260831`, 결정론적 수식).
스냅샷: `tests/fixtures/characterization.json` (`tests/fixtures/generate_characterization.py`로 생성).
허용 오차: 좌표 `atol=1e-6`, 그 외 필드(command/mode/label/bool/None 여부)는 완전 일치.

`pipeline.py`(`SessionPipeline`)와 `app.py`(양쪽 컨테이너의 FastAPI 오케스트레이션)는
스레드/asyncio/MediaPipe 런타임에 결합되어 있어 Phase 0에서는 characterization
대상에서 **제외**했다 — 이미 그 안의 로직은 위 표의 순수 함수로 위임되어 있으므로
"순수 함수 시그니처 추출"이 추가로 필요하지 않았다(§2.4의 예외 조항 미해당).
