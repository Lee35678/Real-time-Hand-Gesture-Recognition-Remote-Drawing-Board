# 수동 스모크 테스트 체크리스트 (Phase 0 / §2.5)

자동 E2E 회귀가 없는 상태(characterization 테스트는 순수 로직만 커버)이므로,
**각 Phase 종료 시** 이 체크리스트를 실제 카메라로 수행하고 결과를
`docs/smoke_test_log.md`에 Phase별로 기록한다. 4개 컨테이너 전부(web,
canvas, vision-analysis, pattern-command)를 대상으로 한다.

## 0. 사전 준비

- [ ] `docker compose up --build` 로 4개 컨테이너 기동 (또는 개별 `uvicorn`/`python -m app.main` 실행)
- [ ] 모델 파일 존재 확인: `containers/vision-analysis/models/hand_landmarker.task`
      (Docker 빌드 시 자동 다운로드되지만, 로컬 직접 실행 시 수동 확보 필요)
- [ ] 브라우저에서 `http://localhost:8000/?t=<SESSION_TOKEN>` (모니터) 및
      `http://localhost:8000/capture.html?t=<SESSION_TOKEN>` (카메라 송출용, 보통 폰) 접속
      — `SESSION_TOKEN` 기본값은 `hand-board` (docker-compose 환경변수로 override 가능)

## 1. 정상 동작 골든 패스

- [ ] `/health` 4개 컨테이너 전부 `{"status":"ok", ...}` 응답
      (web, vision-analysis:8763, pattern-command:8761, canvas:8762)
- [ ] 손을 프레임에 진입 → 모니터 화면에 스켈레톤 오버레이가 나타난다
- [ ] 검지만 편 자세(엄지 비활성) → **DRAW** 모드 진입, 캔버스에 선이 그려진다
- [ ] 검지+중지를 편 자세 → **ERASE** 모드 진입, 지우개 커서가 나타나고 그림이 지워진다
- [ ] 검지만 편 채 엄지를 벌려 유지(3프레임 이상) → **ZOOM** 모드 잠김, 엄지-검지 간격을
      좁히거나(줌 아웃) 벌리면(줌 인, 또는 그 반대 — 잠금 시점 간격에 따라 방향이
      결정된다는 점에 유의, `docs/00_baseline.md` §5-2 참고) 캔버스가 확대/축소된다
- [ ] 손가락을 오므려 released(release_pip_angle 이하)로 3프레임 이상 유지 → DRAW/ERASE/ZOOM
      모드가 **IDLE**로 해제된다
- [ ] 손을 프레임에서 완전히 이탈 → 커서/스트로크가 사라지고(`hide_cursor`), IDLE 상태로 전환된다
- [ ] 손을 다시 진입시켜 위 사이클을 반복해도 이전 상태가 남아있지 않는다(잔상/오작동 없음)

## 2. 경계/장애 상황

- [ ] 손을 프레임 밖으로 완전히 빼도 어느 컨테이너에서도 크래시/예외 스택이
      로그에 남지 않는다 (특히 vision-analysis: `hand_present=False` 처리,
      pattern-command: `classifier.reset()` 처리)
- [ ] 손을 프레임 밖으로 뺀 상태에서 캔버스에 이전 스트로크의 선이 계속
      그려지거나(스트로크 잔류) 커서가 남아있지 않는다
- [ ] 손을 화면 가장자리(모서리)로 이동 — 랜드마크가 정규화 좌표 `[0,1]`을
      벗어나도(클램프하지 않는 현재 계약) 캔버스/커서 렌더링이 깨지지 않는다
      (`point()`가 범위 밖 좌표를 그대로 픽셀로 취급하는 분기를 타는지 확인,
      `containers/canvas/app.py:14`)
- [ ] **pattern-command 컨테이너를 먼저 내린 상태**(`docker compose stop pattern-command`)에서
      vision-analysis가 크래시하지 않고 계속 떠 있는지 확인 (`egress_client.py`의
      지수 백오프 재연결 로그만 남고 프로세스는 생존해야 한다)
- [ ] **canvas 컨테이너를 먼저 내린 상태**에서 pattern-command가 크래시하지
      않는지 확인 — ⚠️ 현재 `app.py`에 `CANVAS_WS_URL` 미정의 버그가 있어(§0 참고)
      첫 non-idle 명령에서 `NameError`로 죽을 수 있다. 이 체크가 **실패하면
      알려진 이슈**이지 새로운 회귀가 아니다 — `docs/00_baseline.md` §5-1 참고
- [ ] pattern-command를 나중에 다시 올렸을 때 vision-analysis가 자동 재연결하는지 확인
- [ ] 카메라를 한 프레임도 못 읽는 상황(폰 카메라 권한 거부 등)에서 web이
      죽지 않고 재연결 대기 상태를 유지하는지 확인

## 3. 종료 동작

- [ ] 각 컨테이너를 `Ctrl+C`(로컬 실행 시) 또는 `docker compose down`으로
      종료할 때 예외 스택 없이 정상 종료 로그가 남는다
      (vision-analysis: `SIGINT`/`SIGTERM` 핸들러 등록, Windows에서는
      `SIGTERM` 핸들러 등록이 불가능하므로 `Ctrl+C`(SIGINT)만 확인하면 된다)
- [ ] 종료 후 좀비 프로세스/열린 포트가 남지 않는다 (`netstat`으로 8000/8760/8761/8762/8763 확인)
- [ ] MediaPipe `HandLandmarker`가 정상적으로 `close()`되는지 확인(재시작 시
      "device busy" 류의 에러가 나지 않으면 통과로 간주)

## 4. 회귀 확인 (자동)

- [ ] `cd containers/vision-analysis && pytest` 통과 (46개)
- [ ] `cd containers/pattern-command && pytest` 통과 (16개)
- [ ] `cd containers/canvas && pytest` 통과 (10개)
- [ ] `python tests/fixtures/generate_characterization.py`를 재실행했을 때
      `tests/fixtures/characterization.json`이 **변경되지 않는다**
      (diff 없음 = 순수 로직 동작 불변 확인. 변경되면 회귀이거나, 의도된
      동작 변경이면 리뷰 후 스냅샷을 갱신)

## 기록 방법

각 Phase 종료 시 위 체크리스트 결과를 `docs/smoke_test_log.md`에 아래 형식으로
추가한다 (이 파일 자체는 Phase 1부터 생성):

```
## Phase N — 2026-MM-DD
- 환경: 카메라 XXX, 조명 XXX, OS XXX
- 1. 정상 동작 골든 패스: PASS/FAIL (실패 시 상세)
- 2. 경계/장애 상황: PASS/FAIL
- 3. 종료 동작: PASS/FAIL
- 4. 회귀 확인: PASS/FAIL
- 알려진 이슈(신규 회귀 아님): ...
```
