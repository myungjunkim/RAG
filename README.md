# KUDOS RAG (PoC)

팀 Confluence `KUDOS` 스페이스와 팀 FastAPI 서비스의 OpenAPI 스펙을 근거로 답하는 로컬 RAG.
LLM/임베딩은 로컬 Ollama 만 사용한다(사내 문서를 외부 API 로 보내지 않는다).

설계: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`

## 사전 준비

1. Ollama
   ```bash
   brew install ollama
   ollama serve            # 별도 터미널
   ollama pull qwen3:14b   # 약 9GB
   ollama pull bge-m3      # 약 1.2GB
   ```
   두 모델이 없으면 인제스트·질의가 동작하지 않는다. 임베딩 모델이 없을 때 `ingest.py` 는
   안내 메시지를 출력하고 종료 코드 1 로 끝나며, **기존 인덱스와 manifest 는 건드리지 않는다**
   (`--full` 을 붙여도 초기화 전에 중단된다).

2. Atlassian API 토큰: https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급
   ```bash
   export CONFLUENCE_API_TOKEN=...   # 커밋 금지
   ```
   `resources/config_local.ini` 의 `[confluence] email` 에 Atlassian 계정 이메일을 입력한다.
   토큰은 환경변수가 우선이며, ini 의 `api-token` 은 **비워 둔다**(자격 증명을 커밋하지 않는다).

## 개발 환경

Python 3.12 기준이다.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pip-tools
pip-compile --no-index --output-file=requirements.txt requirements.in   # requirements.in 변경 시
pip install -r requirements.txt
```

`pip-compile` 옵션은 `requirements.txt` 헤더에 기록된 명령과 동일하게 유지한다.

운영 프로파일이 필요하면 `resources/config_<profile>.ini` 를 만들고 `--active-profile=<profile>` 로
선택한다(예: `host=0.0.0.0`, `reload=False`).

### 의존성 메모 (미결정 사항)

아래 3개는 코드가 **직접 import** 하지만 `requirements.in` 에는 없고 다른 패키지의 전이 의존성으로만
설치되어 있다. 상위 패키지의 의존성 트리가 바뀌면 조용히 깨질 수 있어 직접 명시를 권고하지만,
의존성 파일 변경은 사용자 결정 사항이라 **미반영 상태**다.

| 패키지 | 현재 경로 | 사용처 |
|---|---|---|
| `langchain-text-splitters` | via `langchain-classic` | `src/service/chunk_service.py` |
| `langchain-classic` | via `langchain-community` | `src/service/retriever_service.py` |
| `ollama` | via `langchain-ollama` | `src/service/llm_factory.py` (`LLM_ERRORS`) |

## 인제스트

```bash
python ingest.py --active-profile=local --source all        # confluence + openapi 증분
python ingest.py --active-profile=local --source openapi    # 특정 소스만
python ingest.py --active-profile=local --full              # 전체 재구축
```

결과는 `data/chroma`(벡터), `data/manifest.json`(증분 기준)에 저장된다.
OpenAPI 대상은 `resources/openapi_sources.yaml` 에 추가한다. **`name` 은 유일해야 한다** —
중복되면 경고 없이 마지막 항목만 반영된다.

### `--full` 재인제스트가 필요한 경우

증분 인제스트는 Confluence 는 페이지 `version`, OpenAPI 는 렌더 결과 해시로 변경을 감지한다.
아래 세 경우에는 감지되지 않으므로 `--full` 이 필요하다.

1. `[retrieval]` 의 `chunk-size` / `chunk-overlap` 을 바꾼 뒤 — 문서 내용이 그대로여서 변경으로 잡히지 않는다.
2. 인제스트가 중간에 중단된 뒤 — manifest 는 문서 단위로 갱신되므로 일부만 반영된 상태가 남는다.
3. `openapi_sources.yaml` 에서 서비스를 제거한 뒤 — 수집 대상에서 빠진 서비스의 기존 청크는
   "수집 실패" 와 구분되지 않아 자동 삭제되지 않는다.

`--full` 로 재인제스트한 뒤에는 **서버를 재기동할 필요 없이** `POST /v1/reload` 로 반영된다.
다만 `--full` 완료 직후 **반드시** `POST /v1/reload` 를 호출해야 한다 — 그 사이에 들어온 `/v1/ask` 는
서버가 삭제된 옛 컬렉션을 참조해 500 이 난다.

## 서버

```bash
python main.py --active-profile=local
```

- UI: http://127.0.0.1:5010/
- Swagger: http://127.0.0.1:5010/docs
- `POST /v1/ask` `{"question": "...", "source": "all|confluence|openapi", "top_k": 6}`
- `POST /v1/ask/stream` (SSE), `POST /v1/reload` (재인제스트 후 인덱스 재로드), `GET /check`

Ollama 가 떠 있지 않아도 서버는 기동된다. 이 경우 `/check` 가 `degraded` 를 반환한다.
`/v1/ask` 는 인덱스가 비어 있으면 LLM 을 호출하지 않고 "관련 내용을 문서에서 찾지 못했습니다." 를
200 으로 돌려주고, 청크가 있는 상태에서 LLM 호출이 실패하면 503(원인 메시지 포함),
응답 시간 초과는 504 로 구분된다.

### 브라우저 확인 체크리스트

UI 렌더링은 자동 테스트로 확인하지 않으므로 아래를 육안으로 확인한다.

- [ ] 헤더에 `상태: ok · Ollama 연결됨 · 청크 N개` 가 표시된다(Ollama 미기동이면 `degraded · Ollama 끊김`).
- [ ] 소스를 `OpenAPI` 로 두고 "메시지 등록 API 호출 방법 알려줘" 입력 → 답변이 **토큰 단위로 이어서** 표시된다.
- [ ] 답변이 끝나면 아래에 소스 카드가 붙고, 카드 제목을 누르면 해당 문서가 **새 탭**으로 열린다.
- [ ] 질의 중에는 입력창과 질문 버튼이 비활성화되고, 완료 후 다시 활성화된다.
- [ ] 서버를 내린 뒤 질문 → **빨간 오류 메시지**가 표시되고 입력이 다시 활성화된다.

## 테스트

```bash
pytest --active-profile=local                                  # 단위 테스트 (Ollama 불필요)
pytest --active-profile=local -m integration                   # 통합 테스트 (Ollama 필요)
python -m eval.run_eval --active-profile=local --k 6           # 검색 품질 hit@6 (기준 80%)
```

`run_eval` 은 인제스트 완료와 Ollama `bge-m3` 가 필요하다. 80% 미달 또는 질문이 없으면 종료 코드 1 이며,
`--file` 로 다른 평가 세트를 지정할 수 있다. **프로젝트 루트에서 실행한다.**

## 평가 세트 (`eval/questions.yaml`)

질문마다 `expected_doc_ids` 중 하나라도 상위 k 청크에 있으면 hit 으로 센다.
현재 OpenAPI 3문항만 채워져 있고 **3문항으로는 통계적 의미가 없다** — 기준 80% 는
문항을 충분히(10개 이상) 채운 뒤에야 의미를 가진다.

3번 문항(헬스체크)의 기대값 `message-api:GET:/check`, `general-chatbot-api:GET:/check` 는 실제 스펙에서
확인하지 않은 값이다. 인제스트 후 `data/manifest.json` 에 이 doc_id 가 있는지 먼저 확인하고,
없으면 실제 헬스체크 경로로 교체한다. 3문항 중 1문항만 어긋나도 67% 가 되어 종료 코드 1 이 된다.

```bash
python -c "import json;d=json.load(open('data/manifest.json'));print([k for k in d if ':GET:' in k and 'check' in k])"
```

### Confluence 문항 채우기 (사용자 작업)

Confluence 인제스트는 API 토큰이 필요해 자동화하지 않았다. 아래 절차로 채운다.

1. `python ingest.py --active-profile=local --source confluence` 로 인제스트한다.
2. `data/manifest.json` 을 열어 `"source": "confluence"` 인 엔트리를 찾는다. **각 엔트리의 key 가
   Confluence page id** 다.
   ```bash
   python -c "import json;d=json.load(open('data/manifest.json'));print([k for k,v in d.items() if v['source']=='confluence'][:20])"
   ```
3. 페이지 제목은 `https://ihunet.atlassian.net/wiki/spaces/KUDOS/pages/<page_id>` 로 확인한다.
4. `eval/questions.yaml` 하단의 주석 템플릿을 참고해 `question` / `source: confluence` /
   `expected_doc_ids: ["<page_id>"]` 를 추가한다.

## 튜닝 포인트 (`resources/config_local.ini` `[retrieval]`)

`chunk-size`, `chunk-overlap`, `top-k`, `bm25-weight`/`vector-weight`.
`hit@k` 가 기준에 못 미치면 가중치(경로·식별자 질의가 약하면 `bm25-weight` ↑)와 청크 크기를 조정해
재실행한다. **청킹 관련 값을 바꾸면 `--full` 재인제스트가 필요하다.**

## 로그

`logs/app.log` 에 기록된다. 프로젝트 로그는 `[common] log-level`(기본 DEBUG) 을 따르고,
서드파티(`httpx`, `httpcore`, `urllib3`, `chromadb`, `watchfiles`)는 WARNING 이상만 남긴다.

`[fastapi] reload=True` 로 기동하면 리로더와 앱 두 프로세스가 같은 파일에 append 하므로
줄 순서가 섞여 보일 수 있다(파일 손상은 아니다). 운영 환경에서는 `reload=False` 를 쓴다.

## 그 밖의 메모

- **외부 전송 없음**: Chroma 의 익명 사용 통계(텔레메트리)는 비활성화되어 있다.
- **유지보수**: `langchain-community` 는 sunset 예정이며 import 시 `DeprecationWarning` 이 발생한다.
  현재 `BM25Retriever` 만 이 패키지에서 가져오므로, 사내 서버 이전 시 독립 패키지 또는
  `rank-bm25` 직접 사용으로 대체하는 것을 검토한다.
