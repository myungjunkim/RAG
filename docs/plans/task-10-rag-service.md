# Task 10: RAG 답변 생성 서비스 (프롬프트·인용·스트리밍)

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 10
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 7 (`llm_factory.create_chat_model`), Task 9 (`RetrieverService.search`)
- 상태: **신규 구현 — Builder 진행 중** (Task 9 Validator 검증과 병행, 2026-09-21 지시)

## 목표

검색된 청크를 번호 붙인 컨텍스트로 조립해 로컬 LLM(`qwen3:14b`)에 넘기고, `[n]` 인용이 포함된 답변과 근거 목록(`sources`)을 돌려준다. 검색 결과가 없으면 LLM을 호출하지 않고 고정 문구를 반환한다. 동기(`ask`)와 SSE용 비동기 스트리밍(`ask_stream`) 두 경로를 제공한다.

## 설계

### 컴포넌트

`src/service/rag_service.py` 단일 모듈. 외부 의존: `langchain_core.messages.{SystemMessage, HumanMessage}`, `langchain_core.documents.Document`. 내부 의존: `llm_factory`(팩토리 단일화 — `ChatOllama` 직접 import 금지). `Profile` 직접 참조 없음(`from_profile`은 `llm_factory`에 위임).

### 데이터 흐름

```
ask(question, source="all", top_k=None)
  └─ chunks = retriever.search(question, source, top_k)
  └─ 비어 있으면 → {"answer": NOT_FOUND_ANSWER, "sources": []}   (LLM 미호출)
  └─ context, sources = build_context(chunks)
  └─ model.invoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(_USER_TEMPLATE.format(context, question))])
  └─ {"answer": response.content, "sources": sources}

ask_stream(...)  (async)
  └─ 결과 없음 → token(NOT_FOUND_ANSWER) → sources([]) → done
  └─ 있음 → model.astream(...) 조각마다 token(piece.content, 빈 조각 제외) → sources(list) → done("")
```

### 컨텍스트·인용 규칙 (`build_context`)

| 항목 | 규칙 |
|---|---|
| 컨텍스트 블록 | `"[{i}] {title} | {url}\n{page_content}"`를 빈 줄 2개로 결합. i는 1부터 |
| `sources[i-1]` | `{"index": i, "title", "url", "source", "snippet"}` — 모두 `metadata.get(..., "")` |
| snippet | `_strip_prefix(page_content).strip()[:200]`. `_strip_prefix`는 첫 줄이 `[`로 시작하고 `]`로 끝나면(Task 6 confluence 접두어) 그 줄을 제거. openapi 헤더(`## GET …`)는 유지 |
| 프롬프트 | `SYSTEM_PROMPT`(규칙 5개: 문서 근거만·`[n]` 인용·없으면 고정 문구·API 질의는 메서드/경로/필수 필드 명시·한국어 간결) + `_USER_TEMPLATE`(컨텍스트 → `---` → 질문). 문구는 계획서 Step 3 그대로 |

### 인터페이스 (Produces)

```python
NOT_FOUND_ANSWER = "관련 내용을 문서에서 찾지 못했습니다."
SYSTEM_PROMPT: str
def build_context(chunks: list[Document]) -> tuple[str, list[dict]]

class RagService:
    def __init__(self, retriever, chat_model)
    @classmethod
    def from_profile(cls, retriever) -> "RagService"          # chat_model = llm_factory.create_chat_model()
    def ask(self, question: str, source: str = "all", top_k: int | None = None) -> dict
    async def ask_stream(self, question, source="all", top_k=None) -> AsyncIterator[dict]
        # {"event": "token", "data": str}* → {"event": "sources", "data": list[dict]} → {"event": "done", "data": ""}
```

`retriever`는 `.search(query, source, top_k) -> list[Document]` 덕타이핑(테스트는 StubRetriever). `chat_model`은 `.invoke(messages)`·`.astream(messages)` 덕타이핑(테스트는 `FakeListChatModel`).

### 리드 결정 1: LLM 통합 테스트 범위

| 구분 | 테스트 | 조건 | 기본 실행 |
|---|---|---|---|
| 단위 | 계획서 6개(`FakeListChatModel`, `StubRetriever`, `ExplodingModel`) | 없음 | 포함 |
| 통합 | `@pytest.mark.integration` 1개: `RagService.from_profile(StubRetriever([청크 1개])).ask("토큰은 어디에 넣나?")` → `answer`가 비어 있지 않고 `<think>`를 포함하지 않으며(`reasoning=False` 검증) `sources` 1건 | **`qwen3:14b` 설치** + Ollama 기동 | 제외 |

`[미확인]` `qwen3:14b`(약 9GB) 설치 여부 — Task 7 시점 미설치. 미설치면 Task 7과 같이 "환경 미비로 미실행"으로 기록하고 조건부 판정. 실데이터 컬렉션 대상 end-to-end 질의는 Task 13 평가에서.

### 알려진 동작

`[검증]`(계획서 테스트 설계) `FakeListChatModel.astream`은 응답을 문자 단위 조각으로 흘린다 — 테스트는 `"".join(token)`으로 비교. 실제 `ChatOllama.astream`은 토큰 단위. 빈 `content` 조각(스트림 종료 메타 등)은 `if piece.content`로 걸러 SSE에 빈 이벤트가 나가지 않게 한다.

### 기각한 대안

- 멀티턴 대화 이력: 스펙에서 단일 질의로 확정(PoC). 이력 관리·요약은 범위 밖.
- 인용 번호를 LLM 출력에서 파싱해 `sources`를 필터링: 모델이 인용을 빠뜨리면 근거가 사라짐. 검색된 청크 전체를 `sources`로 돌려주고 UI가 번호 매핑.
- LangChain LCEL 체인(`prompt | model | parser`): 메시지 2개 조립에 추상화 계층이 불필요(§4). 직접 `invoke`/`astream`.
- 답변 후처리(`<think>` 제거): `ChatOllama(reasoning=False)`가 원천에서 끄므로 불필요. 통합 테스트로 확인.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 10 Step 3 코드는 참조 구현.

1. `test/test_rag_service.py` 작성 — 계획서 Step 1 그대로(6개, `@pytest.mark.asyncio` 2개 포함). 변경 금지.
2. `pytest --active-profile=local test/test_rag_service.py -v` → `ModuleNotFoundError` 확인.
3. `src/service/rag_service.py` 작성 — 계획서 Step 3 참조. `SYSTEM_PROMPT`·`_USER_TEMPLATE` 문구는 그대로.
4. 같은 명령 → 6 PASSED. `pytest-asyncio`가 `asyncio_default_fixture_loop_scope = function`(pytest.ini)로 동작하는지 확인.
5. 리드 결정 1의 통합 테스트 1개를 같은 파일에 `@pytest.mark.integration`으로 작성(실행은 Validator).
6. 전체 `pytest --active-profile=local -v` → 회귀 없음, integration deselected.
7. 완료 보고: 실행 명령·결과, 생성 파일, 참조 구현과 다른 점.

**하지 않을 것:** 커밋, `ChatOllama` 직접 import, 실제 LLM 호출을 기본 테스트에 포함, 프롬프트 문구 변경.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 6개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_rag_service.py -v` |
| 회귀 없음 | 전체 green, integration deselected, 소켓 차단 상태 통과 |
| 결과 없음 경로 | `ask`·`ask_stream` 모두 LLM 미호출(계획서 `ExplodingModel`) + `astream`도 폭발하는 모델로 stream 경로 확인 |
| `_strip_prefix` 경계 | 첫 줄 `[…]` 제거 / `[`만 있고 `]` 없음 → 유지 / 본문이 한 줄뿐(개행 없음)이고 `[…]` → 유지(sep 없음) / openapi 헤더 유지 |
| snippet | 200자 절단, 접두어 제거 후 `strip` |
| sources 키·타입 | 5개 키 고정, metadata 누락 시 `""` |
| context 형식 | `[n] title | url` 헤더 + 본문, 블록 사이 빈 줄 |
| ask_stream 이벤트 순서 | token* → sources → done, 빈 content 조각 미방출(빈 문자열 조각을 내는 가짜 모델) |
| 팩토리 단일화 | `grep -rn "ChatOllama\|OllamaEmbeddings" src/` → `llm_factory.py`만 |
| 통합(조건부) | `qwen3:14b` 설치 시 `-m integration` 실행: answer 비어 있지 않음, `<think>` 없음, 응답 시간 기록 |
| 구현이 명세와 일치 | 인터페이스·규칙 표 대조 |

## 완료 기준

- [x] `test/test_rag_service.py` 6 PASSED (Validator 추가 후 18 passed / 1 deselected)
- [x] 전체 green (248 passed / 4 deselected), integration deselected, 소켓 차단 상태 통과
- [x] 결과 없음 시 LLM 미호출(동기 `ExplodingModel` + 스트림 `ExplodingStreamModel`)
- [x] `ask_stream` 이벤트 순서·빈 조각 미방출 (`["답","","변",""]` → token 2개)
- [x] `src/`에서 `ChatOllama` 참조는 `llm_factory.py`만
- [x] 통합 테스트 — `qwen3:14b` 설치 후 1 passed(3.3초): answer `str`, `<think>` 부재, 인용 `[1]`. **조건 해제 (2026-09-21, review-04 2단계)**
- [x] 구현이 이 문서의 인터페이스와 일치 (계획서 Step 3과 IDENTICAL, 프롬프트 무변경)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. `response.content`가 리스트형일 가능성 `[미확인]` — `reasoning=False`·텍스트 응답에서는 문자열. 통합 테스트 재실행 시 타입 확인 항목으로 추가(`isinstance(answer, str)`).
2. `ask_stream` 예외 시 `done` 없이 종료 — 설계 의도. Task 11이 제너레이터를 감싸 `event: error`를 방출하고 스트림을 닫는다(Task 11 명세 데이터 흐름·기각 대안 참조). Task 11 검증 항목 "스트림 오류 → `error` 이벤트"가 이를 고정한다.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드 관련 완료 기준 전부 통과, 설계 문서와 구현 일치. LLM 통합 1건은 `qwen3:14b` 설치 후 재실행.
→ **리뷰 3 통과 (2026-09-21) — 커밋 대기.** 리뷰 3 A-1로 `ask_stream`의 `search`가 `asyncio.to_thread` 경유(계획서 대비 차이).

커밋 대상(사용자 수행): `src/service/rag_service.py`, `test/test_rag_service.py`.

## 범위 제외

- 멀티턴, 대화 이력
- 인용 번호 파싱·검증
- 프롬프트 튜닝(Task 13 평가 후)
- HTTP 엔드포인트·SSE 인코딩 → Task 11
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(리뷰 2 진행 중). Task 9 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 리드: Task 9 Builder 완료·리드 대조 후 Validator 검증과 병행해 Builder 지시. Task 9에서 `search` 인터페이스 변경이 나오면 중단 후 재지시.
- 2026-09-21 Validator(Task 9 검증 중 확인): `search` 계약 변경 없음 → Task 10 병행 지장 없음.
- 2026-09-21 Builder 완료: RED → 6 passed(pytest-asyncio 1.4.0, loop scope function) → 통합 1개 작성(deselected) → 전체 236 passed / 4 deselected. 프롬프트 문구 무변경, 팩토리 단일화 유지. 참조 구현과 다른 점 없음.
- 2026-09-21 Validator 회차 1: 코드 완료 기준 전부 PASS, 248 passed(소켓 차단 포함). 테스트 +12. LLM 통합 환경 미비. `RagService` 인터페이스 영향 결함 없음. **검증 하네스 정정**: 소켓 차단 플러그인이 asyncio self-pipe(`socketpair`, AF_UNIX)까지 막아 비동기 테스트 6건 error → "AF_INET/AF_INET6 연결 시도만 차단"으로 수정 후 248 passed. 제품 결함 아님, 이전 티켓 결과 유효(당시 비동기 테스트 없음).
- 2026-09-21 리드: 조건부 READY FOR REVIEW. 구현 대조 일치(`[검증]`). Validator에게 검증 지시. **Task 11 병행 지시** — `RagService` 인터페이스가 계획서 검증 코드와 동일, 파일 겹침 없음(Task 11은 `llm_factory.py`에 `LLM_ERRORS` 추가만).
