# 00. 베이스라인 성능 측정 (Phase 0 §2.3 / Phase 3 진입 조건)

> refactoring.md §2.3: "리팩토링 전 수치를 반드시 기록한다. Phase 3의 개선 근거이자
> 회귀 판단 기준이다." 이 문서는 그 기록이다. **카메라 기반 수치(E2E FPS/드롭률/
> 장시간 메모리)는 이 PC의 로컬 환경 문제로 측정하지 못했다** — 아래 §3에 그대로
> 기록해 둔다. 정직하게 "미측정"으로 남기는 것이 잘못된 숫자를 근거로 최적화하는
> 것보다 낫다.

## 1. 측정 도구 (신규 작성, `containers/vision-analysis/scripts/`)

| 스크립트 | 역할 | 카메라 필요 여부 |
|---|---|---|
| `bench_pure_overhead.py` | 전처리/스무딩/기하연산/패킷 직렬화를 합성 데이터로 직접 호출해 시간 측정 | 불필요 |
| `bench_e2e_sink.py` | Container C 스탠드인 — 수신 패킷의 seq/capture_ts/processed_ts를 JSONL로 기록만 함(분석은 별도) | 불필요(측정 대상 프레임의 출처는 무관) |
| `bench_analyze.py` | `bench_e2e_sink.py`가 남긴 JSONL을 읽어 E2E 지연 p50/p95/p99, 처리 FPS, 드롭률 계산 | 불필요 |
| `bench_stream_and_monitor.py` | 실제 웹캠 프레임을 ingest 프로토콜로 스트리밍하면서 지정한 PID의 RSS/CPU를 주기적으로 샘플링 | **필요** |

`dev_camera_source.py`/`dev_pattern_sink.py`(기존, 사람이 읽는 콘솔 출력용)는 건드리지 않았다 —
위 4개는 측정 전용으로 새로 분리했다.

## 2. 순수 파이프라인 오버헤드 (측정 완료 — 카메라·MediaPipe 불필요, 완전 재현 가능)

`python scripts/bench_pure_overhead.py --iterations 2000` 결과 (이 PC, Python 3.12.10,
Windows, CPU 위임 기준). MediaPipe 추론 자체는 제외 — 그 값은 §3의 `/metrics`
`inference_ms_p50/p95`로 별도 확인해야 한다(카메라 문제로 아직 못함, §3 참고).

| 단계 | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 전처리(RGB 변환+회전/미러+letterbox, CLAHE 미사용) | 0.921 | 1.222 | 1.552 |
| 전처리(CLAHE 사용) | 2.627 | 3.711 | 4.166 |
| One Euro Filter `apply()`(21 랜드마크) | 0.042 | 0.080 | 0.111 |
| 기하 연산(`hand_scale`+`is_near_edge`+`max_displacement`) | 0.006 | 0.006 | 0.010 |
| `LandmarkPacket` 생성 + JSON 직렬화 | 0.055 | 0.081 | 0.144 |

**해석**: 전처리+스무딩+기하연산+직렬화를 다 합쳐도 p99 기준 ~1.8ms(CLAHE 미사용
시)로, MediaPipe CPU 추론이 통상 수 ms~수십 ms대인 것에 비해 무시할 수준이다.
"20%(동작 코드)/80%(인프라)"라는 refactoring.md의 전제와 달리, **적어도 이
파이프라인 코드 자체는 이미 가벼워서 3-3(병렬화) 같은 구조적 최적화가 필요할
근거가 현재로선 없다** — CLAHE를 켜면 전처리 단계가 약 2.9배 느려지므로, CLAHE는
저조도 환경에서만 켜는 옵션(`pipeline.enable_clahe`, 기본 false)으로 유지하는 게
맞다는 것도 이 수치로 확인된다.

## 3. 카메라 기반 측정 — 미완료 (환경 문제)

### 3.1 시도한 것

`bench_stream_and_monitor.py`로 이 PC의 웹캠(index 0)을 열어 실제 스트리밍을
시도했다:

- OpenCV 기본 백엔드(MSMF)는 `cap.read()` 자체가 실패한다
  (`OnReadSample() ... error status: -1072875772`).
- DirectShow(`cv2.CAP_DSHOW`)로 재시도하면 프레임은 읽히지만, **`cap.read()`
  호출마다 정확히 1.000초가 걸린다** — `CAP_PROP_FPS`/`FRAME_WIDTH`/`HEIGHT`/
  `BUFFERSIZE`를 조정해도 동일. 디바이스는 30fps를 보고하지만 실제로는 1fps로
  고정되어 있다. 정확히 1.000초라는 값은 대역폭 한계보다 드라이버/백엔드 쪽
  타임아웃 아티팩트에 가깝다.

### 3.2 그래도 확인된 것 (8프레임 시험 실행, 통계적으로 유의미하지 않음 — 참고용)

| 항목 | 값 |
|---|---|
| capture_ts → processed_ts (E2E, 프레임당) | 15~35ms (8개 샘플) |
| RSS (기동 직후 → 웜업 후 안정) | ~123MB → ~172MB |
| CPU (1fps 입력 기준) | 0~6% |

이 수치는 **입력이 1fps일 때**의 값이라 "입력 FPS 대비 처리 FPS", "드롭률",
"10분 연속 구동 메모리 증가량" 같은 §2.3의 핵심 질문에는 답하지 못한다 — 시스템이
전혀 부하를 받지 않기 때문이다. E2E 지연 자체(15~35ms)는 낮게 나왔지만 표본이
8개뿐이라 p95/p99를 신뢰할 수 없다.

### 3.3 재측정 방법 (카메라 문제 해결 후)

```powershell
# 1) vision-analysis를 로컬로 기동 (PATTERN_COMMAND_WS_URL을 sink로 돌림)
cd containers/vision-analysis
$env:PATTERN_COMMAND_WS_URL = "ws://127.0.0.1:8761/landmarks"
python -m app.main

# 2) 측정용 sink 기동 (다른 터미널)
python scripts/bench_e2e_sink.py --out docs/perf/run1.jsonl

# 3) 실제 웹캠으로 스트리밍 + RSS/CPU 샘플링 (또 다른 터미널, <PID>는 1번 프로세스)
python scripts/bench_stream_and_monitor.py `
  --url ws://127.0.0.1:8760/ingest/bench-session --camera 0 --fps 30 `
  --duration-sec 40 --pid <PID> --rss-out docs/perf/run1_rss.csv

# 4) 분석
python scripts/bench_analyze.py docs/perf/run1.jsonl
```

refactoring.md §2.3 규칙대로 위 3~4단계를 **동일 조건으로 3회 반복**하고
중앙값을 기록하며, 조명/카메라 거리/배경 조건을 함께 남긴다. 회차 간 편차가
20%를 넘으면 측정 환경부터 재점검한다. 10분 연속 구동 메모리 증가량은
`--duration-sec 600`으로 별도 실행해 `run*_rss.csv`의 시작/끝 `rss_bytes`를
비교한다.

## 4. Phase 3 진행 범위에 대한 결정

카메라와 무관하게 진행 가능한 것만 이번에 진행했다:

- [x] 3-1 단계별 지연 계측 체계 구축 — `MetricsCollector.record_stage()` +
      `pipeline/runner.py`의 preprocess/smoothing/postprocess/total 계측,
      `/metrics`의 `stage_latencies_ms` 필드, 예산 초과 시 WARN, 100프레임마다
      INFO 스냅샷. 카메라 재측정 시 바로 값이 채워진다.
- [x] 3-4 프레임 처리 최적화 체크리스트 검증 — 대부분 이미 충족(cvtColor 1회,
      imshow 없음, deque(maxlen) 사용 중). 실제 발견: `letterbox_resize`가
      소스가 이미 목표 해상도와 같아도 매번 `cv2.resize`+캔버스 복사를
      했음 — fast path 추가로 해결(전처리 p50 0.92ms → 0.29ms, 순수
      오버헤드 벤치마크로 직접 비교 확인).
- [x] 3-5 메모리 누수 점검 — 합성 데이터 10,000회 반복(`tests/perf/test_memory_leak.py`,
      `pytest -m slow`) 결과 누수 없음. 카메라·MediaPipe 네이티브 메모리는
      제외(카메라 재측정 시 확인).

아래는 여전히 보류 상태다(카메라 문제 해결 전까지):

- [ ] 3-3 병렬 처리 도입 여부 — "병목으로 확인된 경우에만" 도입해야 하는데 병목 확인 자체가 불가능
- [ ] 3-6 최종 수용 기준(E2E p95, 처리 FPS ≥90%, 드롭률 <5%, 10분 구동 RSS 증가 <50MB) 검증
