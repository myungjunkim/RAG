# Task 7: LLM 팩토리와 Chroma 벡터 저장소

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 7
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 1 (`Profile`), Task 6 (청크 `Document`, `chunk_id`)
- 상태: **신규 구현 — Builder 진행 중** (Task 6 READY FOR REVIEW 확인 후 2026-09-21 지시)

## 목표

(1) Ollama LLM·임베딩 객체를 만드는 **유일한 지점** `llm_factory`를 두고, (2) 인제스트와 서빙이 공유하는 Chroma 로컬 저장소 접근을 `VectorStoreRepository`로 감싼다. 단위 테스트는 가짜 임베딩으로 Ollama 없이 통과해야 한다.

## 설계

### 컴포넌트

| 파일 | 책임 |
|---|---|
| `src/service/llm_factory.py` | `ChatOllama`/`OllamaEmbeddings` 생성, `ping_ollama()`. Global Constraint: LLM/임베딩 객체 생성은 이 파일에서만 |
| `src/repository/vector_store_repository.py` | Chroma persist 컬렉션 upsert/delete/get_all/count/reset/as_retriever |
| `test/test_vector_store_repository.py` | 단위 테스트 (`DeterministicFakeEmbedding`, tmp_path persist) |
| `test/test_llm_factory.py` | 단위: 설정값 매핑(객체 속성 확인, 네트워크 없음). 통합(`@pytest.mark.integration`): 실제 Ollama ping·임베딩 1회 |

### 인터페이스 (Produces)

```python
# llm_factory
def create_embeddings() -> OllamaEmbeddings          # model=[ollama].embedding-model, base_url
def create_chat_model() -> ChatOllama                # model, base_url, temperature(float), num_ctx(int),
                                                     # reasoning=False, client_kwargs={"timeout": llm-timeout(float)}
def ping_ollama() -> bool                            # GET {base-url}/api/tags == 200, timeout 3s, 예외 → False

# vector_store_repository
class VectorStoreRepository:
    def __init__(self, persist_dir: str, collection_name: str, embeddings, batch_size: int = 32)
    @classmethod
    def from_profile(cls, embeddings=None) -> "VectorStoreRepository"
        # [chroma] persist-dir, collection; [retrieval] embed-batch-size; embeddings 미지정 시 create_embeddings()
    def upsert(self, chunks: list[Document]) -> None     # id = metadata["chunk_id"], batch_size 단위, None 값 metadata 제거
    def delete(self, chunk_ids: list[str]) -> None       # 빈 목록 무시
    def get_all(self) -> list[Document]                  # documents + metadatas
    def count(self) -> int
    def reset(self) -> None                              # delete_collection 후 재오픈
    def reopen(self) -> None                             # (리뷰 3 A-2 추가) 다른 프로세스가 --full 로 컬렉션을 재생성한 뒤 최신 컬렉션을 가리키도록 다시 연다
    def as_retriever(self, k: int, source: str | None = None)  # source 있으면 filter={"source": source}
```

Chroma 컬렉션 생성 인자: `collection_metadata={"hnsw:space": "cosine"}`, 컬렉션 이름은 3자 이상(Global Constraint — 테스트도 `test_col`).

### 리드 결정 1: Chroma 익명 텔레메트리 비활성화 (참조 구현과 다름)

chromadb는 기본으로 익명 사용 통계를 외부(PostHog)로 전송한다. 사내 문서 내용은 포함되지 않지만, 이 프로젝트의 "외부 전송 금지" 원칙과 맞지 않고, 리뷰 1에서 리뷰어 환경의 chromadb 초기화 hang(`[미확인]` 원인)이 텔레메트리 네트워크 시도일 가능성이 있다. 또한 소켓 차단 검증에서 불필요한 외부 연결 시도를 없앤다.

**결정**: `_open()`에서 `client_settings=chromadb.config.Settings(anonymized_telemetry=False)`를 전달한다.
```python
from chromadb.config import Settings
...
Chroma(
    collection_name=..., embedding_function=..., persist_directory=...,
    collection_metadata={"hnsw:space": "cosine"},
    client_settings=Settings(anonymized_telemetry=False, persist_directory=self._persist_dir, is_persistent=True),
)
```
`[검증]`(리뷰 2, langchain-chroma 1.1.0) `Chroma.__init__`은 `persist_directory` 인자가 있으면 `chromadb.PersistentClient(path=persist_directory, settings=client_settings)`로 생성한다 — **인자가 우선**이고 settings의 `persist_directory`/`is_persistent` 중복 지정은 무해하다. 양쪽에 같은 값을 넣은 현재 구현은 어긋남이 없다. (초안의 "settings가 우선될 수 있음" `[추측]`은 반대로 확인됨 — 결과 영향 없음.) `chromadb`는 이미 `requirements.in`에 있어 새 의존성 아님.

### 리드 결정 2: 통합 테스트 범위

| 구분 | 테스트 | Ollama 필요 | 기본 실행 |
|---|---|---|---|
| 단위 | `test_vector_store_repository.py` 6개(계획서) — `DeterministicFakeEmbedding(size=16)` | 아니오 | 포함 |
| 단위 | `test_llm_factory.py`: `create_embeddings().model == "bge-m3"`, `create_chat_model()`의 `model`/`temperature`/`num_ctx`/`reasoning` 속성이 ini 값과 일치, `ping_ollama()`가 `requests.get`을 monkeypatch한 상태에서 200→True / 예외→False | 아니오 | 포함 |
| 통합 | `test_llm_factory.py` `@pytest.mark.integration`: `ping_ollama() is True`, `create_embeddings().embed_query("테스트")`가 길이 1024 벡터(`bge-m3`), **3000자 텍스트 `embed_query`도 예외 없이 1024차원**(Task 6 openapi 청크 최대 길이 대응) | **예** | 제외(`-m integration`으로만) |

LLM 실호출(`create_chat_model().invoke`) 통합 테스트는 이 티켓에 넣지 않는다 — qwen3:14b 응답 시간이 길고 Task 10에서 스트리밍까지 함께 검증하는 것이 효율적.

### 리드 결정 3: Ollama 모델 미설치 상태의 검증 진행 (2026-09-21)

`[검증]`(Validator) Ollama 0.34.1 기동 중, `ollama list` 빈 목록 — `bge-m3`·`qwen3:14b` 모두 미설치. `ping_ollama()`는 True지만 임베딩 통합 테스트는 실행 불가.

**결정**: Validator 제안 (b) 채택.
- 단위·소켓 차단·텔레메트리·metadata 검증은 예정대로 수행한다.
- 통합 테스트는 작성 상태로 두고 "환경 미비로 미실행"으로 보고서에 기록한다.
- 완료 기준 "통합 테스트 PASS"는 **사용자가 `ollama pull bge-m3`를 수행한 뒤 Validator가 재실행**해 채운다. 그 전까지 이 티켓은 READY FOR REVIEW를 선언하지 않고 **"조건부 — 통합 테스트 보류"** 상태로 둔다(단위 검증이 모두 통과하면 Task 8 착수는 막지 않는다 — Task 8 단위 테스트도 가짜 임베딩만 사용).
- 모델 다운로드(`bge-m3` 약 1.2GB, `qwen3:14b` 약 9GB)는 에이전트가 수행하지 않는다. 사용자 안내 사항.
- (c) 통합 범위 축소는 기각 — 임베딩 차원·3000자 입력 확인은 Task 8 실데이터 인제스트 전에 확인해야 하는 항목이다.

**사전 점검 결과** `[검증]`(Validator): langchain-chroma 1.1.0, chromadb 1.5.9, langchain-ollama 1.1.0. `Chroma.__init__`에 `client_settings` 존재 → 리드 결정 1 적용 가능. `data/` 현재 없음(오염 판정 기준선).

### 알려진 라이브러리 동작

`[검증]`(계획서 기록, langchain-chroma 1.1.0) `_collection.count()`, `get(include=[...])`, `delete(ids=)`, `delete_collection()`, `as_retriever(search_kwargs={"filter": ...})` 동작 확인됨. `count()`가 private `_collection`에 접근하는 것은 langchain-chroma가 공개 count API를 제공하지 않아 수용.

`[미확인]` Chroma metadata에 빈 문자열(`""`) 허용 여부 — OpenAPI schema 문서가 `method=""`를 가진다. Validator가 실제 upsert로 확인(리뷰 1 기록 10번).

### 기각한 대안

- 임베딩·LLM 생성을 각 사용처에서 직접: 사내 서버 이전 시 교체 지점이 분산됨. Global Constraint대로 팩토리 단일화.
- Chroma HTTP 서버 모드: 프로세스 하나 더 운영해야 함. PoC는 persist 디렉터리 공유로 충분(스펙 결정).
- 텔레메트리 기본값 유지: 위 결정 1의 이유로 기각.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 7 Step 3 코드는 참조 구현. 단, **리드 결정 1(`client_settings`)은 참조 구현에 없으므로 반드시 반영**.

0. `python -c "import langchain_chroma, chromadb, langchain_ollama; print(langchain_chroma.__version__, chromadb.__version__)"`로 설치 확인. `langchain_chroma.Chroma.__init__` 시그니처에 `client_settings`가 있는지 확인(`inspect.signature`). 없으면 ESCALATE.
1. `test/test_vector_store_repository.py` 작성 — 계획서 Task 7 Step 1 그대로(6개). 변경 금지.
2. `pytest --active-profile=local test/test_vector_store_repository.py -v` → `ModuleNotFoundError` 확인.
3. `src/service/llm_factory.py`, `src/repository/vector_store_repository.py` 작성 — 계획서 Step 3 참조 + 리드 결정 1.
4. 같은 명령 → 6 PASSED. **테스트 실행이 10초 이상 걸리거나 hang이면 중단하고 ESCALATE**(chromadb 초기화 문제 의심, 버전·에러 출력 첨부).
5. `test/test_llm_factory.py` 단위 테스트 작성 — 리드 결정 2의 "단위" 행. 통합 테스트도 같은 파일에 `@pytest.mark.integration`으로 작성(실행은 Validator).
6. 전체 `pytest --active-profile=local -v` → 회귀 없음. 통합 테스트가 `deselected`로 표시되는지 확인.
7. 완료 보고: 실행 명령·결과, 생성 파일, 참조 구현과 다른 점, 라이브러리 버전.

**하지 않을 것:** 커밋, `requirements*` 변경, Ollama 실호출을 기본 테스트에 포함, `resources/config_local.ini` 변경, `data/` 디렉터리에 실제 컬렉션 생성(테스트는 tmp_path만).

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 단위 테스트 통과 | `pytest --active-profile=local test/test_vector_store_repository.py test/test_llm_factory.py -v` |
| 회귀 없음 | 전체 green, integration은 deselected |
| 네트워크 비의존 | 소켓 차단 상태에서 전체 통과 — **텔레메트리 비활성화가 실제로 외부 연결을 만들지 않는지** 이 실행으로 확인 |
| 통합 테스트 | Ollama 기동 상태에서 `pytest --active-profile=local -m integration test/test_llm_factory.py -v` → ping True, 임베딩 길이 1024. 결과를 보고서에 별도 표기 |
| 빈 문자열 metadata | `method=""`, `path=""`, `tags=""` 청크 upsert → get_all에서 그대로 반환 |
| None 제거 | metadata에 `None` 값 포함 청크 upsert → 예외 없음, 해당 키 제거됨 |
| batch 분할 | `batch_size=2`로 5개 upsert → count 5 (계획서 `_repo` 기본값이 2) |
| 빈 컬렉션 | 새 repo `get_all() == []`, `count() == 0` |
| source 필터 | 계획서 테스트 + `source="confluence"` 필터, 없는 source → `[]` |
| reset 후 persist | reset → 새 인스턴스로 열어도 count 0 |
| `data/` 오염 없음 | 테스트 후 `data/chroma` 미생성(`git status` 또는 `ls data/`) |
| 팩토리 단일화 | `grep -rn "ChatOllama\|OllamaEmbeddings" src/` 결과가 `llm_factory.py`만 |
| 구현이 명세와 일치 | 인터페이스·리드 결정 1·2 대조 |

## 완료 기준

- [x] 단위 테스트 전부 PASS (계획서 6 + llm_factory 단위 5 + Validator 11 = 22)
- [x] 전체 green (165 passed / 3 deselected), 소켓 차단 상태 통과 — 텔레메트리 외부 연결 없음 실증
- [ ] 통합 테스트(Ollama 기동) — **ping PASS / 임베딩 1024차원·3000자 2건 미실행(모델 미설치, 404)**. `ollama pull bge-m3` 후 재실행 필요
- [x] 텔레메트리 비활성화 반영 (런타임 `get_settings()` 확인)
- [x] 빈 문자열 metadata 저장·조회 확인 (리뷰 1 기록 10번 해소)
- [x] `src/`에서 `ChatOllama`/`OllamaEmbeddings` 참조는 `llm_factory.py`만
- [x] `data/` 오염 없음
- [x] 구현이 이 문서의 인터페이스와 일치 (`llm_factory.py` IDENTICAL, `vector_store_repository.py` 차이 7줄 = 리드 결정 1)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. `count()`의 `_collection` private 접근 — 명세에서 수용한 사항. Task 8에서 `count()` 사용처는 `ingest.py` 결과 출력 1곳으로 제한(계획서대로). 변경 없음.
2. Validator 테스트의 private 접근(`_store._client`, `_batch_size`) — 런타임 반영 확인의 유일한 경로. 수용.
3. 소켓 차단 통과는 테스트 경로 한정 증거 — 인정. 설정값 `False` 런타임 확인으로 충분하다고 판단. 변경 없음.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드 관련 완료 기준 전부 통과, 설계 문서와 구현 일치. 통합 임베딩 2건은 사용자가 `bge-m3`를 받은 뒤 Validator 재실행으로 채운다 — 코드 결함이 아니므로 Task 8 진행을 막지 않는다.
→ **리뷰 2 통과 (2026-09-21) — 커밋 대기.** 통합 2건은 모델 설치 후 재실행 조건 유지.

커밋 대상(사용자 수행): `src/service/llm_factory.py`, `src/repository/vector_store_repository.py`, `test/test_vector_store_repository.py`, `test/test_llm_factory.py`.

## 범위 제외

- manifest·증분 인제스트 → Task 8
- BM25·하이브리드 검색 → Task 9
- LLM 실호출 통합 테스트 → Task 10
- Chroma 서버 모드, 컬렉션 다중화
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 6 진행 중). Task 6 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 리드: Task 6 통과 확인. 통합 테스트에 3000자 임베딩 항목 추가(Task 6 비차단 2번). Builder에게 시작 지시.
- 2026-09-21 Validator 사전 검토: Ollama 모델 미설치 발견(`bge-m3`, `qwen3:14b`). 라이브러리 사전 점검 정상.
- 2026-09-21 리드: 리드 결정 3 — (b) 채택. 사용자에게 `ollama pull bge-m3` 안내.
- 2026-09-21 Builder 완료: langchain-chroma 1.1.0 / chromadb 1.5.9 / langchain-ollama 1.1.0. `client_settings` 시그니처 확인. RED → 6 passed(0.54s, hang 없음) → `test_llm_factory.py` 단위 5 + integration 3(미실행) → 전체 154 passed / 3 deselected. `data/` 미생성, 팩토리 단일화 확인. 참조 구현과 다른 점: 리드 결정 1의 `client_settings`만. 런타임 `get_settings()`로 `anonymized_telemetry=False` 확인.
- 2026-09-21 리드: 구현 대조 일치(`[검증]`). Validator에게 (b) 모드 검증 지시. **Task 8을 병행 지시** — Task 7 구현이 계획서 검증 코드와 동일하고 파일이 겹치지 않아 재작업 위험이 낮다고 판단. Task 7에서 인터페이스 변경이 나오면 Task 8 중단 후 재지시.
- 2026-09-21 Validator 회차 1: 코드 완료 기준 전부 PASS, 165 passed(소켓 차단 포함). 통합: ping PASS, 임베딩 2건 모델 미설치로 미실행. 테스트 +11. 인터페이스 영향 결함 없음 → Task 8 병행 지장 없음.
- 2026-09-21 리드: 조건부 READY FOR REVIEW. 통합 2건은 모델 설치 후 재실행.
