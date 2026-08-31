# 수동 스모크 테스트 기록

`docs/smoke_test_checklist.md`의 실행 결과를 Phase별로 남기는 로그다. 체크리스트는
**실제 카메라**가 있어야 수행 가능하다.

> ⚠️ **현재 상태: 카메라 기반 수동 체크리스트는 아직 한 번도 수행되지 않았다.**
>
> Phase 0~5는 이 세션(에이전트 실행 환경)에서 진행됐고, 이 환경에는 카메라 장치가
> 없다 — Phase 3에서 3-3/3-6 항목이 "카메라 문제로 보류"된 것과 같은 제약이다
> (`docs/00_baseline_metrics.md` §4 참고). 아래는 **각 Phase에서 실제로 수행한
> 자동 검증**(회귀 테스트, 특성화 스냅샷, 린트/타입, Docker 빌드)의 기록이다 —
> `docs/smoke_test_checklist.md` §1~3(실제 카메라로 손 제스처를 수행하는 골든
> 패스/경계 상황/종료 동작)은 **사람이 실제 카메라로 직접 수행해야** 채울 수 있는
> 항목이라 아직 미기입 상태로 남겨둔다. `docs/smoke_test_checklist.md`를 그대로 따라
> `docker compose up --build`로 4개 컨테이너를 띄운 뒤 결과를 이 파일에 추가해달라.

## 자동 검증 기록 (§4 회귀 확인에 해당)

| Phase | 회귀 테스트 (pytest, 4개 컨테이너) | 특성화 스냅샷 diff | 린트/타입 | Docker 빌드 |
|---|---|---|---|---|
| 0 | — (베이스라인 확보 단계, 스냅샷 최초 생성) | 스냅샷 최초 생성 | — | — |
| 1 | PASS | 0 diff | — (Phase 5 이전) | — |
| 2 | PASS | 0 diff | — | — |
| 3 | PASS (`pytest -m slow` 메모리 누수 테스트 포함) | 0 diff | — | — |
| 4 | PASS (122개: web 5 / canvas 15 / pattern-command 23 / vision-analysis 79) | 0 diff | — | — |
| 5 | PASS (동일 122개) | 0 diff | `ruff check containers` all pass, `mypy`(4개 컨테이너 각각) all pass | 4개 Dockerfile 전부 로컬 빌드 성공 + `python -c "import app"` (web/canvas/pattern-command), `import app.main`(vision-analysis) 성공 확인 |

> 정확한 현재 테스트 개수는 드리프트될 수 있으니 `cd containers/<name> && pytest -q`로
> 직접 확인하는 쪽이 이 표보다 신뢰도가 높다.

## §1~3 수동 카메라 체크리스트 — 미기입

아래는 `docs/smoke_test_checklist.md` §1(정상 동작 골든 패스), §2(경계/장애 상황),
§3(종료 동작)을 실제 카메라로 수행한 뒤 채워 넣을 자리다.

```
## Phase N — YYYY-MM-DD
- 환경: 카메라 XXX, 조명 XXX, OS XXX
- 1. 정상 동작 골든 패스: PASS/FAIL (실패 시 상세)
- 2. 경계/장애 상황: PASS/FAIL
- 3. 종료 동작: PASS/FAIL
- 알려진 이슈(신규 회귀 아님): ...
```
