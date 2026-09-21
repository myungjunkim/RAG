# Task 13: 검색 품질 평가 스크립트, 통합 테스트, README

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 13 (3130~3363행)
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md` §8
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 7~11 전부. 실행 검증은 Ollama 모델(`bge-m3`, `qwen3:14b`)과 실데이터 인제스트 필요.
- 상태: **신규 구현 — Builder 진행 중** (Task 12 Validator 검증과 병행, 2026-09-21 지시. 파일 겹침 없음)

## 목표

(1) `eval/questions.yaml`의 질문마다 상위 k 청크에 기대 문서가 포함되는지 재는 `hit@k` 스크립트, (2) Ollama가 있을 때만 도는 end-to-end 통합 테스트, (3) 실행 절차·튜닝 포인트·주의 사항을 담은 README.

## 설계

### 컴포넌트

| 파일 | 책임 |
|---|---|
| `eval/__init__.py`, `eval/questions.yaml` | 평가 세트. OpenAPI 3문항은 즉시 사용 가능, Confluence 문항은 인제스트 후 `data/manifest.json`에서 page id를 채움(주석 템플릿) |
| `eval/run_eval.py` | `python -m eval.run_eval --active-profile=local [--k 6] [--file …]` → 질문별 O/X, `hit@k`, 80% 미만 종료 1 |
| `test/test_integration_ask.py` | `pytestmark = integration`. Ollama 미기동이면 skip. tmp Chroma에 `openapi_sample.json` 인제스트 → `/v1/ask` → 답변에 `/v1/messages/message`, sources에 `POST /v1/messages/message` |
| `README.md` | 사전 준비(Ollama·토큰), 개발 환경, 인제스트, 서버, 테스트, 튜닝 포인트 + **리뷰 2 인계 사항** |

### 인터페이스 (Produces)

```python
# eval/run_eval.py
def main() -> int   # 0: hit rate >= 0.8, 1: 미달 또는 질문 없음
_PASS_RATE = 0.8
```
질문 스키마: `{question: str, source: "all"|"confluence"|"openapi", expected_doc_ids: list[str]}`. hit = 상위 k 청크의 `metadata.doc_id` 중 하나라도 `expected_doc_ids`에 포함.

### 리드 결정 1: README에 반드시 들어갈 항목 (계획서 Step 4 + 인계)

계획서 README 초안에 아래를 **추가**한다(리뷰 1·2와 Task 명세에서 확정된 사실):
1. `--full` 재인제스트가 필요한 경우 3가지(리뷰 2 `[검증]`): 청킹 설정 변경 후 / 인제스트 중단 후 / `openapi_sources.yaml`에서 서비스 제거 후.
2. `openapi_sources.yaml`의 `name`은 유일해야 함(중복 시 마지막 항목만 반영, 경고 없음 — 리뷰 2 info 3).
3. Ollama 모델 미설치 시 `ingest.py`가 안내 후 종료 1하며 기존 인덱스는 건드리지 않음(리뷰 2 A-1).
4. 로그: `logs/app.log`(프로젝트 DEBUG, 서드파티 WARNING). `reload=True`로 기동 시 두 프로세스가 같은 파일에 기록(Task 11 리드 결정 3).
5. Chroma 텔레메트리 비활성화됨(Task 7 리드 결정 1).
6. 인증 정보: `CONFLUENCE_API_TOKEN` env 우선, ini `api-token`은 비워 둠(커밋 금지).
7. 유지보수 메모: `langchain-community` sunset 경고 — 사내 서버 이전 시 `BM25Retriever` 대체 검토(Task 9).
8. `requirements.in` 직접 명시 권고 2건(`langchain-text-splitters`, `langchain-classic`) — 사용자 결정 상태 기재.

### 리드 결정 2: 평가 세트 Confluence 문항

`[미확인]` Confluence 인제스트는 토큰이 필요해 에이전트가 수행할 수 없다. Builder는 계획서대로 OpenAPI 3문항 + Confluence 주석 템플릿으로 작성하고, Confluence 문항 채우기는 **사용자 작업**으로 README에 절차를 적는다(`data/manifest.json`에서 `source == "confluence"` 엔트리의 key가 page id). hit@k 80% 기준은 사용자가 문항을 채운 뒤 의미를 가진다 — 3문항만으로는 통계적 의미 없음을 README에 명시.

### 기각한 대안

- 평가에 LLM 답변 품질(LLM-as-judge) 포함: 로컬 14B 모델로 판정하면 비용·변동이 크고 PoC 목표(검색 재현율)와 다름. 검색 hit@k만.
- 통합 테스트에서 실데이터 컬렉션(`data/chroma`) 사용: 사용자 환경 상태에 의존 → 픽스처 스펙을 tmp 컬렉션에 인제스트하는 자족적 구성 유지.

## 작업 목록 (Builder)

1. `eval/__init__.py`, `eval/questions.yaml`, `eval/run_eval.py` 작성 — 계획서 Step 1·2 참조.
2. `test/test_integration_ask.py` 작성 — 계획서 Step 3 그대로. `pytest --active-profile=local -v`에서 deselected 확인.
3. `README.md` 작성 — 계획서 Step 4 초안 + 리드 결정 1의 8개 항목 + 리드 결정 2의 Confluence 문항 절차.
4. `python -m eval.run_eval --help` 정상. `python -m eval.run_eval --active-profile=local --file <빈 yaml>` → "평가 질문이 없습니다." 종료 1(Ollama 불필요 — 질문 로딩이 먼저).
5. 전체 `pytest --active-profile=local -v` → 회귀 없음.
6. 완료 보고.

**하지 않을 것:** 커밋, 실제 평가·통합 테스트 실행(Validator), README에 토큰·이메일 기입.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 회귀 없음 | 전체 green, integration deselected, 소켓 차단 통과 |
| `run_eval` 단위 동작 | 빈 yaml → 종료 1; `RetrieverService`를 monkeypatch한 가짜로 hit 2/3 → 출력 형식·종료 1, 3/3 → 종료 0 |
| README 항목 | 리드 결정 1의 8개 항목 존재 여부 체크리스트 |
| **조건부(Ollama+모델+인제스트)** | `python -m eval.run_eval --k 6` 실행 결과(O/X·hit@6) 기록; `pytest -m integration test/test_integration_ask.py` 1 PASSED. 조건 미충족 시 `[미확인]` |
| 계획서 전체 완료 기준(3367행) 대조 | 4항목 각각 PASS/조건부 기록 |

## 완료 기준

- [x] 전체 green (296 passed / 5 deselected, 소켓 차단 포함), integration deselected(`-m integration` 시 5/301)
- [x] `run_eval` 종료 코드·출력 형식 고정 — `test_run_eval.py` 9개 신설(빈 yaml 1, 3/3 → 0, 2/3 → 1 + 기대/실제 출력, `--k`·`source` 전달, `reload` 선행, 동봉 yaml 스키마)
- [x] README에 리드 결정 1 항목 11개 + 결정 2 절차 — 전부 PASS, 자격 증명 0건(정규식 스캔), 84~86행 수정본이 Task 11 실기동 관측과 일치
- [ ] 평가·통합 실행 — **`[미확인]`**: `run_eval` 실행은 정상 동작했으나 컬렉션이 비어 0/3(검색 결함 아님). 통합 테스트는 모델 부재로 ERROR(아래 비차단 1)

## 계획서 전체 완료 기준(3367~3372행) 대조 (Validator)

| 완료 기준 | 판정 | 근거 |
|---|---|---|
| `pytest --active-profile=local` 전체 통과(Ollama 없이) | **PASS** | 296 passed, 소켓 차단 동일 |
| `ingest.py --source all` + 재실행 `추가 0 / 갱신 0` | `[미확인]` | `bge-m3` 미설치 + Confluence 토큰 미설정. 스펙 다운로드·렌더까지는 확인(Task 8) |
| `main.py` 기동 후 UI 스트리밍 답변 + 출처 카드 | **부분** | 기동·SSE·`/`·헤더 확인(Task 11·12). 브라우저 육안은 사용자 |
| `run_eval` hit@6 ≥ 80% | `[미확인]` | 인제스트 후 재실행 필요. 3문항은 통계적 의미 없음(README 명시) |

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. **통합 테스트 가드가 `ping_ollama()`만 확인** → Ollama는 떠 있고 모델만 없는 환경에서 skip이 아닌 ERROR. 환경 미비와 실제 실패를 구분하기 위해 가드에 모델 존재 확인이 필요. **리뷰 4 조치 후보** — `llm_factory`에 `has_model(name) -> bool`(`/api/tags` 목록 대조)을 두고 통합 픽스처 3곳(`test_llm_factory`, `test_rag_service`, `test_integration_ask`)에서 `pytest.skip`. 리뷰 4 결과와 함께 결정.
2. `test_integration_ask.py` 픽스처의 `ask_controller.context` 직접 대입·미복원 — 계획서 코드 그대로. 리뷰 3 B-1과 같은 패턴이므로 위 1과 함께 monkeypatch로 교체(Validator). 리뷰 4 조치 후보.
3. eval Q3 기대값에 두 서비스 `/check`를 모두 넣어 RRF 병합에도 hit 판정 안정 — 의도대로.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드·문서 기준 완료 기준 충족. 남은 조건: 모델 설치 후 실데이터 인제스트 → `run_eval` → 통합 테스트, 브라우저 육안 확인(사용자).
→ **리뷰 4 통과 (2026-09-21) — 커밋 대기.** 리뷰 4 A-1·A-2·A-3으로 README 보강, `run_eval` 소폭, `has_model` 추가, 통합 가드 교체(현재 환경 SKIP).

커밋 대상(사용자 수행): `eval/`, `test/test_integration_ask.py`, `test/test_run_eval.py`, `README.md`.

## 범위 제외

- LLM 답변 품질 평가, 재랭커 실험
- CI 파이프라인
- 사내 서버 Docker 이전 절차(별도 문서)
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 10 진행 중). Task 12 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 리드: Task 12 Builder 완료·리드 확인 후 Validator 검증과 병행해 Builder 지시. README 리드 결정 1 항목에 리뷰 3 인계(`reopen()`으로 `--full` 후 `/v1/reload` 가능, `requirements.in` 권고 3건째 `ollama`) 반영 필요 — 아래 추가.

### 리드 결정 1 추가 항목 (리뷰 3 반영)
9. `--full` 재인제스트 후에도 서버 재기동 없이 `POST /v1/reload`로 반영된다(리뷰 3 A-2 `reopen()`).
10. `requirements.in` 직접 명시 권고는 **3건**: `langchain-text-splitters`, `langchain-classic`, `ollama`.
11. 브라우저 UI 렌더링은 에이전트가 검증하지 못했으므로 README "서버" 절에 확인 절차(헤더 상태·스트리밍·소스 카드·오류 표시)를 체크리스트로 적는다.

### 진행 기록 (계속)
- 2026-09-21 Builder 완료: `eval/` 3파일, `test_integration_ask.py`, `README.md` 144줄. `run_eval --help` 정상, 빈 yaml → 종료 1(Ollama 불필요 확인). 전체 287 passed / 5 deselected(통합 정상 deselect). README에 리드 결정 1 항목 11개 + 결정 2 절차 반영, 토큰·이메일 미기입.
- 2026-09-21 리드: README 직접 확인 — 항목 전부 존재. **정확성 오류 1건**(84~85행): "Ollama 미기동이면 `/v1/ask` 503" → 실제는 빈 컬렉션이면 200+NOT_FOUND, 청크가 있고 LLM 실패 시 503(Task 11 실기동 확인). Builder에게 문장 수정 지시(작업 7). Validator 검증·리뷰 4 병행 착수.

- 2026-09-21 Builder 작업 7 완료: README 해당 문장 교체(4줄로 줄바꿈, 문구 동일), 146줄. 전체 296 passed / 5 deselected(Validator 추가분 포함). 리드 diff 확인 일치.
- 2026-09-21 Validator 회차 1: 코드·문서 완료 기준 전부 PASS, `test_run_eval.py` 9개. 계획서 전체 완료 기준 4항목 대조(1 PASS, 1 부분, 2 `[미확인]`). 비차단 3건.
- 2026-09-21 리드: 조건부 READY FOR REVIEW. 비차단 1·2 → 리뷰 4 조치 후보.

**7. (리드 확인 수정)** README 84~85행을 아래로 교체:
> Ollama 가 떠 있지 않아도 서버는 기동된다. 이 경우 `/check` 가 `degraded` 를 반환한다. `/v1/ask` 는 인덱스가 비어 있으면 LLM 을 호출하지 않고 "관련 내용을 문서에서 찾지 못했습니다." 를 200 으로 돌려주고, 청크가 있는 상태에서 LLM 호출이 실패하면 503(원인 메시지 포함), 응답 시간 초과는 504 로 구분된다.
