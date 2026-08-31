# 00. 하드코딩 전수 조사 (Phase 0 / §2.2)

> **Phase 1 커밋 1~4 반영 후 갱신** (원본 Phase 0 스냅샷은 git 이력의 이전 버전 참고).
> 4개 컨테이너 전부 `config/{service}.yaml` + env override + pydantic Fail-Fast
> 검증 계층을 갖췄다 — 아래 표의 "상태" 열이 전부 **이관 완료**인 항목은 재작업
> 불필요.

우선순위 기준: **P0** = 컨테이너 간 배선(주소/포트/경로)이 깨지면 즉시 장애.
**P1** = 사용자 체감 동작(임계값/캔버스 크기/화질)을 좌우 — 튜닝 편의를 위해
이관. **P2** = 테스트 픽스처/문서 내 상수 등 이관 불필요.

## Container A — `containers/web/`

| 파일:라인 | 현재 값 | 상태 |
|---|---|---|
| `app.py` | `VISION_ANALYSIS_WS_URL`/`PUBLIC_BASE_URL` 기본값 | 이관 완료(env) |
| `app.py` | `SESSION_TOKEN` 기본값 `"hand-board"` | 이관 완료(env) + **Fail-Fast 추가**: `APP_ENV=prod`에서 기본값 그대로면 기동 거부 (커밋 4) |
| `Dockerfile` | `EXPOSE`/포트 `8000` (docker-compose와 이중 관리) | 구조적 한계 — §"남은 항목" 참고 |
| `web/capture.html`, `web/index.html` | 브라우저 JS의 `location.host` 사용 | 문제 없음(상대경로, 하드코딩 아님) |

## Container D — `containers/canvas/`

| 파일:라인 | 현재 값 | 상태 |
|---|---|---|
| `app.py` | `WEB_CANVAS_OUTPUT_URL` 기본값 | 이관 완료(`canvas_config.py` → `config/canvas.yaml`, 커밋 3) |
| `app.py` | 캔버스 해상도(`DrawingCanvas(360,640)` vs `point()`의 `x*359,y*639`) 이중 하드코딩 | **수정 완료**(커밋 1: `CANVAS_WIDTH-1`/`CANVAS_HEIGHT-1`로 단일화) → **이관 완료**(커밋 3: `canvas.width`/`canvas.height`로 YAML/env 배선) |
| `app.py` | `cv2.IMWRITE_JPEG_QUALITY, 88` | 이관 완료(`canvas.jpeg_quality`) |
| `drawing_canvas.py`의 `DrawingCanvas.__init__` 기본값(zoom_step/min_zoom/max_zoom/pen_thickness/eraser_radius/min_draw_distance) | 생성자 파라미터화는 원래 완료 상태였음 | 이관 완료(`app.py`가 `canvas_config.CanvasConfig`의 값을 전부 명시적으로 전달, 커밋 3) |
| `Dockerfile` | 포트 `8762` | 구조적 한계 — §"남은 항목" 참고 |
| `drawing_canvas.py`의 `--model`/`--output`/`--canvas-width`/`--canvas-height`/`--camera` 등 | 디버그 CLI 전용 | 이관 완료(CLI 인자), 프로덕션 경로 아님 — 재작업 불필요 |

## Container B — `containers/vision-analysis/`

Phase 0 시점에 이미 대부분 완료된 상태였고 이번 Phase 1에서 추가로 손대지 않음.

| 파일:라인 | 현재 값 | 상태 |
|---|---|---|
| `Dockerfile` | `HAND_LANDMARKER_MODEL_URL` 기본값(`ARG`로 override 가능) | 이관 완료 |
| `Dockerfile` | `EXPOSE 8760 8763` | 구조적 한계 — §"남은 항목" 참고 |
| `scripts/dev_camera_source.py`, `scripts/dev_pattern_sink.py` | `--host`/`--port`/`--fps` 등 | 이관 완료(CLI 인자), 테스트 인프라 아님 |
| `app/config/__init__.py`, `app/config/schema.py` | 모델/파이프라인/One-Euro/전송/관측성 파라미터 21개 | **이관 완료** — env>YAML>코드기본값 + pydantic Fail-Fast |

## Container C — `containers/pattern-command/`

| 파일:라인 | 현재 값 | 상태 |
|---|---|---|
| `app.py`의 `GestureClassifier()` | 인자 없이 생성, `config.py`의 값 미사용이었던 버그 | **수정 완료**(커밋 1: `GestureClassifier(**dataclasses.asdict(settings.gesture))` 배선) |
| `app.py`의 `CANVAS_WS_URL` | working tree에서 정의가 삭제되어 미정의 심볼이던 버그 | **수정 완료**(커밋 1: `settings.transport.canvas_ws_url`) |
| `config.py`/`config_loader.py`/`config_schema.py` | env-only였던 설정을 YAML 계층 + Fail-Fast로 확장 | **이관 완료**(커밋 2) |
| `Dockerfile` | 포트 `8761` | 구조적 한계 — §"남은 항목" 참고 |
| `gesture_classifier.py`/`index_finger.py`의 생성자 기본값 | `config.py`의 `GestureConfig`와 1:1 대응, 배선 완료 | 이관 완료 |

## docker-compose.yml / 전역

| 위치 | 현재 값 | 상태 |
|---|---|---|
| `docker-compose.yml` 포트 매핑(8000, 8762, 8760, 8763) | 각 Dockerfile의 `EXPOSE`와 이중 관리 | 구조적 한계 — §"남은 항목" 참고 |
| `docker-compose.yml`의 `PATTERN_COMMAND_WS_URL`, `CANVAS_WS_URL` 등 | 각 컨테이너의 env override를 명시적으로 채움 | 이관 완료 |

## 테스트/문서 내 상수 (이관 불필요, 참고용)

`containers/vision-analysis/tests/*.py`의 `640`/`480` 등은 테스트 픽스처
값이며 실제 운영 설정과 결합되어 있지 않다 — 이관 대상 아님 (P2).

## 남은 항목 (Phase 1 범위 밖, 의도적으로 보류)

1. **P1 — Dockerfile `EXPOSE` / docker-compose 포트 매핑 이중 관리** (4개 컨테이너
   전부 해당). 컨테이너 이미지 빌드는 각 `Dockerfile`이 독립적으로 처리하므로
   compose와 값을 완전히 단일 출처화하기 어렵다. refactoring.md의 CI 단계(Phase 5)에서
   두 값이 실제로 일치하는지 자동 검증하는 스텝을 추가하는 쪽이 현실적 — 지금
   억지로 통합하지 않는다.
2. `containers/canvas/canvas_config*.py`를 `containers/pattern-command/config*.py`와
   다른 이름으로 유지해야 하는 이유(sys.path 충돌)는 `canvas_config.py` 상단
   docstring에 기록해 두었다 — 향후 두 컨테이너 중 하나라도 이름을 바꾸면 이
   제약이 사라지는지 재검토할 것.

## 요약 — Phase 1 완료 현황

- [x] **P0** `pattern-command`의 `CANVAS_WS_URL` 미정의 버그 수정 (커밋 1)
- [x] **P0** `pattern-command`가 `GestureConfig`를 `GestureClassifier`에 실제로 전달하도록 배선 (커밋 1)
- [x] **P0** `canvas`의 캔버스 해상도 중복 하드코딩 단일 출처화 (커밋 1)
- [x] **P1** Container C에 `config/pattern-command.yaml` 계층 도입 (커밋 2)
- [x] **P1** Container D에 `config/canvas.yaml` 계층 도입 (커밋 3)
- [x] **P1** Container A의 `SESSION_TOKEN` Fail-Fast 추가 (커밋 4)
- [ ] **P1** Dockerfile/compose 포트 이중 관리 — Phase 5(CI) 범위로 이월
