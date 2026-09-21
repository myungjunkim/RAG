# Task 11: FastAPI 서버 (DTO, 컨트롤러, main.py)

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 11
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 7 (`VectorStoreRepository`, `llm_factory`), Task 9 (`RetrieverService`), Task 10 (`RagService`)
- 상태: **신규 구현 — Builder 진행 중** (Task 10 Validator 검증과 병행, 2026-09-21 지시)

## 목표

`POST /v1/ask`(동기), `POST /v1/ask/stream`(SSE), `POST /v1/reload`(BM25 인덱스 재구성), `GET /check`(헬스체크)와 정적 UI(`/`)를 제공하는 FastAPI 앱. 기동 시 Chroma에서 청크를 읽어 검색 인덱스를 만들고, Ollama 장애를 503/504로 구분해 돌려준다.

## 설계

### 컴포넌트

| 파일 | 책임 |
|---|---|
| `src/dto/ask_dto.py` | `AskRequest`, `SourceRef`, `AskResponse`, `ReloadResponse`, `HealthResponse` (pydantic) |
| `src/controller/ask_controller.py` | 라우터, `RagContext` 모듈 전역, `init_context()/get_context()`, LLM 오류 → HTTP 상태 변환, SSE 인코딩 |
| `main.py` | `FastAPI(lifespan=...)`, 정적 파일 마운트, `/` → `index.html`, `uvicorn.run` |
| `src/service/llm_factory.py` | **수정(리드 결정 1)** — `LLM_ERRORS` 튜플 추가 |
| `resources/static/index.html` | Task 12에서 교체할 임시 1줄 파일 (`test_root_serves_ui` 통과용) |
| `test/test_ask_controller.py` | `TestClient` 기반 8개(계획서) |

### 데이터 흐름

```
main.py import → Profile 로드 → app 생성 → lifespan 시작 시 context가 None이면 init_context()
init_context(): RetrieverService.from_profile(VectorStoreRepository.from_profile()) → reload() → RagService.from_profile(retriever) → RagContext

POST /v1/ask       → AskRequest 검증(422) → rag_service.ask → AskResponse
                     LLM 오류 → 504(timeout) / 503(그 외 연결·모델 오류)
POST /v1/ask/stream → StreamingResponse(text/event-stream): rag_service.ask_stream 이벤트를 SSE로
                     스트림 중 LLM 오류 → `event: error` 이벤트로 전달(HTTP 상태는 이미 200)
POST /v1/reload    → retriever.reload() → {"chunk_count": n}
GET  /check        → {"status": ok|degraded, "ollama": ping, "chunk_count": n}  (ok = ping True and n > 0)
GET  /             → resources/static/index.html
```

### 인터페이스 (Produces)

```python
# ask_dto
SourceFilter = Literal["all", "confluence", "openapi"]
class AskRequest(BaseModel):  question: str (1~2000자); source: SourceFilter = "all"; top_k: int | None (1~20)
class SourceRef(BaseModel):   index: int; title: str; url: str; source: str; snippet: str
class AskResponse(BaseModel): answer: str; sources: list[SourceRef]
class ReloadResponse(BaseModel): chunk_count: int
class HealthResponse(BaseModel): status: Literal["ok", "degraded"]; ollama: bool; chunk_count: int

# ask_controller
@dataclass class RagContext: retriever; rag_service
context: RagContext | None          # 모듈 전역. 테스트는 여기에 Stub을 주입
def init_context() -> RagContext
def get_context() -> RagContext     # context or init_context()
router: APIRouter                   # POST /{api_root}/ask, /{api_root}/ask/stream, /{api_root}/reload, GET /{health_check_endpoint}

# main
app: FastAPI
```

**SSE 포맷**: `event: <name>\ndata: <JSON>\n\n`. `token`의 data는 JSON 인코딩된 문자열(`"헤더로"`), `sources`는 JSON 배열, `done`은 `""`, `error`는 detail 문자열. 헤더 `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

### 리드 결정 1: LLM 오류 타입을 `llm_factory`에 모은다 (참조 구현과 다름)

**문제** `[검증]`(리뷰 2 관점 4-1): 모델 미설치 시 `ChatOllama`는 `ollama._types.ResponseError`(404, `Exception` 직계)를 낸다. 참조 구현의 컨트롤러는 `(httpx.HTTPError, ConnectionError)`만 잡으므로 이 경우 **500 Internal Server Error**가 된다. 이를 503으로 매핑하려면 `ollama` 예외 타입이 필요한데, Global Constraint상 Ollama 관련 import는 `llm_factory`에만 둔다.

**결정**: `llm_factory`가 예외 튜플을 공개하고 컨트롤러는 그것만 참조한다.
```python
# llm_factory.py 에 추가
import httpx
from ollama import ResponseError as OllamaResponseError   # langchain-ollama 의 의존성. 새 패키지 아님

# LLM/임베딩 호출에서 "Ollama 쪽 문제"로 분류할 예외. 컨트롤러는 이 튜플만 잡는다
LLM_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, ConnectionError, OllamaResponseError)
```
컨트롤러 `_translate_llm_error(e)`: `isinstance(e, httpx.TimeoutException)` → 504 `_LLM_TIMEOUT_DETAIL`; 그 외 → 503 `_OLLAMA_DOWN_DETAIL + f" ({e})"` — 모델 미설치 메시지(`model "qwen3:14b" not found`)가 detail에 포함되어 원인을 구분할 수 있다. `except llm_factory.LLM_ERRORS as e:`로 잡는다. `httpx` import는 컨트롤러에도 남는다(`TimeoutException` 판별용 — Ollama 특화 아님).

`[검증]` `ollama` 패키지는 `langchain-ollama`의 의존성으로 이미 설치됨(Validator가 `ollama._types.ResponseError` 관측). `requirements.in` 변경 없음.

### 리드 결정 2: 기동 시 인덱스 로드 실패 정책

`init_context()`는 lifespan에서 호출되며 `VectorStoreRepository.from_profile()`이 `create_embeddings()`를 호출한다 — 객체 생성만이라 Ollama 미기동이어도 예외 없음. `reload()`는 Chroma만 읽는다. 따라서 **Ollama가 없어도 서버는 뜨고**, `/check`가 `degraded`, `/v1/ask`가 503을 낸다. 이 동작을 유지한다(기각 대안: 기동 시 Ollama ping 실패면 즉시 종료 — 운영자가 Ollama를 나중에 띄우는 시나리오를 막음).

`data/chroma`가 없으면 Chroma가 빈 컬렉션을 새로 만들고 `chunk_count=0` → `degraded`. 예외 없음.

### 리드 결정 3: `reload=True`와 GlobalLogger

`[검증]`(리뷰 2 관점 3-b, uvicorn 0.53.0 인프로세스 재현): uvicorn `LOGGING_CONFIG`는 root를 건드리지 않고 `uvicorn.*`는 `propagate=False` → 앱 로그는 `app.log`에 기록 지속, uvicorn 접근 로그는 콘솔만. `[추측]` `reload=True`(ini `[fastapi] reload=True`)는 부모(리로더)·자식(앱) 두 프로세스가 뜨고 둘 다 `main.py`를 import하므로 `app.log`에 두 프로세스가 append한다 — 줄 섞임 가능, 손상은 아님. **PoC 개발 편의로 유지**하고 Validator가 실제 기동으로 확인·기록한다. 사내 서버 이전 시 `reload=False` 프로파일 사용(범위 밖).

### 기각한 대안

- `@app.on_event("startup")`: FastAPI 0.141에서 deprecated. `lifespan` 사용(계획서 `[검증]`).
- `Depends`로 컨텍스트 주입: 테스트가 모듈 전역 `context`에 Stub을 넣는 방식이 더 단순하고, 엔드포인트 4개에 DI 계층은 과함(§4).
- 스트림 오류를 HTTP 5xx로: 첫 바이트 전송 후에는 상태 코드를 바꿀 수 없다. `event: error`로 전달하고 UI(Task 12)가 표시.
- 컨트롤러에서 `except Exception`으로 전부 503: 코드 버그가 503으로 가려짐. `LLM_ERRORS`로 범위를 한정.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 11 Step 3 코드는 참조 구현. **리드 결정 1은 참조 구현에 없으므로 반드시 반영.**

1. `test/test_ask_controller.py` 작성 — 계획서 Step 1 그대로(8개). 변경 금지.
2. `pytest --active-profile=local test/test_ask_controller.py -v` → `ModuleNotFoundError` 확인.
3. `src/dto/__init__.py`, `src/dto/ask_dto.py`, `src/controller/__init__.py`, `src/controller/ask_controller.py`, `main.py` 작성 — 계획서 Step 3 참조. `resources/static/index.html` 임시 1줄 파일 생성(계획서 문구 그대로).
4. `llm_factory.py`에 `LLM_ERRORS` 추가, 컨트롤러 `except llm_factory.LLM_ERRORS`·`_translate_llm_error` 503 detail에 `({e})` 포함.
5. 같은 명령 → 8 PASSED.
6. `python -c "import main"` → 예외 없음(Profile·정적 디렉터리 확인). **서버 기동은 하지 않음**(Validator 담당).
7. 전체 `pytest --active-profile=local -v` → 회귀 없음.
8. 완료 보고: 실행 명령·결과, 생성·수정 파일, 참조 구현과 다른 점.

**하지 않을 것:** 커밋, `resources/config_local.ini` 변경, `uvicorn.run` 실행, `ollama` import를 컨트롤러에 두기, index.html 본격 구현(Task 12).

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 8개 테스트 통과 | `pytest --active-profile=local test/test_ask_controller.py -v` |
| 회귀 없음 | 전체 green, 소켓 차단 상태 통과(`TestClient`는 인프로세스) |
| 422 검증 | 계획서 + `question` 2001자, `top_k=21`. 알 수 없는 필드는 pydantic 기본대로 **무시되고 200**(리드 판단 1) |
| 오류 매핑 | 계획서 503/504 + **`ollama.ResponseError` 모델을 주입 → 503, detail에 원인 문자열 포함** (리드 결정 1) |
| SSE 포맷 | 계획서 파싱 테스트 + 스트림 중 예외 모델 → `event: error` 이벤트, 이후 스트림 종료. **`RagService.ask_stream`은 예외 시 `done` 없이 끝나므로(Task 10 비차단 2) 컨트롤러의 `error` 이벤트가 클라이언트에 종료를 알리는 유일한 신호** — `astream` 도중 `LLM_ERRORS` 예외를 내는 모델로 마지막 프레임이 `error`인지 확인 |
| `/check` | ping True·chunk>0 → ok; ping False → degraded; chunk 0 → degraded |
| `/v1/reload` | reload 호출 1회, 반환값 반영 |
| Swagger | `GET /docs` 200, `GET /openapi.json`에 4개 경로 존재, `/`는 `include_in_schema=False` |
| 기동 시 context 주입 존중 | 테스트 fixture가 넣은 context를 lifespan이 덮어쓰지 않음(계획서 fixture 동작) |
| **기동 시 `reload()` 호출** (Task 9 비차단 3) | context 미주입 상태로 `TestClient(main.app)` 진입 → `init_context()`가 호출되고 `retriever.chunk_count`가 컬렉션 청크 수와 일치(가짜 임베딩 tmp 컬렉션에 청크 2개 넣고 `VectorStoreRepository.from_profile`·`RagService.from_profile`을 monkeypatch). `reload()` 누락 시 `search()`가 조용히 `[]`를 내는 구조라 반드시 고정 |
| **실기동(조건부: Ollama + 모델 + `data/chroma` 인제스트됨)** | `python main.py --active-profile=local` → `curl /check` ok, `curl -X POST /v1/ask …openapi 질의` → `POST /v1/messages/message` 언급, `/docs` 접속. `app.log`에 앱 로그 기록, 리로더 2프로세스 append 상태 기록(리드 결정 3). 조건 미충족 시 **Ollama 없이 기동** → `/check` degraded, `/v1/ask` 503 확인으로 대체(리드 결정 2) |
| 구현이 명세와 일치 | 인터페이스·SSE 포맷·리드 결정 1~3 대조 |

## 완료 기준

- [x] `test/test_ask_controller.py` 8 PASSED (Validator 추가 후 19 passed)
- [x] 전체 green (267 passed / 4 deselected), 소켓 차단 상태 통과
- [x] 503/504/422 매핑, `ResponseError` → 503 with 원인, 일반 `Exception`은 500 유지
- [x] SSE 이벤트 순서·포맷, 스트림 오류 → `error` 이벤트(마지막 프레임), 헤더 2종
- [x] Ollama 없이도 서버 기동, `/check` degraded. **`/v1/ask`는 컬렉션이 비어 있으면 200 + NOT_FOUND**(`search()`가 `[]` → LLM 미호출), **청크가 있고 LLM 실패 시 503**(단위 테스트로 고정). — 초안의 "`/v1/ask` 503" 문구는 두 동작의 조합을 잘못 적은 것으로 정정(Validator 지적)
- [x] 실기동 확인 (모델 미설치 대체 경로): 기동 성공, `/check` degraded, `/docs` 200, `/` 200, SSE 정상, 종료·포트 해제 확인
- [x] 기동 시 `init_context()` → `reload()` 호출, `chunk_count`가 실제 청크 수와 일치(`test_lifespan_initializes_context_and_calls_reload`)
- [x] `ollama` import는 `llm_factory.py`만
- [x] 구현이 이 문서의 인터페이스와 일치
- [ ] **조건부**: 모델 설치 후 full 경로 실기동(`/check` ok + 실제 질의 응답)

## 리드 결정 3 실측 결과 (Validator, `[추측]` → `[검증]`)

- 리로더(PID 부모)·앱(자식) 두 프로세스가 5010 LISTEN. 두 프로세스가 같은 `app.log`에 append — 자식의 앱 로그 + **부모의 `watchfiles.main` DEBUG 2줄**. 줄 섞임·손상 없음.
- uvicorn 하에서 GlobalLogger 정상 기록(`검색 인덱스 로드: 청크 0개`). uvicorn 접근 로그는 콘솔만. 서드파티 노이즈 0건.

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. **알 수 없는 요청 필드가 무시되고 200** — pydantic 기본. `extra="forbid"`는 클라이언트(Task 12 UI·Swagger 시도)가 필드를 추가로 보낼 때 깨지게 하므로 PoC에서는 관용이 낫다. 변경 없음. 검증 전략의 "알 수 없는 필드 → 422" 문구는 잘못 적은 것 — "무시되고 200"으로 정정.
2. **`watchfiles.main` DEBUG가 `app.log`에 기록** — `reload=True` 개발 모드 한정. 억제 목록(리뷰 2 A-2)에 `watchfiles` 한 단어 추가로 해결 가능. **리뷰 3 조치 후보**로 넘긴다(리뷰 3 조치와 함께 Builder에게 한 번에 지시).
3. lifespan 테스트가 소켓 차단에서 `ping_ollama` 실호출로 실패 → `monkeypatch`로 격리 후 통과. 제품 문제 아님. 기록.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드 관련 완료 기준 전부 통과, 실기동 대체 경로 확인, 설계 문서와 구현 일치. full 경로 실기동은 모델 설치 후.
→ **리뷰 3 통과 (2026-09-21) — 커밋 대기.** 리뷰 3 A-1로 `ask`·`reload`·`health_check`가 `def`(스레드풀)로 변경(계획서 대비 차이). 인터페이스 절의 코드 블록은 시그니처만 다름.

커밋 대상(사용자 수행): `src/dto/`, `src/controller/`, `main.py`, `src/service/llm_factory.py`(수정), `resources/static/index.html`(임시), `test/test_ask_controller.py`.

## 범위 제외

- 인증·CORS·레이트리밋
- 채팅 UI 본격 구현 → Task 12
- 멀티 워커·프로세스 매니저, `reload=False` 운영 프로파일
- 요청 로깅 미들웨어
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 9 진행 중). 리드 결정 1(`LLM_ERRORS`)·2(기동 정책)·3(`reload=True` 로깅) 확정. Task 10 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 리드: Task 9 비차단 3(`reload()` 누락 시 조용히 `[]`) → 검증 항목 추가. Builder 질의(기동 시 `reload()` 포함 여부) → `init_context()`가 호출함, 명세에 이미 반영. Task 10 Builder 완료·리드 대조 후 Validator 검증과 병행해 Builder 지시.
- 2026-09-21 Builder 완료: RED → 8 passed → `import main` 정상 → 전체 256 passed / 4 deselected / 2 warnings(sunset, starlette anyio alias). 리드 결정 1 반영 3곳(`llm_factory.LLM_ERRORS`, 컨트롤러 `except` 2곳, 503 detail `({e})`). `[검증]` `ResponseError(404)` → 503 + 원인 메시지, `ReadTimeout` → 504. `ollama` import는 `llm_factory.py`만. 임시 `index.html` 생성.
- 2026-09-21 리드: 컨트롤러·`llm_factory`·`main.py` 대조 일치(`[검증]`). Validator에게 검증 지시(실기동은 모델 미설치 → 리드 결정 2 대체 경로). Task 12 지시는 **리뷰 3 종결 후**(conventions §2-4).
- 2026-09-21 Validator 회차 1: 코드 완료 기준 전부 PASS, 267 passed(소켓 차단 포함). 테스트 +11. **실기동 수행**(모델 미설치 대체 경로) — 리드 결정 2·3 실측 확인. 완료 기준 문구 오류 지적(`/v1/ask` 503 → 빈 컬렉션은 200+NOT_FOUND). 비차단 3건.
- 2026-09-21 리드: 완료 기준·검증 전략 문구 정정. 조건부 READY FOR REVIEW. 비차단 2(`watchfiles`)는 리뷰 3 조치 후보.
