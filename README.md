# 실시간 손동작 인식 원격 드로잉 보드

휴대폰 카메라로 손을 비추면 PC 화면의 캔버스에 그림을 그리는 비접촉식 원격 드로잉
보드다. MediaPipe Hand Landmarker로 21개 손 랜드마크를 추출하고, 규칙 기반 판정으로
검지=`DRAW`, 검지+중지=`ERASE`, 엄지 개입=`ZOOM_IN`/`ZOOM_OUT`을 인식한다.

4개 컨테이너로 구성된 마이크로서비스 아키텍처다:

```
[web]  ──►  [vision-analysis]  ──►  [pattern-command]  ──►  [canvas]
 게이트웨이     MediaPipe 추론          제스처 규칙 판정        렌더링
 (Container A)  + 스무딩 (B)            (Container C)          (Container D)
```

각 경계에서 주고받는 메시지 스키마는 [`docs/contract.md`](docs/contract.md), 설정/로깅/CI를
포함한 운영 전반은 [`docs/operations.md`](docs/operations.md)를 본다. 이 저장소를
프로덕션 수준으로 끌어올린 리팩토링 작업 지시서와 그 이력은 [`refactoring.md`](refactoring.md)와
`docs/00_*.md`에 있다.

## 빠른 시작 (Docker Compose)

### 사전 준비

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치 및 실행 중이어야 합니다.
- 실제 휴대폰 카메라로 테스트하려면 [ngrok](https://ngrok.com) 계정과 authtoken이 필요합니다 (PC에서만
  써볼 거라면 생략 가능).

### 1. 저장소 받기

```powershell
git clone https://github.com/ddiw/Real-time-Hand-Gesture-Recognition-Remote-Drawing-Board.git
cd Real-time-Hand-Gesture-Recognition-Remote-Drawing-Board
```

### 2. 빌드 및 실행

```powershell
docker compose up --build
```

4개 컨테이너가 모두 뜨면 준비 완료입니다. 확인용 엔드포인트:

| 컨테이너 | 주소 |
| --- | --- |
| web | http://localhost:8000 |
| canvas | http://localhost:8762/health |
| pattern-command | http://localhost:8761/health |
| vision-analysis | http://localhost:8763/health , http://localhost:8763/metrics |

종료는 `Ctrl+C`, 또는 다른 터미널에서 `docker compose down`.

기본 설정(모델 임계값, 제스처 파라미터, 큐 크기, 로그 레벨 등)은 `config/*.yaml`에
있다. `APP_ENV=dev`/`prod` 전환과 환경변수 오버라이드 규칙은
[`docs/operations.md` §3](docs/operations.md#3-설정-configyaml)을 본다.

### 3. 휴대폰으로 실제 사용하기 (원격 모드)

카메라는 HTTPS에서만 접근을 허용하므로, 실제 휴대폰으로 테스트하려면 ngrok으로
로컬 서버를 HTTPS 터널링해야 합니다.

```powershell
ngrok config add-authtoken <ngrok 대시보드에서 받은 토큰>   # 최초 1회만
.\start_remote.ps1
```

콘솔에 뜨는 두 주소를 사용합니다.

- `Monitor` 주소 → PC 브라우저에서 열기 (QR 코드가 표시됩니다)
- `Phone` 주소 → 휴대폰 브라우저에서 열기, 또는 QR 스캔 후 카메라 권한 허용

종료는 스크립트 창에서 `Enter`를 눌러야 ngrok과 컨테이너가 함께 정리됩니다.

## 개발

각 컨테이너는 독립된 `requirements*.txt`/`pytest.ini`/`Dockerfile`을 갖는다. 컨테이너
간에 `app`/`config`/`tests` 같은 이름이 겹치는 모듈이 있어서 **반드시 해당 컨테이너
디렉토리 안에서** 실행한다.

```powershell
cd containers/vision-analysis   # 또는 pattern-command / canvas / web
pytest -q                       # 컨테이너별 테스트
python -m mypy .                # 컨테이너별 타입 체크
```

```powershell
ruff check containers           # 저장소 루트에서 1회 (4개 컨테이너 공통 린트 설정)
```

`main` push/PR마다 GitHub Actions(`.github/workflows/ci.yml`)가 lint·타입·테스트·설정
검증·Docker 빌드를 자동으로 돈다 — job 구성과 로컬 재현 방법은
[`docs/operations.md` §5](docs/operations.md#5-ci-githubworkflowsciyml)에 정리되어 있다.
CD(자동 배포)는 이 저장소 범위에서 의도적으로 제외되어 있다.

`tests/fixtures/characterization.json`은 제스처 판정 순수 로직(스무딩·거리 계산·상태
전이)의 리팩토링 전 출력을 고정한 회귀 스냅샷이다. 이 로직을 건드리는 변경은 반드시
`python tests/fixtures/generate_characterization.py` 재실행 후 diff가 없음을 확인한다.

실제 카메라로 하는 수동 확인 절차는 [`docs/smoke_test_checklist.md`](docs/smoke_test_checklist.md),
그 기록은 [`docs/smoke_test_log.md`](docs/smoke_test_log.md)에 남긴다.

## 프로토타입 단독 실행 (카메라 1대, 네트워크 없이)

4개 컨테이너를 전부 띄우지 않고 `canvas` 로직만 로컬 웹캠 창으로 빠르게 확인하고
싶을 때 쓰는 레거시 경로다. `containers/canvas/drawing_canvas.py`를 그대로 재사용한다.

```powershell
python -m pip install -r requirements.txt
.\download_model.ps1
python app.py
```

카메라가 여러 개인 경우 `python app.py --camera 1`처럼 번호를 바꿉니다.
종료는 `Q` 또는 `Esc`입니다.

창의 `CAPTURE` 버튼을 클릭하거나 스페이스바를 누르면 `captures/` 폴더에
다음 두 파일이 함께 저장됩니다.

- 화면에 판정 결과가 표시된 JPG 이미지
- 21개 `(x, y, z)` 좌표와 각도, 거리 비율, 판정 결과가 포함된 JSON

저장 위치는 `python app.py --output 내폴더`처럼 변경할 수 있습니다.

## 현재 명령 규칙

MediaPipe의 화면 좌표 대신 3D 월드 좌표를 사용합니다. 따라서 검지가 카메라를
향해도 2D 투영으로 거리 값이 무너지는 문제를 줄입니다. (판정 로직 소스:
`containers/pattern-command/gesture_classifier.py`, `index_finger.py`)

- 검지·중지·약지·새끼 PIP 각도가 각각 120도 이상이면 해당 손가락 펴짐
- 각 손가락 상태는 최근 5프레임 중 4프레임 이상 유지돼야 확정
- 검지만 펴짐: `DRAW`
- 검지와 중지만 펴짐: `ERASE` (약지·새끼는 접힘)
- 엄지가 활성화되면 즉시 `DRAW`를 중단하고 줌 시작 자세를 확인
- 엄지-검지 간격이 0.80 이하인 "모은" 자세로 시작하면 `ZOOM_IN` 잠금
- 엄지-검지 간격이 1.00 이상인 "벌린" 자세로 시작하면 `ZOOM_OUT` 잠금
- 줌 잠금 이후에는 손가락 간격이 변해도 처음 정한 방향만 유지
- 줌 모드가 시작되면 검지를 접거나 다른 명령 자세로 바꿀 때까지 `DRAW`로 돌아가지 않음
- 명령이 시작되면 모드가 잠기며, 검지를 3프레임 접을 때까지 다른 명령으로 바뀌지 않음

확대·축소는 손 크기에 따라 달라지지 않도록 `엄지 끝–검지 끝 거리 / 손바닥 너비`를
사용합니다. 0.80~1.00 사이는 줌 시작 방향이 불명확한 중립 구간이라 명령을 만들지
않습니다. 줌 방향은 시작 자세에서만 결정됩니다.
