# KUDOS RAG 시스템 설계 (PoC)

작성일: 2026-09-17

## 1. 목적

팀 Confluence 스페이스(`KUDOS`)와 팀 FastAPI 서비스의 OpenAPI(Swagger) 스펙을 근거로 질문에 답하는 RAG 시스템의 PoC.
"이 API 어떻게 호출해?", "이 설정값 정의가 어디 있어?" 같은 팀 내부 질문에 근거(출처 링크)와 함께 답한다.

## 2. 확정된 요구사항·제약

| 항목 | 결정 |
|---|---|
| 데이터 정책 | 사내 문서를 외부 LLM/임베딩 API로 전송 금지 → **완전 로컬** (Ollama) |
| 실행 환경 | 1차: 개인 Mac (Apple M5 Pro, 64GB). PoC 후 사내 서버 Docker 이전 |
| Confluence | Atlassian Cloud `https://ihunet.atlassian.net`, 스페이스 `KUDOS` 1개, **페이지 본문만** (첨부파일 제외 — 이후 텍스트류 첨부 확장 예정) |
| OpenAPI | QA 환경 `/openapi.json`. 초기 2개(General Chatbot API, Message Management API), 설정 파일에 URL 추가로 확장 |
| 형태 | FastAPI 서버(`/v1/ask`) + 최소 웹 UI. 인제스트는 별도 CLI |
| 프레임워크 | LangChain 1.x + Chroma + Ollama (팀 기존 프로젝트가 LangChain 사용) |
| 코드 컨벤션 | `ailab_general_chatbot`/`dialog_history_api`와 동일: `main.py`, `--active-profile`, `resources/config_{profile}.ini`, `Profile` 싱글톤, `src/{config,controller,dto,repository,service,library}`, `requirements.in` + pip-compile, pytest `--active-profile=local` |

### 사전 확인된 사실

- Confluence API 접근 정상(읽기 스코프). `KUDOS` 페이지 200개 이상(검색 상한), 활발히 갱신 중.
- OpenAPI 두 스펙 모두 사내망 없이 접근 가능:
  - `https://qa-general-chatbot-api.hunet.ai/openapi.json` — 9 endpoints / 8 schemas
  - `https://message-api.qa.hunet.io/openapi.json` — 143 endpoints / 39 schemas
- 설치된 주요 버전: `langchain 1.4.0`, `langchain-community 0.4.2`, `langchain-classic 1.0.8`, `langchain-ollama 1.1.0`, `langchain-chroma 1.1.0`, `langchain-text-splitters 1.1.2`, `chromadb 1.5.9`, `fastapi 0.141.1`, `markdownify 1.2.3`, `rank-bm25 0.2.2`.
- LangChain 1.x import 경로: `EnsembleRetriever` → `langchain_classic.retrievers`, `BM25Retriever` → `langchain_community.retrievers`, `MarkdownHeaderTextSplitter`/`RecursiveCharacterTextSplitter` → `langchain_text_splitters`, `ChatOllama`/`OllamaEmbeddings` → `langchain_ollama`, `Chroma` → `langchain_chroma`.

### 사용자가 직접 준비할 항목

1. Ollama 설치 및 모델: `brew install ollama`, `ollama pull qwen3:14b`, `ollama pull bge-m3`
2. Atlassian API 토큰 발급(https://id.atlassian.com/manage-profile/security/api-tokens) → 환경변수 `CONFLUENCE_API_TOKEN`

## 3. 전체 아키텍처

```
[인제스트 (CLI: ingest.py)]                       [서빙 (FastAPI: main.py)]

Confluence REST API v2 ─┐                          브라우저 UI (static/index.html)
  KUDOS 페이지(storage HTML)│                              │ POST /v1/ask, /v1/ask/stream
                          ▼                                ▼
OpenAPI JSON(QA URL들) ─► Loader ─► Chunker ─► Indexer ─► Chroma(로컬 persist)
                                                   │            ▲
                                             manifest.json      │ 기동 시 전체 청크 로드
                                            (증분 갱신용)       ▼
                                                        Hybrid Retriever
                                                        (BM25 + 벡터, RRF)
                                                               │ top-k 청크
                                                               ▼
                                                     RagService ─► Ollama(qwen3:14b)
                                                     프롬프트 조립     bge-m3 임베딩
                                                               │
                                                               ▼
                                                     {answer, sources[]}
```

- 인제스트와 서빙은 별도 프로세스이며 **Chroma persist 디렉터리**만 공유한다. 재인제스트 후 서버는 `/v1/reload`로 인덱스를 재로드한다.
- 외부 네트워크 호출은 인제스트 시점(Confluence, OpenAPI 다운로드)에만 발생한다. 질의 시점에는 로컬 Ollama만 호출한다.

## 4. 프로젝트 구조

```
RAG/
├── main.py                        # FastAPI 진입점 (--active-profile)
├── ingest.py                      # 인제스트 CLI (--active-profile, --source confluence|openapi|all, --full)
├── global_variable.py             # PROJECT_ROOT_DIR, PROJECT_RESOURCE_DIR
├── requirements.in / requirements.txt
├── resources/
│   ├── config_local.ini
│   ├── openapi_sources.yaml       # 수집할 OpenAPI 목록 (name, spec_url, docs_url)
│   └── static/index.html          # 최소 채팅 UI (단일 HTML+JS, SSE 수신)
├── src/
│   ├── config/{profile.py, argument.py}
│   ├── controller/ask_controller.py
│   ├── dto/ask_dto.py
│   ├── repository/
│   │   ├── confluence_repository.py
│   │   ├── openapi_repository.py
│   │   └── vector_store_repository.py
│   ├── service/
│   │   ├── confluence_document_service.py
│   │   ├── openapi_document_service.py
│   │   ├── chunk_service.py
│   │   ├── ingest_service.py
│   │   ├── retriever_service.py
│   │   ├── llm_factory.py         # LLM/임베딩 객체 생성 단일 지점
│   │   └── rag_service.py
│   └── library/global_logger.py
├── test/                          # pytest --active-profile=local, fixtures/
├── eval/questions.yaml, eval/run_eval.py
├── data/                          # (gitignore) chroma/, manifest.json
└── docs/superpowers/{specs,plans}/
```

## 5. 컴포넌트 상세

### 5-1. Confluence 수집 — `confluence_repository`, `confluence_document_service`

- 인증: Basic Auth(이메일 + API 토큰). 토큰은 환경변수 `CONFLUENCE_API_TOKEN` 우선, 없으면 ini `[confluence] api-token`.
- 조회 순서:
  1. `GET /wiki/api/v2/spaces?keys=KUDOS` → space id
  2. `GET /wiki/api/v2/spaces/{id}/pages?status=current&body-format=storage&limit=250` — `_links.next` 커서 페이지네이션
- 페이지 응답의 `parentId`로 로컬에서 트리를 만들어 breadcrumb(`상위 > 중위 > 페이지`) 생성. 추가 API 호출 없음.
- storage HTML → Markdown:
  - `markdownify` 적용 전 Confluence 매크로 전처리: `ac:structured-macro[ac:name=code]` → fenced code block(언어 파라미터 유지), `ac:link`/`ri:page` → 링크 텍스트, 그 외 매크로(toc, status, info/note/warning, expand 등)는 내부 본문 텍스트만 남기고 태그 제거.
  - 표는 Markdown 표로 유지.
- Document 메타데이터: `source="confluence"`, `doc_id=page_id`, `title`, `url`(base + `_links.webui`), `breadcrumb`, `version`, `last_modified`.

### 5-2. OpenAPI 수집 — `openapi_repository`, `openapi_document_service`

- `resources/openapi_sources.yaml`:
  ```yaml
  sources:
    - name: general-chatbot-api
      spec_url: https://qa-general-chatbot-api.hunet.ai/openapi.json
      docs_url: https://qa-general-chatbot-api.hunet.ai/docs
    - name: message-api
      spec_url: https://message-api.qa.hunet.io/openapi.json
      docs_url: https://message-api.qa.hunet.io/docs
  ```
- 각 소스를 다운로드(JSON 또는 YAML). 한 소스가 실패하면 로그 후 나머지 계속.
- **endpoint 단위 Document** (Markdown 렌더링):
  - `## {METHOD} {path} — {summary}`
  - 서비스명, 태그, description
  - Parameters 표(name / in / type / required / description)
  - Request Body: 스키마 `$ref` 인라인 해석, 중첩 깊이 3 제한, 순환 참조는 스키마 이름만 표기
  - Responses: 상태코드별 스키마 요약
- **schema 단위 Document**: `components.schemas` 각각 → `## Schema {name}` + 필드명/타입/필수/설명 표.
- 메타데이터: `source="openapi"`, `doc_id="{service}:{METHOD}:{path}"` 또는 `"{service}:schema:{name}"`, `service`, `method`, `path`, `tags`(쉼표 결합 문자열), `url`(docs_url), `title`(`{METHOD} {path}` 또는 `Schema {name}`).

### 5-3. 청킹 — `chunk_service`

- Confluence: `MarkdownHeaderTextSplitter`(h1~h3) → 섹션이 `chunk-size`(기본 1000자) 초과 시 `RecursiveCharacterTextSplitter`(overlap 150). 각 청크 본문 앞에 `[{breadcrumb} > {섹션 헤딩 경로}]` 한 줄 접두어.
- OpenAPI: 1 Document = 1 청크가 원칙. `chunk-size`의 3배(3000자) 초과 시에만 분할하며, 분할된 각 청크에 `## {METHOD} {path}` 헤더를 반복.
- 청크 id: `{doc_id}#{n}` (n은 0부터). 청크 메타데이터는 Document 메타데이터 + `chunk_index`.

### 5-4. 인덱싱·증분 갱신 — `ingest_service`, `vector_store_repository`

- Chroma `PersistentClient(path=data/chroma)`, 컬렉션 1개(`kudos_rag`), 임베딩 `OllamaEmbeddings(model=bge-m3)`.
- `data/manifest.json`: `{ doc_id: { "fingerprint": str, "chunk_ids": [..], "source": str } }`
  - Confluence fingerprint = `version` 번호, OpenAPI fingerprint = 렌더링 텍스트 SHA-256.
- 증분 규칙:
  - fingerprint 동일 → 스킵
  - 변경 → 기존 `chunk_ids` 삭제 후 새 청크 삽입
  - 원본에 없는 doc_id(해당 `--source` 범위 내) → 청크 삭제, manifest에서 제거
  - `--full` → 컬렉션 삭제 후 전체 재구축
- 임베딩은 `embed-batch-size`(기본 32) 단위로 배치 호출.
- 종료 시 요약 출력: 추가/갱신/삭제 doc 수, 청크 수, 실패한 소스 목록. 실패 소스가 있으면 종료코드 1.

### 5-5. 검색 — `retriever_service`

- 서버 기동 시(및 `/v1/reload` 시) Chroma에서 전체 청크(문서 + 메타)를 로드하여 `BM25Retriever`를 인메모리로 구성.
- BM25 토크나이저(`preprocess_func`): 소문자화 → 정규식 토큰화(`\w+` 단어와 `/v1/messages/{id}` 같은 경로 조각 보존) → 한글이 포함된 토큰에는 글자 2-gram을 추가.
- `EnsembleRetriever(retrievers=[bm25(k=bm25-k), chroma(k=vector-k)], weights=[bm25-weight, vector-weight])` → RRF 결합 → 상위 `top-k`(기본 6).
- 요청 파라미터 `source`(`all|confluence|openapi`)로 필터: Chroma는 `where={"source": ...}`, BM25는 소스별로 미리 나눈 인덱스를 선택.

### 5-6. 생성 — `llm_factory`, `rag_service`

- `llm_factory`: `ChatOllama(model, base_url, temperature=0, num_ctx=16384, reasoning=False)`와 `OllamaEmbeddings(model, base_url)` 생성을 이곳에서만 수행(서버 이전 시 vLLM 교체 지점).
- 시스템 프롬프트(한국어):
  - 제공된 문서만 근거로 답한다.
  - 근거 문서는 `[1]`, `[2]` 형식으로 인용한다.
  - 문서에 없으면 "관련 내용을 문서에서 찾지 못했습니다"라고 답한다.
  - API 질문은 메서드·경로·필수 파라미터를 명시한다.
- 컨텍스트 조립: 청크마다 `[n] {title} | {url}` 헤더 + 본문.
- 응답 DTO:
  ```json
  { "answer": "...", "sources": [ { "index": 1, "title": "...", "url": "...", "source": "confluence|openapi", "snippet": "..." } ] }
  ```
- 스트리밍(`/v1/ask/stream`): SSE. `event: token`으로 토큰 전송, 마지막에 `event: sources`(JSON), `event: done`.
- 멀티턴 대화 이력은 PoC 범위 밖. 단일 질의만 처리한다.

### 5-7. API·UI — `ask_controller`, `static/index.html`

| 메서드/경로 | 요청 | 응답 |
|---|---|---|
| `POST /v1/ask` | `{ "question": str, "source": "all"\|"confluence"\|"openapi" = "all", "top_k": int? }` | AskResponse |
| `POST /v1/ask/stream` | 동일 | SSE |
| `POST /v1/reload` | 없음 | `{ "chunk_count": int }` |
| `GET /check` | 없음 | `{ "status": "ok"\|"degraded", "ollama": bool, "chunk_count": int }` |

- UI: 프레임워크 없는 단일 HTML. 입력창, 소스 선택(all/confluence/openapi), 스트리밍 답변 표시, 소스 카드(제목 클릭 → Confluence/Swagger 링크).
- Swagger UI(`/docs`)는 기존 프로젝트 `main.py` 패턴을 따른다.

## 6. 데이터 흐름

**인제스트** — `python ingest.py --active-profile=local --source all`
1. Confluence 페이지 목록 조회 → manifest와 version 비교 → 변경분만 본문 변환·청킹
2. OpenAPI 각 URL 다운로드 → 렌더링 → 해시 비교 → 변경분 청킹
3. 변경 doc의 기존 청크 삭제 → 임베딩 → Chroma upsert → manifest 갱신
4. 요약 출력

**질의** — `POST /v1/ask`
1. 요청 검증 → 2. Hybrid 검색(top_k) → 3. 컨텍스트 조립 → 4. LLM 호출 → 5. `answer` + `sources` 반환

## 7. 에러 처리

| 상황 | 처리 |
|---|---|
| Confluence 401/403 | 인증 정보 안내 메시지 출력 후 인제스트 중단(종료코드 1) |
| Confluence/OpenAPI 429·5xx·네트워크 오류 | 지수 백오프 3회 재시도 후 해당 소스 실패 기록, 다른 소스는 계속 |
| OpenAPI 스펙 파싱 실패(잘못된 `$ref` 등) | 해당 endpoint/schema만 건너뛰고 경고 로그 |
| Ollama 미기동/모델 없음 | `/check`는 `degraded`, `/v1/ask`는 503 + 안내 메시지 |
| 검색 결과 0건 | LLM 호출 없이 "관련 문서를 찾지 못했습니다" 즉시 반환(sources 빈 배열) |
| LLM 타임아웃 | ini `llm-timeout`(기본 120초) 초과 시 504 |
| 인제스트 중 Chroma 쓰기 실패 | 해당 doc은 manifest 미갱신 → 다음 실행에서 재시도 |

## 8. 테스트·검증

- **단위 테스트**(외부 의존 없음): storage HTML → Markdown 변환(code 매크로·표·링크), 청킹(헤딩 분할·접두어·id), OpenAPI 렌더링(`$ref` 해석·깊이 제한·순환 참조), manifest 증분 diff(추가/변경/삭제), BM25 토크나이저. 픽스처: `test/fixtures/` 아래 샘플 storage HTML, 축약 openapi.json.
- **통합 테스트**(`@pytest.mark.integration`, Ollama 필요, 기본 실행에서 제외): 소량 문서 인제스트 → `/v1/ask` 응답에 sources 포함 확인.
- **검색 품질 평가**: `eval/questions.yaml`에 질문 + 기대 doc_id 10~20개 → `eval/run_eval.py`가 hit@k 출력. **PoC 성공 기준: hit@6 ≥ 80%.** 미달 시 청크 크기·가중치 조정 → 그다음 로컬 리랭커(`bge-reranker-v2-m3`) 추가 검토.

## 9. 설정 — `resources/config_local.ini`

```ini
[common]
log-level=DEBUG
log-file-path={project_root}/logs
version=1.0
api-root=v1
health_check_endpoint=check

[swagger]
title=KUDOS RAG API
summary=팀 Confluence + OpenAPI 기반 RAG (local)

[fastapi]
host=127.0.0.1
port=5010
reload=True

[ollama]
base-url=http://127.0.0.1:11434
llm-model=qwen3:14b
embedding-model=bge-m3
num-ctx=16384
temperature=0
llm-timeout=120

[chroma]
persist-dir={project_root}/data/chroma
collection=kudos_rag

[confluence]
base-url=https://ihunet.atlassian.net/wiki
space-key=KUDOS
email=
api-token=            ; 환경변수 CONFLUENCE_API_TOKEN 우선

[openapi]
sources-file={project_root}/resources/openapi_sources.yaml

[retrieval]
chunk-size=1000
chunk-overlap=150
top-k=6
bm25-k=10
vector-k=10
bm25-weight=0.4
vector-weight=0.6
embed-batch-size=32
```

- `{project_root}`는 `Profile`에서 `global_variable.PROJECT_ROOT_DIR`로 치환한다.
- `.env`, `data/`, `logs/`, `.venv/`는 `.gitignore` 대상.

## 10. 사내 서버 이전 시 고려 (PoC 범위 밖)

- LLM/임베딩 생성은 `llm_factory` 한 곳에서만 수행 → 서버 GPU 환경에서 vLLM(OpenAI 호환 API)로 교체 가능.
- `Dockerfile` + `docker-compose.yml`(app + ollama) — 기존 배포 절차(`/app/{프로젝트명}`, `docker-compose up -d`)와 동일하게.
- `data/chroma`는 볼륨 마운트.

## 11. 범위 밖 (이번 PoC에서 하지 않음)

- 첨부파일 인제스트(txt/csv/xlsx → 다음 단계, 이미지/drawio → 미정)
- Confluence 페이지 권한을 답변에 반영하는 접근 제어
- 멀티턴 대화 이력
- 리랭커(품질 미달 시 추가 검토)
- Docker/배포 구성
