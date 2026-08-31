# 운영 가이드

신규 개발자가 이 저장소를 받아서 로컬에서 띄우고, 설정을 바꾸고, 로그를 읽고, CI를
로컬에서 재현하는 데 필요한 모든 실무 정보를 모은 문서다. 아키텍처/컨테이너 경계에서
주고받는 메시지 스키마는 `docs/contract.md`, 성능 베이스라인·하드코딩 인벤토리 등
리팩토링 이력은 `docs/00_*.md`를 본다.

## 1. 아키텍처 한눈에 보기

4개 컨테이너가 각자 독립 프로세스로 뜬다 (하나로 빌드되는 단일 패키지가 아니다).

| 컨테이너 | 코드 위치 | 기본 포트 | 역할 |
|---|---|---|---|
| web (Container A) | `containers/web/` | 8000 | 게이트웨이 — 카메라 프레임 수신, QR/토큰 발급, 모니터 UI, 프레임 재중계 |
| vision-analysis (Container B) | `containers/vision-analysis/` | 8760(ingest), 8763(health/metrics) | MediaPipe Hand Landmarker + One Euro Filter + 좌표 후처리 |
| pattern-command (Container C) | `containers/pattern-command/` | 8761 | 랜드마크 → DRAW/ERASE/ZOOM 규칙 판정 (`gesture_classifier.py`) |
| canvas (Container D) | `containers/canvas/` | 8762 | 명령 적용 및 캔버스 렌더링 |

각 컨테이너는 자체 `requirements*.txt`, `pytest.ini`, `Dockerfile`을 갖는다. 컨테이너마다
동일한 이름의 모듈(`app`, `config`, `tests`)이 있어서 **반드시 해당 컨테이너 디렉토리
안에서** 독립적으로 실행해야 한다 — 저장소 루트에서 합쳐서 실행하면 모듈명이 충돌한다.

## 2. 로컬 실행

### 2.1 Docker Compose (권장)

```powershell
docker compose up --build
```

`docker-compose.yml`이 4개 컨테이너의 빌드 컨텍스트(전부 저장소 루트)·환경변수·컨테이너 간
URL을 이미 배선해 둔다. `SESSION_TOKEN`, `PUBLIC_BASE_URL`은 셸 환경변수로 오버라이드할
수 있다 (`docker-compose.yml`의 `${SESSION_TOKEN:-hand-board}` 참고).

휴대폰 카메라로 원격 테스트하려면 `.\start_remote.ps1` (ngrok 터널링, README 참고).

### 2.2 컨테이너 개별 실행 (디버깅용)

```powershell
cd containers/vision-analysis
pip install -r requirements-dev.txt
python -m app.main            # vision-analysis만 별도 실행

cd containers/pattern-command
pip install -r requirements.txt
uvicorn app:app --port 8761

cd containers/canvas
pip install -r ../../requirements.txt   # 루트 requirements.txt 공용
uvicorn app:app --port 8762

cd containers/web
pip install -r ../../requirements.txt
uvicorn app:app --port 8000
```

vision-analysis를 Docker 없이 로컬 실행하는 경우 모델 파일을 직접 받아야 한다
(Docker 이미지는 빌드 시점에 자동으로 받는다) — `HAND_LANDMARKER_MODEL_PATH` 환경변수로
경로를 지정하거나 `containers/vision-analysis/models/hand_landmarker.task`에 둔다.

## 3. 설정 (config/*.yaml)

`web`을 제외한 3개 컨테이너(vision-analysis, pattern-command, canvas)는 동일한 계층형
설정 로더 패턴을 쓴다 (`containers/<name>/app/config/loader.py` 또는
`containers/<name>/config_loader.py`).

**우선순위**: 환경변수 > `config/<service>.{APP_ENV}.yaml` > `config/<service>.yaml`
(기본값) > 코드 기본값.

- `APP_ENV` 환경변수(`dev` | `prod`, 기본 `dev`)가 어떤 `.{APP_ENV}.yaml`을 얹을지 결정한다.
- 각 설정 필드는 YAML 키 경로와 1:1로 대응하는 **전용 환경변수명**을 갖는다
  (예: `pipeline.target_width` ↔ `VISION_TARGET_WIDTH`). 이 매핑은 코드에만 있고 이
  문서에는 중복하지 않는다 — 정확한 이름은 각 컨테이너의 `app/config/__init__.py`
  (vision-analysis) 또는 `config.py`(pattern-command) / `canvas_config.py`(canvas)에서
  `resolve_*(...)` 호출의 첫 인자를 확인한다. 값 자체(기본값, 의미, 단위)는
  `config/<service>.yaml`의 주석에 있다.
- 잘못된 설정은 **기동 즉시** 거부된다 (Fail Fast, Pillar 1-2) — `validate()`가
  pydantic 스키마로 타입/범위/논리적 제약(예: `pinch_exit > pinch_enter` 류)을 검사하고,
  실패하면 어떤 키가 왜 잘못됐는지 메시지와 함께 프로세스가 종료한다.
- `web`은 YAML 계층이 없다 — 순수 환경변수 기반이다(`VISION_ANALYSIS_WS_URL`,
  `SESSION_TOKEN`, `PUBLIC_BASE_URL`, `WEB_LOG_*`). `APP_ENV=prod`인데 `SESSION_TOKEN`이
  기본값(`hand-board`, 소스에 그대로 노출된 값)이면 기동을 거부한다 — 프로덕션에서
  누구나 세션에 프레임을 흘려보낼 수 있는 상태로 뜨는 것을 막기 위함이다.

### 새 설정 항목을 추가하려면

1. `config/<service>.yaml`(및 필요하면 `.dev.yaml`/`.prod.yaml`)에 기본값 + 주석 추가.
2. 해당 컨테이너의 `Settings` dataclass에 `resolve_*("ENV_NAME", ("yaml","path"), default)`
   필드 추가.
3. 논리적 제약이 있으면 `schema.py`/`config_schema.py`의 pydantic 모델에 검증 추가.
4. `python -m mypy .`(해당 컨테이너 디렉토리에서) + `pytest` 통과 확인.

## 4. 로깅

4개 컨테이너 모두 동일한 설계의 로깅 모듈을 쓴다 (`app/observability/logging.py`
또는 `logging_setup.py` / `canvas_logging_setup.py` — canvas·pattern-command는 이름이
겹치는 모듈이라 canvas 쪽에 `canvas_` 접두어를 붙였다, sys.path 충돌 방지).

- **포맷**: `log_format: console`(개발, 컬러 콘솔) 또는 `json`(운영, 구조화 로그) —
  설정으로 전환. `config/<service>.{dev,prod}.yaml`에서 dev는 console, prod는 json으로
  이미 갈라져 있다.
- **컨텍스트**: 모든 로그 레코드에 `session_id`/`frame_id`가 `contextvars` 기반으로
  자동 주입된다 — 컨테이너 경계를 넘어 같은 세션의 로그를 상호 대조할 수 있다.
- **레벨**: `DEBUG`(프레임 단위 상세, 운영 기본값 아님) / `INFO`(수명주기, 상태 전이) /
  `WARN`(저하되었지만 지속 동작 — 프레임 드롭, 재연결 시도) / `ERROR`(기능 실패,
  프로세스는 생존) / `CRITICAL`(설정 검증 실패 등 프로세스 종료 유발).
- **로테이션**: `log_path`를 지정하면 `RotatingFileHandler`(설정된 `max_bytes`/
  `backup_count`)가 붙는다. 비워두면 stdout만 — 컨테이너 환경(Docker/K8s)에서는 보통
  stdout만으로 충분하고, 로그 수집기가 그 앞단을 담당한다.
- **개인정보**: 원본 카메라 프레임은 로그/디스크에 절대 저장하지 않는다. 랜드마크 원시
  좌표는 개념상 `DEBUG`에서만 노출 가능하고 운영 기본값(`INFO`)에서는 나가지 않는다.

## 5. CI (`.github/workflows/ci.yml`)

`main` push와 PR마다 5개 job이 각자 독립적으로 돈다 (하나가 실패해도 나머지는 계속
실행됨, `fail-fast: false`). 로컬에서 그대로 재현하려면:

| Job | 로컬 재현 |
|---|---|
| `quality` | `ruff check containers` (루트에서 1회) + 컨테이너별 `cd containers/<name> && python -m mypy .` |
| `test` | 컨테이너별 `cd containers/<name> && pytest -q` |
| `characterization` | `python tests/fixtures/generate_characterization.py` 후 `git diff --exit-code tests/fixtures/characterization.json` — diff가 나오면 순수 판정 로직(gesture_classifier/index_finger/geometry/smoothing)의 동작이 바뀐 것. 의도된 변경이면 리뷰 후 스냅샷 갱신, 아니면 회귀. |
| `config-validation` | 컨테이너 디렉토리 안에서 `APP_ENV=dev`/`APP_ENV=prod` 각각으로 `load_settings()` → `validate()` 실행 (예: `python -c "from config import load_settings, validate; validate(load_settings())"`, 컨테이너별 import 경로는 3절 참고) |
| `docker-build` | 루트에서 `docker build -f containers/<name>/Dockerfile .` (빌드만, push 없음) |

CI는 **품질 게이트까지만** 다룬다. `deploy`/`release`/registry push job은 의도적으로
없다 (refactoring.md §4-1 지침, §8 금지사항 4) — CD가 필요해지면 별도 논의 대상이다.

ruff/mypy 설정은 루트 `pyproject.toml` 하나를 4개 컨테이너가 공유한다 (컨테이너별
`pip install -e .` 패키지가 아니라 순수 린트/타입체크 설정 전용 — 컨테이너마다
`app`/`config`/`tests`처럼 이름이 겹치는 모듈이 있어서 하나로 합쳐 검사할 수 없다).

## 6. 헬스체크 / 관측

| 컨테이너 | 엔드포인트 | 내용 |
|---|---|---|
| web | `GET /health` | `{"status":"ok","role":"A-web-gateway"}` |
| vision-analysis | `GET :8763/health`, `GET :8763/metrics` | 프로세스 상태, 단계별(capture/preprocess/inference/smoothing/postprocess) 지연 p50/p95/p99 |
| pattern-command | `GET /health` | `{"status":"ok","sessions":N}` |
| canvas | `GET /health` | `{"status":"ok","sessions":N}` |

vision-analysis는 `observability.stage_log_every_n_frames`마다 단계별 지연 요약을
INFO로도 로깅한다 — `pipeline.target_latency_budget_ms`를 초과하면 WARN.

## 7. 트러블슈팅

- **컨테이너 하나가 계속 재연결 로그만 남긴다** — 정상 동작이다. vision-analysis↔
  pattern-command, pattern-command↔canvas 사이는 지수 백오프 재연결이 구현되어 있어
  한쪽이 죽어도 나머지 파이프라인은 살아있는다 (Pillar 2). `docs/smoke_test_checklist.md`
  §2가 이 시나리오를 다룬다.
- **`pytest`를 저장소 루트에서 실행했더니 이상하게 동작한다** — 루트 `pytest.ini`는
  의도적으로 `tests/fixtures`만 스코프로 잡는다. 컨테이너별 스위트는
  `cd containers/<name> && pytest`로만 실행한다 (2절 참고 — 모듈명 충돌 방지).
- **mypy가 저장소 루트에서 실행하면 "Duplicate module" 에러를 낸다** — 같은 이유.
  반드시 컨테이너 디렉토리 안에서 실행한다 (5절 표 참고).
- **설정을 바꿨는데 반영이 안 된다** — 환경변수가 YAML보다 항상 우선한다 (3절). 셸에
  같은 이름의 환경변수가 이미 설정되어 있지 않은지 먼저 확인한다.
- **`config-validation`/기동 시 "configuration rejected, refusing to start"** — Fail
  Fast가 의도대로 동작한 것. 에러 메시지에 어떤 키가 왜 잘못됐는지 나온다.
