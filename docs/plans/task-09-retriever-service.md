# Task 9: 하이브리드 검색 서비스 (BM25 + 벡터, RRF)

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 9
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 7 (`VectorStoreRepository`), Task 8 (실데이터 컬렉션 `data/chroma` — 수동 검증용)
- 상태: **신규 구현 — Builder 진행 중** (리뷰 2 종결 후 2026-09-21 지시)

## 목표

서빙 프로세스가 기동 시 Chroma 전체 청크를 읽어 **소스별 BM25 인메모리 인덱스**를 만들고, 질의 시 BM25와 벡터 검색 결과를 RRF(`EnsembleRetriever`)로 합쳐 `chunk_id` 중복 없는 상위 `top_k` 청크를 반환한다. 경로(`/v1/messages/message`)·식별자(`service_key`) 같은 정확 매칭은 BM25가, 의미 유사는 벡터가 담당한다.

## 설계

### 컴포넌트

`src/service/retriever_service.py` 단일 모듈. 외부 의존: `langchain_classic.retrievers.EnsembleRetriever`, `langchain_community.retrievers.BM25Retriever`(내부적으로 `rank-bm25`). 내부 의존: `Profile`, `GlobalLogger`, `VectorStoreRepository`.

Global Constraint의 import 경로 고정: `EnsembleRetriever` → `langchain_classic.retrievers`, `BM25Retriever` → `langchain_community.retrievers`.

### 의존성 확인 (Builder 작업 0)

`[미확인]` `langchain-classic`이 `requirements.in`에 직접 명시돼 있지 않다(Task 6에서 `langchain-text-splitters`가 `# via langchain-classic`으로 설치된 것은 확인됨 → `langchain-classic` 자체는 설치돼 있음). `rank-bm25`는 `requirements.in`에 있음. Builder는 `importlib.metadata.version("langchain-classic")`과 두 import 경로를 확인하고, `langchain-classic`이 전이 의존성이면 완료 보고에 "requirements.in 명시 필요"를 적는다(Task 6과 동일 처리, 사용자 결정). import 실패 시 ESCALATE.

**사전 점검 결과** `[검증]`(Validator, 2026-09-21): `langchain-classic` 1.0.8 / `langchain-community` 0.4.2 / `rank-bm25` 0.2.2 설치, 두 import 경로 OK → ESCALATE 조건 해당 없음. `langchain-classic`은 `requirements.txt`에 `# via langchain-community`로 **전이 의존성** — 직접 import하므로 `requirements.in` 명시 대상(사용자 결정, Task 6 `langchain-text-splitters`와 동일). import 시 `DeprecationWarning: langchain-community is being sunset` 발생 — PoC 범위에서는 무관하나 **사내 서버 이전·유지보수 시 `BM25Retriever` 대체(독립 패키지 또는 `rank-bm25` 직접 사용) 검토 사항**으로 기록.

### 데이터 흐름

```
reload()
  └─ store.get_all() → chunks (chunk_count 갱신)
  └─ groups = {"all": chunks, "<source>": [...소스별]}
  └─ 각 그룹(비어 있지 않은 것만) → BM25Retriever.from_documents(docs, preprocess_func=tokenize, k=bm25_k)

search(query, source="all", top_k=None)
  └─ k = top_k or self._top_k
  └─ bm25 = self._bm25.get(source) → 없으면 []   (인덱스 비어 있음 또는 미지의 source)
  └─ vector = store.as_retriever(k=vector_k, source=None if "all" else source)
  └─ EnsembleRetriever([bm25, vector], weights=[bm25_weight, vector_weight]).invoke(query)  # RRF
  └─ chunk_id 기준 중복 제거 → 상위 k
```

### 토크나이저 규칙 (`tokenize`)

| 입력 | 처리 |
|---|---|
| 전체 | 소문자화 후 정규식 `[a-z0-9_{}./\-]+ \| [가-힣]+`로 토큰 추출 |
| 경로 토큰(`/` 포함, 예 `/v1/messages/{service_key}`) | 토큰 자체 + `/`로 나눈 조각(`v1`, `messages`, `{service_key}`) 추가 |
| 한글 토큰(3자 이상) | 토큰 자체 + 2-gram(`메시지` → `메시`, `시지`) 추가. 2자 이하는 그대로 |
| 영숫자·식별자(`service_key`, `get`) | 그대로 |

근거: 한국어 형태소 분석기 없이 BM25 재현율을 확보하는 최소 방법. 경로 조각으로 `messages` 단어 질의가 `/v1/messages/...` 청크를 잡고, 2-gram으로 조사 변화(`메시지를`)에 대응.

### 인터페이스 (Produces)

```python
SOURCE_ALL = "all"
def tokenize(text: str) -> list[str]

class RetrieverService:
    def __init__(self, vector_store: VectorStoreRepository, bm25_k: int, vector_k: int,
                 bm25_weight: float, vector_weight: float, top_k: int)
    @classmethod
    def from_profile(cls, vector_store) -> "RetrieverService"   # [retrieval] bm25-k, vector-k, bm25-weight, vector-weight, top-k
    def reload(self) -> int          # 청크 수 반환, 인덱스 전체 재구성(삭제된 청크는 사라짐)
    chunk_count: int
    def search(self, query: str, source: str = "all", top_k: int | None = None) -> list[Document]
```

### 알려진 동작

`[검증]`(계획서 기록) 가짜 임베딩(`DeterministicFakeEmbedding`) 환경에서 RRF 순위는 가중치에 민감(0.5/0.5에서 `o1#0` 1위, 0.4/0.6에서 3위). 따라서 계획서 단위 테스트는 **포함 여부만** 확인한다. 순위 품질은 Task 13 평가(`eval/questions.yaml`)에서 실데이터·실임베딩으로 본다.

### 기각한 대안

- BM25 인덱스를 디스크에 저장: 기동 시 Chroma에서 전체 청크를 읽어 재구성하는 것이 수백~수천 청크 규모에서 1초 내(`[추측]`)이고, 인제스트와 서빙이 Chroma 디렉터리만 공유한다는 스펙 원칙을 지킨다.
- 형태소 분석기(kiwipiepy/konlpy): 새 의존성·모델 다운로드. PoC는 2-gram으로 시작하고 Task 13 평가 결과에 따라 재검토.
- 벡터 검색만: 경로·필드명 정확 질의(`/v1/messages/message`, `affiliated_company_seq`)에서 임베딩이 약함. 스펙에서 하이브리드로 확정.
- 소스별 인덱스 없이 결과 필터링: `source="openapi"` 질의에서 BM25 상위 k가 confluence로 채워지면 필터 후 결과가 비는 문제. 소스별 인덱스 유지.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 9 Step 3 코드는 참조 구현.

0. 의존성·import 경로 확인(위 절). 실패 시 ESCALATE.
1. `test/test_retriever_service.py` 작성 — 계획서 Step 1 그대로(7개). 변경 금지.
2. `pytest --active-profile=local test/test_retriever_service.py -v` → `ModuleNotFoundError` 확인.
3. `src/service/retriever_service.py` 작성 — 계획서 Step 3 참조.
4. 같은 명령 → 7 PASSED.
5. 전체 `pytest --active-profile=local -v` → 회귀 없음.
6. 완료 보고: 실행 명령·결과, 생성 파일, 참조 구현과 다른 점, `langchain-classic` 버전과 requirements.in 명시 필요 여부.

**하지 않을 것:** 커밋, `requirements*` 변경, `data/chroma` 실데이터 컬렉션 접근(Validator 담당), `VectorStoreRepository` 수정.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 7개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_retriever_service.py -v` |
| 회귀 없음 | 전체 green, 소켓 차단 상태 통과 |
| tokenize 경계 | 대문자 → 소문자, 2자 한글(`조회`)은 2-gram 없음, 3자 한글 2-gram 개수 = len-1, 경로 끝 `/` 처리, 빈 문자열 → `[]`, 특수문자만 → `[]`, 영문+한글 혼합(`API키`)이 두 토큰으로 분리 |
| 소스별 인덱스 | 미지의 source(`"foo"`) → `[]`; 한 소스만 있는 컬렉션에서 다른 source 질의 → `[]` |
| reload 재구성 | 청크 삭제 후 reload → chunk_count 감소, 삭제된 chunk_id가 검색에 안 나옴 |
| 중복 제거·k | 결과 chunk_id 유일, `len <= k`, `top_k=None`이면 생성자 top_k |
| from_profile 매핑 | ini 값(bm25-k=10, vector-k=10, 0.4/0.6, top-k=6)이 인스턴스 속성에 반영 |
| import 경로 | `retriever_service.py`의 import가 Global Constraint 경로와 일치 |
| **실데이터 sanity**(조건: Task 8에서 `data/chroma` 생성됨 + `bge-m3` 설치) | `VectorStoreRepository.from_profile()` + `RetrieverService.from_profile().reload()` → chunk_count가 Task 8 인제스트 청크 수와 일치; `search("메시지 등록 API", source="openapi")` 상위 결과에 `POST /v1/messages/message` 청크 포함; `search("/v1/messages/message")` 결과에 동일 청크 포함. 조건 미충족 시 `[미확인]` 기록 |
| 구현이 명세와 일치 | 인터페이스·토크나이저 규칙·데이터 흐름 대조 |

## 완료 기준

- [x] `test/test_retriever_service.py` 7 PASSED (Validator 추가 후 23 passed)
- [x] 전체 green (230 passed / 3 deselected), 소켓 차단 상태 통과
- [x] tokenize 규칙 표대로 동작 (9종 입력 실제 출력 대조)
- [x] 미지의 source·빈 인덱스·reload 전 → `[]`, 결과 중복 없음, `len <= k`
- [x] reload가 삭제된 청크를 반영 (4 → 3)
- [x] import 경로 Global Constraint 준수 (`__module__` 확인)
- [ ] 실데이터 sanity — **`[미확인]`** (`data/chroma` 청크 0, `bge-m3` 미설치). 모델 설치 후 ③ 순서로 재실행
- [x] 구현이 이 문서의 인터페이스와 일치 (계획서 Step 3과 IDENTICAL)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. `langchain-community` sunset 경고 — 이미 "사전 점검 결과"에 유지보수 항목으로 기록. 변경 없음.
2. `langchain-classic` 전이 의존성 — 사용자 결정 목록 2건째. 변경 없음.
3. `reload()` 전 `search()`가 조용히 `[]` — 명세 데이터 흐름대로. **Task 11 검증 항목에 추가**: 기동(lifespan) 후 `init_context()`가 `reload()`를 호출해 `chunk_count`가 컬렉션 청크 수와 일치하는지.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드 관련 완료 기준 전부 통과, 설계 문서와 구현 일치. 실데이터 sanity는 모델 설치 후 재실행.
→ **리뷰 3 통과 (2026-09-21) — 커밋 대기.** 리뷰 3 조치 A-2·A-3으로 `reload()`가 `reopen()` 호출 + 인덱스 단일 대입 구조로 변경(계획서 대비 차이). 상세: `review-03-task9-11.md`

커밋 대상(사용자 수행): `src/service/retriever_service.py`, `test/test_retriever_service.py`.

## 범위 제외

- 재랭킹(cross-encoder), 쿼리 확장
- 형태소 분석
- 검색 품질 수치 평가 → Task 13
- 프롬프트·LLM 호출 → Task 10
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 8 진행 중). 리뷰 2 종결 후 Builder 지시 예정.
- 2026-09-21 리드: 리뷰 2 종결 확인. Builder에게 시작 지시. 실데이터 sanity는 `data/chroma`가 비어 있어(청크 0) 모델 설치·재인제스트 후 가능.
- 2026-09-21 Builder 완료: 의존성 확인(langchain-classic 1.0.8 전이 의존성 → `requirements.in` 명시 권고 2건째). RED → 7 passed → 전체 214 passed / 3 deselected / 1 warning(sunset). `data/chroma` 미접근. 참조 구현과 다른 점 없음.
- 2026-09-21 리드: 구현 대조 일치(`[검증]`). Validator에게 검증 지시. **Task 10 병행 지시** — `search` 인터페이스가 계획서 검증 코드와 동일하고 파일 겹침 없음.
- 2026-09-21 Validator 회차 1: 코드 완료 기준 전부 PASS, 230 passed(소켓 차단 포함). 테스트 +16. 실데이터 sanity `[미확인]`. 인터페이스 영향 결함 없음.
- 2026-09-21 리드: 조건부 READY FOR REVIEW. 비차단 3번 → Task 11 검증 항목.
