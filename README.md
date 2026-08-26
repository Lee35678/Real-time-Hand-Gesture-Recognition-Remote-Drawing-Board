# MediaPipe 손 제스처 규칙 테스트

현재 단계는 전체 원격 그림판이 아니라 Container B의 21개 랜드마크 출력과
Container C의 규칙 기반 명령 판정을 검증하는 최소 프로토타입입니다.

## 전체 서비스 실행 (Docker Compose)

4개 컨테이너(web, canvas, vision-analysis, pattern-command)를 한 번에 띄워
원격 그림판 전체를 로컬에서 실행할 수 있습니다.

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
| vision-analysis | http://localhost:8763/health , http://localhost:8763/metrics |

종료는 `Ctrl+C`, 또는 다른 터미널에서 `docker compose down`.

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

## 프로토타입 단독 실행

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
향해도 2D 투영으로 거리 값이 무너지는 문제를 줄입니다.

- 검지·중지·약지·새끼 PIP 각도가 각각 120도 이상이면 해당 손가락 펴짐
- 각 손가락 상태는 최근 5프레임 중 4프레임 이상 유지돼야 확정
- 검지만 펴짐: `DRAW`
- 검지와 중지만 펴짐: `ERASE` (약지·새끼는 접힘)
- 검지만 펴짐: `DRAW` (중지·약지·새끼는 모두 접힘)
- 엄지가 활성화되면 즉시 `DRAW`를 중단하고 줌 시작 자세를 확인
- 엄지-검지 간격이 0.80 이하인 "모은" 자세로 시작하면 `ZOOM_IN` 잠금
- 엄지-검지 간격이 1.00 이상인 "벌린" 자세로 시작하면 `ZOOM_OUT` 잠금
- 줌 잠금 이후에는 손가락 간격이 변해도 처음 정한 방향만 유지
- 줌 모드가 시작되면 검지를 접거나 다른 명령 자세로 바꿀 때까지 `DRAW`로 돌아가지 않음
- 명령이 시작되면 모드가 잠기며, 검지를 3프레임 접을 때까지 다른 명령으로 바뀌지 않음

확대·축소는 손 크기에 따라 달라지지 않도록 `엄지 끝–검지 끝 거리 / 손바닥 너비`를
사용합니다. 0.80~1.00 사이는 줌 시작 방향이 불명확한 중립 구간이라 명령을 만들지
않습니다. 줌 방향은 시작 자세에서만 결정됩니다.
