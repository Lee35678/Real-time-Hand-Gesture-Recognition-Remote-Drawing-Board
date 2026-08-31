# 컨테이너 간 인터페이스 계약

refactoring.md §5 — 4개 컨테이너 경계에서 실제로 주고받는 메시지 스키마를 코드에서
역추출해 고정한 문서다. **계약을 바꾸려면 `schema_version`을 올리고 이 문서도 함께
갱신한다.** 아래 4개 경계 각각 "누가 보내는가 / 어떤 프레임인가 / 필드 의미"만 다룬다 —
게이트웨이별 REST 엔드포인트, 설정 항목은 `docs/operations.md`를 본다.

```
[Container A: web]  ──①──►  [Container B: vision-analysis]  ──②──►  [Container C: pattern-command]  ──③──►  [Container D: canvas]
       ▲                                                                                                          │
       └──────────────────────────────────────④ (canvas 렌더 프레임, /ws/monitor로 재중계) ──────────────────────┘
```

모든 바이너리 프레임은 동일한 포장 형식을 쓴다: **4바이트 빅엔디안 길이 + UTF-8 JSON
메타데이터 + 그 뒤에 이어지는 원시 바이트(JPEG 또는 raw pixel)**. `pack()`/`unpack()`
헬퍼가 `containers/web/app.py`, `containers/canvas/app.py`에 각각 구현되어 있다(로직은
동일, 컨테이너마다 독립 구현).

---

## ① A → B: 카메라 프레임 (`ws://vision-analysis:8760/ingest/{session_id}`)

프레임마다 **텍스트 JSON 헤더 1개 + 그 직후 이어지는 BGR raw 바이트 1개**를 보낸다
(`containers/web/app.py`의 `camera()` 핸들러가 발신자, `containers/vision-analysis/app/contracts.py`의
`IngestFrameHeader.from_json()`이 수신측 파서).

```json
{
  "schema_version": "1.0",
  "session_id": "a1b2c3d4",
  "frame_id": "f-9f2a...",
  "seq": 10421,
  "captured_at_ms": 1735891234567,
  "width": 640,
  "height": 480,
  "channels": 3,
  "dtype": "uint8",
  "color_order": "BGR",
  "byte_length": 921600
}
```

- 헤더 직후 정확히 `width * height * 3`바이트의 BGR raw 픽셀이 이어진다.
- `channels`/`dtype`/`color_order`는 수신측이 검증만 하고 값 자체는 고정이다 (`3`/`uint8`/`BGR`).
- `rotation`(0/90/180/270 중 하나, 기본 0)과 `mirrored`(기본 false) 필드를 헤더에 추가로
  넣을 수 있다 — B가 추론 **이전**에 보정한다. C는 이미 보정된 좌표만 받으므로 추가 반전을
  하지 않는다.
- 잘못된 헤더(JSON 파싱 실패, 필수 키 누락, 지원하지 않는 `dtype`/`color_order`/`rotation`,
  0 이하 width/height)는 `ContractError`로 즉시 거부된다.

## ② B → C: 랜드마크 패킷 (`ws://pattern-command:8761/landmarks`)

B가 프레임마다 텍스트 JSON 1개를 보낸다 (`LandmarkPacket.to_json()`,
`containers/vision-analysis/app/contracts.py`). 상세 근거와 좌표계 설명은
`containers/vision-analysis/readme.md` §6을 함께 참고한다 — 아래는 그 문서와 실제
구현이 100% 일치함을 확인한 현재 스키마다.

```json
{
  "session_id": "a1b2c3d4",
  "seq": 10421,
  "capture_ts": 1735891234567,
  "processed_ts": 1735891234589,
  "hand_present": true,
  "frame": { "w": 640, "h": 480 },
  "handedness": { "label": "Right", "score": 0.98 },
  "landmarks": [{ "x": 0.412, "y": 0.633, "z": -0.021 }, "... 21개"],
  "world_landmarks": [{ "x": -0.031, "y": 0.042, "z": 0.008 }, "... 21개"],
  "hand_scale": 0.187,
  "quality": { "near_edge": false, "filtered": true, "outlier_dropped": false }
}
```

**계약 규칙** (`LandmarkPacket.__post_init__`이 강제):

1. 좌표계 — 원점 좌상단, x는 오른쪽, y는 **아래쪽**이 양의 방향.
2. `landmarks`는 정규화 `[0,1]` 기준이지만 프레임 밖으로 나간 랜드마크는 음수/1 초과가
   될 수 있다 — **클램핑하지 않는다.**
3. `landmarks`는 화면 좌표(그리기용), `world_landmarks`는 미터 단위(형태/거리 판별용).
   혼용 금지 — 핀치·줌 판정은 반드시 `world_landmarks`를 쓴다 (카메라 거리 불변).
4. `hand_present: false`일 때 `handedness`/`landmarks`/`world_landmarks`/`hand_scale`은
   전부 `null`. `hand_present: true`일 때는 전부 채워짐이 보장된다 — 둘 중 하나라도
   어기면 생성 시점에 `ContractError`가 발생한다(반쯤 채워진 패킷이 나갈 수 없음).
5. 변화량 계산의 시간 기준은 `capture_ts`. `processed_ts`는 지연 관측 전용.

## ③ C → D: 렌더 명령 (`ws://canvas:8762/commands/{session_id}`)

C가 B의 패킷 하나를 판정할 때마다 텍스트 JSON 1개를 canvas로 보낸다
(`SessionState._send_command`, `containers/pattern-command/app.py`).

```json
{
  "command": "DRAW",
  "mode": "DRAW",
  "seq": 10421,
  "index_tip": { "x": 0.412, "y": 0.633 },
  "index_direction": { "x": 0.016, "y": -0.032 },
  "landmarks": [{ "x": 0.412, "y": 0.633, "z": -0.021 }, "... 21개, 모니터 스켈레톤 오버레이용"]
}
```

- `command` ∈ `{IDLE, DRAW, ERASE, ZOOM_IN, ZOOM_OUT}` — 프레임 단위 순간 판정.
- `mode` ∈ `{IDLE, DRAW, ERASE, ZOOM}` — 잠긴 모드(락) 상태. 상세 규칙은 README의
  "현재 명령 규칙" 절과 `containers/pattern-command/gesture_classifier.py`.
- `index_tip`/`index_direction`이 없으면(`hand_present: false`) `command: "IDLE"`,
  `index_tip`/`index_direction`은 `null`.
- canvas는 이 JSON을 못 읽으면(파싱 실패, 필드 타입 불일치) 그 패킷만 버리고 세션은
  유지한다 — 계약 위반 1건이 세션 전체를 끊지 않는다.

## ④ D → A: 렌더 결과 (`ws://web:8000/ws/canvas-output/{session_id}`)

canvas가 명령을 그림에 적용한 뒤 렌더된 프레임을 web으로 보내면, web은 이를 그대로
`/ws/monitor` 구독자에게 재중계한다 (원본 카메라 프레임도 `kind: "source"`로 같은
경로에 함께 중계된다 — `containers/web/app.py`의 `publish()`).

메타데이터(JSON) + JPEG 바이트, ① 절 도입부의 포장 형식과 동일:

```json
{
  "kind": "canvas",
  "session_id": "a1b2c3d4",
  "frame_id": "f-9f2a...",
  "seq": 10421,
  "command": "DRAW",
  "mode": "DRAW",
  "zoom": 1.35,
  "inference_ms": null,
  "landmarks": [{ "x": 0.412, "y": 0.633, "z": -0.021 }, "..."]
}
```

- `kind`: `"source"`(web이 그대로 중계하는 원본 카메라 프레임) 또는
  `"canvas"`(canvas가 렌더링한 프레임) — 모니터 UI가 이 값으로 두 스트림을 구분한다.
- 이 경로는 **모니터링/디버깅 전용**이다. 파이프라인의 판정 로직은 여기 의존하지 않는다.

---

## 버전 관리

- 스키마 변경 시 ①의 `schema_version`을 올리고 이 문서의 해당 절을 함께 갱신한다.
- ②(B→C)는 `containers/vision-analysis/readme.md` §6에 더 상세한 배경(왜 이 필드들인지,
  왜 `world_landmarks`가 핀치/줌 판정에 필수인지)이 있다 — 필드 자체를 바꿀 때는 그
  문서도 같이 본다.
- 계약을 어기는 입력(①③)은 해당 프레임/패킷만 드롭하고 세션은 유지한다 — 어느 경계도
  잘못된 메시지 1건으로 프로세스가 죽지 않는다(Pillar 2).
