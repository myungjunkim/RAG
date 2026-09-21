# 리뷰 3: Task 9~11 코드 리뷰 결과와 조치

- 일자: 2026-09-21
- 대상: Task 9(하이브리드 검색), 10(RAG 답변), 11(FastAPI 서버, `llm_factory.LLM_ERRORS`) — 전체 267 passed 기준선
- 방식: 읽기 전용 리뷰 에이전트(서버 기동·포트·Ollama 요청 금지, 인프로세스 ASGI로만 재현) 6개 관점 리뷰. 리드가 should-fix·nit를 재확인한 뒤 결정.

## 요약

- blocker: 없음
- should-fix 2건 + 연동 nit 1건 → 조치 A(Builder)
- nit 채택: `watchfiles` 억제(Builder, 조치 A), 테스트 전역 상태 복원·누락 테스트 3개(Validator, 조치 B)
- 검색→답변→SSE→Task 12 JS 계약 `[검증]`: 이벤트 4개, data 인코딩, `SourceRef` 5필드, `source` Literal, `top_k` 범위, `_strip_prefix`↔Task 6 접두어 — **전 구간 일치. 변경 없음.**
- 리드 결정 1~3 `[검증]`: 모두 타당. 503 detail의 `({e})`는 Ollama 자체 메시지만 포함(URL 미노출). `reload=True`는 `*.py`만 감시해 `logs/`·`data/` 쓰기로 리로드되지 않음.

## 조치 A (Builder)

### A-1. 동기 호출 엔드포인트를 스레드풀로 (should-fix #1)

**발견** `[검증]`(리뷰어 인프로세스 재현): `ask_controller.py`의 `ask`(`:56`)·`reload`(`:85`)·`health_check`(`:90`)가 `async def`인데 내부에서 동기 `rag_service.ask`(LLM `invoke`, 최대 120초)·`retriever.reload()`·`ping_ollama()`(최대 3초)를 호출한다. 이벤트 루프가 그 동안 멈춰 `/`, `/check`, 다른 스트림 요청이 전부 대기한다. 계획서 참조 구현에서 물려받은 문제.

**결정: 수정.** FastAPI는 `def` 엔드포인트를 스레드풀에서 실행하므로 세 함수의 `async` 키워드를 제거한다. `ask_stream`은 `astream`이 비동기라 유지하되, 제너레이터 안의 동기 `search()`(임베딩 HTTP 1회)는 `RagService.ask_stream`에서 `asyncio.to_thread`로 감싼다.

**변경**:
```python
# ask_controller.py — 세 엔드포인트 시그니처만 변경 (본문 동일)
@router.post(f"/{__api_root}/ask", response_model=AskResponse, tags=["질의"])
def ask(request: AskRequest):                 # async 제거 — 동기 LLM 호출을 스레드풀에서 실행
...
@router.post(f"/{__api_root}/reload", response_model=ReloadResponse, tags=["관리"])
def reload():                                 # async 제거
...
@router.get(f"/{__health_endpoint}", response_model=HealthResponse, tags=["health check"])
def health_check():                           # async 제거 — ping_ollama 최대 3초 블로킹
```
```python
# rag_service.py — ask_stream 첫 줄
import asyncio
...
async def ask_stream(self, question, source="all", top_k=None):
    # 검색(임베딩 HTTP 1회)은 동기이므로 이벤트 루프를 막지 않도록 스레드에서 실행
    chunks = await asyncio.to_thread(self._retriever.search, question, source, top_k)
```
`ask_stream` 엔드포인트와 `_sse`·`generate`는 변경 없음. 계획서 테스트 8개(`TestClient`)는 `def` 엔드포인트도 동일하게 동작.

### A-2. `--full` 후 컬렉션 재오픈 (should-fix #2)

**발견** `[검증]`(동일 프로세스 재현) / `[추측]`(별도 프로세스도 동일): `ingest.py --full`은 `reset_all()` → `delete_collection()` → 재생성으로 컬렉션 UUID가 바뀐다. 서버의 `Chroma` 객체는 옛 UUID를 들고 있어 이후 `reload()`(`get_all`)·벡터 검색(`as_retriever`)이 `chromadb.errors.NotFoundError` → `/v1/reload` 500, `/v1/ask` 500(`LLM_ERRORS` 아님), 재기동 필요. README 계획의 "`--full` 후 `/v1/reload`" 흐름과 충돌.

**결정: 수정.** 인덱스 재구성 시 컬렉션 핸들도 다시 연다. README 안내(재기동)만으로 두는 대안은 운영 흐름을 깨뜨려 기각.

**변경**:
```python
# vector_store_repository.py — 메서드 1개 추가
def reopen(self) -> None:
    """인제스트 프로세스가 컬렉션을 삭제·재생성(--full)한 뒤에도 최신 컬렉션을 가리키도록 다시 연다."""
    self._store = self._open()
```
```python
# retriever_service.py — reload() 첫 줄
def reload(self) -> int:
    self._store.reopen()
    chunks = self._store.get_all()
    ...
```
Task 7 인터페이스에 `reopen() -> None` 추가(공개 메서드 1개). 증분 `upsert`만 있었던 경우에도 무해(같은 컬렉션을 다시 연다).

### A-3. `reload()` 중 빈 인덱스 창 제거 (nit #3 → A-1 적용으로 should-fix)

**발견** `[검증]`(코드 읽기): `reload()`가 `self._bm25 = {}`(`:50`) 후 재구성(`:56`)하는 사이에 `search()`가 오면 `bm25 is None` → `[]` → 200+NOT_FOUND. 현재는 `async def` 루프 블로킹 덕에 닫혀 있지만 A-1로 스레드풀에 올리면 실제로 열린다.

**변경** — `retriever_service.py` `reload()`: 로컬 dict에 구성한 뒤 마지막에 한 번 대입.
```python
def reload(self) -> int:
    self._store.reopen()
    chunks = self._store.get_all()
    groups: dict[str, list[Document]] = {SOURCE_ALL: chunks}
    for chunk in chunks:
        groups.setdefault(chunk.metadata.get("source", ""), []).append(chunk)
    # 검색 요청과 동시에 실행될 수 있으므로 완성된 인덱스를 한 번에 교체한다
    new_index = {source: BM25Retriever.from_documents(docs, preprocess_func=tokenize, k=self._bm25_k)
                 for source, docs in groups.items() if docs}
    self._bm25 = new_index
    self.chunk_count = len(chunks)
    logger.info(...)  # 기존 문구 유지
    return self.chunk_count
```
`chunk_count`도 인덱스 교체 뒤에 갱신한다(순서 일관).

### A-4. `watchfiles` 로거 억제 (nit #7, Task 11 비차단 2)

`global_logger.py` 억제 튜플 `("httpx", "httpcore", "urllib3", "chromadb")`에 `"watchfiles"` 추가. `reload=True`에서 리로더 프로세스의 DEBUG가 `app.log`에 쌓이는 것을 막는다.

### 조치 A 완료 기준
- 전체 `pytest --active-profile=local` green(기존 267 + Validator 추가분)
- `[검증]`할 것(Validator): 1.5초 걸리는 모델로 `/v1/ask` 진행 중 `/check`가 **즉시**(≤0.3초) 응답; `reopen()` 후 두 번째 클라이언트의 `reset()`+`upsert` → 서버 측 `reload()` 예외 없이 새 청크 수 반영; `reload()` 도중 `search()`가 `[]`를 내지 않음(스레드 경합 테스트 또는 코드 검토로 "단일 대입" 확인); `watchfiles` 로거 레벨 WARNING
- 계획서 테스트(Task 9 7개·Task 10 6개·Task 11 8개) 미변경

## 조치 B (Validator)

1. `test/test_ask_controller.py` 전역 상태 복원(nit #5): `client` fixture와 `_swap_model` 등이 `ask_controller.context`를 직접 대입하는 부분을 `monkeypatch.setattr(ask_controller, "context", …)`로 바꿔 자동 복원. 250행 `ask_controller.context = None`(monkeypatch undo에 덮여 무효) 삭제.
2. 누락 테스트 3개(nit #6): (a) `search()` 단계에서 `ConnectionError`/`ResponseError` → `/v1/ask` 503, 스트림 `event: error`; (b) 토큰 일부 방출 후 `astream` 예외 → 마지막 프레임 `error`; (c) builtin `ConnectionError`를 내는 모델 → 503(실제 `ollama` 클라이언트가 감싸는 타입).
3. 조치 A 완료 기준 검증. A-1은 인프로세스 ASGI(`httpx.ASGITransport`)로 동시 요청 타이밍 측정, A-2는 tmp 컬렉션에 클라이언트 2개, A-3은 코드 검토 + 가능하면 스레드 경합 테스트.
4. 전체 green·소켓 차단 포함.

## 사용자 결정 목록 추가

- `requirements.in` 직접 명시 권고 **3건째**: `ollama`(`llm_factory.py:5` 직접 import, 현재 `# via langchain-ollama` 전이 의존성). 기존 2건: `langchain-text-splitters`, `langchain-classic`.

## Task 12·13 인계

- Task 12 명세에 추가: 계획서 HTML JS가 `!res.ok`일 때 `detail`을 문자열로 가정하는데 **422의 `detail`은 배열** → `"[object Object]"` 표시. `Array.isArray(detail) ? detail.map(d => d.msg).join(", ") : detail`로 처리(리드가 명세 반영).
- Task 13 평가 후 판단(info #8): `EnsembleRetriever`에 `id_key` 미지정 → RRF가 `page_content` 기준으로 합산·중복 제거해 **본문이 동일한 서로 다른 청크**(예: 두 서비스의 `GET /check`)가 하나로 합쳐짐. `id_key="chunk_id"`로 청크 단위 RRF 가능. eval Q3은 `expected_doc_ids`에 둘을 모두 넣어 hit 판정에는 영향 없음.

## 변경하지 않는 항목 (기록)

| # | 항목 | 심각도 | 판단 |
|---|---|---|---|
| 1 | `get_context()`의 요청 시점 `init_context()` 경로 — lifespan 실패 시 uvicorn이 종료하므로 운영에서 도달하지 않음 | info | 그대로 |
| 2 | `EnsembleRetriever` 매 요청 생성 비용 | info | pydantic 객체 1개, 임베딩 HTTP 대비 무시 가능 |
| 3 | `tokenize`가 문장부호 `.`를 토큰으로 남김, 한글 2-gram이 문서 길이를 부풀려 `source=all`에서 openapi 청크가 상대적으로 유리할 가능성 `[추측]`, `{service_key}` 중괄호 토큰과 bare 질의 불일치, 한자·이모지 무시 | info | Task 13 실데이터 평가 결과로 판단. 지금 조정하면 근거 없는 튠 |
| 4 | 503 detail에 예외 메시지 노출 | info | Ollama 자체 메시지만, URL 미포함, 127.0.0.1 PoC |
| 5 | `response.content`/`piece.content` list 가능성 | `[미확인]` | 통합 테스트 재실행 시 타입 확인(Task 10 기록) |
| 6 | `test_retriever_service.py`의 private 속성 단언 | info | 명세 매핑 검증 목적. 유지 |

## 진행 기록

- 2026-09-21 리드: 리뷰 결과 수신, should-fix 2건·연동 nit 1건·`watchfiles` → 조치 A(Builder), 테스트 복원·누락 3개·검증 → 조치 B(Validator). 사용자 결정 3건째(`ollama`) 추가. Task 12 명세에 422 detail 처리 반영.
- 2026-09-21 Builder 조치 A 완료: 5파일 diff 명세 블록과 동일. 267 passed. `[검증]` 다른 repo 인스턴스의 `reset()`+`upsert` 후 서버 `reload()` 예외 없이 새 청크 반영, `new_index` 단일 대입, `watchfiles` WARNING. 동시 요청 타이밍은 Validator 담당. Task 7 명세 인터페이스에 `reopen()` 반영(리드).
- 2026-09-21 리드: Validator에게 조치 B 실행·조치 A 검증 지시.
- 2026-09-21 Validator 조치 B 완료: fixture monkeypatch 전환(계획서 테스트 본문 미변경, fixture 1줄만), 수동 복원 줄 삭제, 테스트 +5(search 실패 → 503 2케이스·스트림 `error`, 부분 토큰 후 `error`, builtin `ConnectionError`). 조치 A 검증 전부 PASS — **A-1 `/check` 0.002초**(1.5초 `/v1/ask` 진행 중), A-2 두 클라이언트 reset 후 reload 정상, **A-3 스레드 경합 실측 reload 15회 중 빈 결과 0회**, A-4 5개 로거 WARNING. **전체 272 passed**(소켓 차단 포함). 결함 없음.
- 2026-09-21 리드: **리뷰 3 종결.** Task 9·10·11 "리뷰 3 통과 — 커밋 대기"(모델 조건 항목 유지). Task 12 지시.

## Validator 비차단 의견에 대한 리드 판단

1. 스레드풀 기본 40으로 동시 요청 제한 — PoC 단일 사용자, LLM이 병목. 변경 없음.
2. `astream`은 비동기 이터레이터라 루프 비블로킹 — 검색만 `to_thread`로 옮긴 조치 적절. 확인.
3. `[미확인]` `reopen()`이 매 `reload()`마다 Chroma 클라이언트를 다시 여는 비용 — 실데이터(수천 청크)에서 `/v1/reload` 지연 측정을 **모델 설치 후 재실행 항목 ④**로 추가. 문제가 되면 `reopen()`을 `NotFoundError` 발생 시에만 호출하는 방식으로 조정.

## 종결 상태 (재개 시 기준선)

- 전체 272 passed / 4 deselected (소켓 차단 포함)
- 미커밋: Task 9~11 산출물 + 리뷰 3 변경분(`ask_controller.py`, `rag_service.py`, `vector_store_repository.py`, `retriever_service.py`, `global_logger.py`, `test_ask_controller.py`) + `docs/plans/` 갱신분
- 모델 설치 후 Validator 재실행 항목(순서): ① Task 7 임베딩 통합 2건 → ② Task 8 실데이터 인제스트·재실행 변경 0·httpx 노이즈 부재 → ③ Task 9 실데이터 sanity → ④ `/v1/reload` 지연 측정(`bge-m3`까지). ⑤ Task 10 LLM 통합 → ⑥ Task 11 full 경로 실기동(`qwen3:14b`까지)
