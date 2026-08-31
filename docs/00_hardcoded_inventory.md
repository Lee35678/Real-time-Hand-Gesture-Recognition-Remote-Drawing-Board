# 00. 하드코딩 전수 조사 (Phase 0 / §2.2)

grep 기준 전수 조사. `containers/2-vision-analysis`는 이미 Pillar 1-1의 상당
부분(모델/파이프라인/One-Euro/전송/관측성 설정)이 `config/vision-analysis*.yaml`
+ 환경변수로 이관되어 있다 — 아래 표의 "상태" 열에서 **이관 완료**로 표시한
항목은 Phase 1에서 손댈 필요가 없다. 나머지 컨테이너(0-web, 1-canvas,
3-pattern-command)는 대부분 미착수 상태다.

우선순위 기준: **P0** = 컨테이너 간 배선(주소/포트/경로)이 깨지면 즉시 장애 —
가장 먼저 이관. **P1** = 사용자 체감 동작(임계값/캔버스 크기/화질)을 좌우 —
튜닝 편의를 위해 이관. **P2** = 테스트 픽스처/문서 내 상수 등 이관 불필요.

## Container A — `containers/0-web/`

| 파일:라인 | 현재 값 | 제안 설정키 | 우선순위 | 상태 |
|---|---|---|---|---|
| `app.py:10` | `VISION_ANALYSIS_WS_URL` 기본값 `ws://vision-analysis:8760/ingest/{session_id}` | 이미 env override 가능 (`os.getenv`) | P2 | 이관 완료(env) |
| `app.py:11` | `SESSION_TOKEN` 기본값 `"hand-board"` | 이미 env override 가능 | P0 (기본값 자체가 보안상 약함 — 운영 시 필수 override) | 이관 완료(env), 문서화 필요 |
| `app.py:11` | `PUBLIC_BASE_URL` 기본값 `""` | 이미 env override 가능 | P2 | 이관 완료(env) |
| `Dockerfile:6` | `EXPOSE`/포트 `8000` (docker-compose와 이중 관리) | `app.port` (compose와 단일 출처화) | P1 | 미착수 |
| `web/capture.html:14`, `web/index.html` | 브라우저 JS 내 WS 프로토콜 유도 로직(`location.host` 사용, 하드코딩 아님) | - | - | 문제 없음(상대경로) |

## Container D — `containers/1-canvas/`

| 파일:라인 | 현재 값 | 제안 설정키 | 우선순위 | 상태 |
|---|---|---|---|---|
| `app.py:7` | `WEB_CANVAS_OUTPUT_URL` 기본값 `ws://web:8000/ws/canvas-output/{session_id}` | 이미 env override 가능 | P2 | 이관 완료(env) |
| `app.py:19` | `DrawingCanvas(360, 640)` — 캔버스 해상도 하드코딩 | `canvas.width` / `canvas.height` | P1 | 미착수 |
| `app.py:14` | `point()`의 `x*359`, `y*639` — 위 360×640과 별도로 또 하드코딩(-1 오프셋 포함, 두 곳이 어긋나면 좌표 왜곡) | 동일 설정키에서 파생 계산(`width-1`/`height-1`)으로 단일화 | **P0** (두 상수가 이미 서로 다른 표현으로 중복 — 값 불일치 리스크) | 미착수 |
| `app.py:25` | `cv2.IMWRITE_JPEG_QUALITY, 88` | `canvas.jpeg_quality` | P1 | 미착수 |
| `Dockerfile:13` | 포트 `8762` | `canvas.port` | P1 | 미착수 |
| `drawing_canvas.py:95-101` | `DrawingCanvas.__init__` 기본값: `zoom_step=1.05`, `min_zoom=1.0`, `max_zoom=4.0`, `pen_thickness=4`, `eraser_radius=24`, `min_draw_distance=2.0` | `canvas.zoom_step` 등 (생성자 인자로 이미 분리는 되어 있음 — YAML/env 배선만 없음) | P1 | 부분 이관(생성자 파라미터화는 완료, 배선 미착수) |
| `drawing_canvas.py:296` | `--model` 기본값 `containers/2-vision-analysis/models/hand_landmarker.task` | CLI 인자로 이미 override 가능(디버그 전용 스크립트) | P2 | 이관 완료(CLI 인자), 프로덕션 경로 아님 |
| `drawing_canvas.py:311-313` | `--output` 기본값 `captures`, `--canvas-width/height` 기본값 `360`/`640` | 디버그 CLI 전용 | P2 | 이관 완료(CLI 인자) |
| `drawing_canvas.py:386` | `cv2.VideoCapture(args.camera)` | `--camera` 인자로 이미 분리됨(디버그 CLI 전용, 프로덕션 경로 아님) | P2 | 이관 완료(CLI 인자) |

## Container B — `containers/2-vision-analysis/`

대부분 `app/config/__init__.py`(환경변수) + `config/vision-analysis*.yaml`로
이관 완료. 실제 남은 항목:

| 파일:라인 | 현재 값 | 제안 설정키 | 우선순위 | 상태 |
|---|---|---|---|---|
| `Dockerfile:18` | `HAND_LANDMARKER_MODEL_URL` 기본값(구글 GCS URL, 이미 `ARG`로 override 가능) | 이미 이관 완료 | P2 | 이관 완료 |
| `Dockerfile:29-31` | `EXPOSE 8760 8763` (compose/YAML의 `transport.ingest_port`/`metrics_port`와 이중 관리) | 단일 출처화는 Dockerfile 특성상 어려움 — 값 일치 여부만 CI에서 검증 | P1 | 구조적 한계(문서화로 완화) |
| `scripts/dev_camera_source.py:76-81` | `--host localhost`, `--port 8760`, `--fps 30.0`, `--rotation 0` | 디버그 스탠드인 CLI 전용, 이미 인자화 | P2 | 이관 완료(CLI 인자), 테스트 인프라 아님(카메라/영상 필요) |
| `scripts/dev_pattern_sink.py:51` | `--host 0.0.0.0` 기본값 | 디버그 스탠드인 CLI 전용 | P2 | 이관 완료(CLI 인자) |
| `app/config/__init__.py` 전체 | (참고) 모델/파이프라인/One-Euro/전송/관측성 파라미터 21개 — 모두 `resolve_*()`로 env>YAML>코드기본값 이미 구현 | - | - | **이관 완료** — refactoring.md의 `config/config.yaml` 목표 구조를 서비스별 파일명(`vision-analysis.yaml`)으로 이미 충족 |
| `app/config/schema.py` 전체 | pydantic 기반 Fail-Fast 검증 이미 존재(범위/논리 제약 포함) | - | - | **이관 완료** — Pillar 1-2 사실상 충족(모델 파일 미커밋 시 옵션으로 스킵 가능) |

## Container C — `containers/3-pattern-command/`

`config.py`가 working tree에 신규 추가되어 `GestureConfig`/`TransportConfig`로
환경변수 오버라이드를 제공하지만, **`app.py`가 아직 그 설정을 실제로 사용하지
않는다** (아래 P0 참고 — docs/00_baseline.md §5-1의 버그와 동일 지점).

| 파일:라인 | 현재 값 | 제안 설정키 | 우선순위 | 상태 |
|---|---|---|---|---|
| `app.py:44` | `GestureClassifier()` — 인자 없이 생성, `config.py`의 `settings.gesture.*`를 전달하지 않음 | `settings.gesture.*`를 `GestureClassifier(**...)`로 주입 | **P0** | **미배선** — config.py는 존재하지만 소비되지 않음 |
| `app.py:49` | `CANVAS_WS_URL` 참조 — working tree에서 정의가 삭제되어 **미정의 심볼** (docs/00_baseline.md §5-1) | `settings.transport.canvas_ws_url` | **P0 (버그)** | 깨짐 — Phase 1 착수 전 최우선 수정 |
| `Dockerfile:7` | 포트 `8761` | `transport.port` | P1 | 미착수 |
| `gesture_classifier.py:30-40` | `GestureClassifier.__init__` 기본값 9종(`open_pip_angle_deg=120.0` 등) | 이미 생성자 인자로 분리됨 — `config.py`의 `GestureConfig` 필드명과 1:1 대응, **배선만 하면 됨**(위 P0과 동일 작업) | P1 | 부분 이관(파라미터화 완료, 배선 미착수) |
| `index_finger.py:50-53` | `IndexFingerClassifier.__init__` 기본값(`open_pip_angle_deg=120.0`, `window_size=5`, `required_open_votes=4`) | `GestureClassifier`를 통해 간접 주입됨 — 위와 동일 | P1 | 부분 이관 |

## docker-compose.yml / 전역

| 위치 | 현재 값 | 우선순위 | 상태 |
|---|---|---|---|
| `docker-compose.yml` 포트 매핑(8000, 8762, 8760, 8763) | Dockerfile `EXPOSE`와 이중 관리 | P1 | 구조적 한계 — 단일 출처화보다 CI에서 값 일치 검증이 현실적 |
| `docker-compose.yml:32,41` | `PATTERN_COMMAND_WS_URL`, `CANVAS_WS_URL` 환경변수 주입 | - | 이관 완료(compose가 각 컨테이너의 env override를 명시적으로 채움) |

## 테스트/문서 내 상수 (이관 불필요, 참고용)

`containers/2-vision-analysis/tests/*.py`의 `640`/`480` 등은 테스트 픽스처
값이며 `config/vision-analysis.yaml`의 실제 운영값(동일하게 640×480)과 우연히
같다 — 결합되어 있지 않으므로 이관 대상 아님 (P2).

## 요약 — Phase 1 우선순위 작업 목록

1. **P0** `containers/3-pattern-command/app.py`의 `CANVAS_WS_URL` 미정의 버그 수정 (settings 배선)
2. **P0** `containers/3-pattern-command/app.py`가 `config.py`의 `GestureConfig`를 `GestureClassifier`에 실제로 전달하도록 배선
3. **P0** `containers/1-canvas/app.py`의 캔버스 해상도 중복 하드코딩(`DrawingCanvas(360,640)` vs `x*359,y*639`) 단일 출처화
4. **P1** Container A/D/C에 `config/{service}.yaml` 패턴을 Container B와 동일하게 도입(현재 A/D/C는 env-only, YAML 계층 없음)
5. **P1** Dockerfile `EXPOSE`/docker-compose 포트 매핑 값을 CI에서 교차 검증하는 스텝 추가(단일 출처화가 어려운 구조적 한계의 완화책)
