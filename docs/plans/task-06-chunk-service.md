# Task 6: Markdown 헤딩 기반 청킹

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 6
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 2·4 (`Document` 형식). `Profile` 미사용 — `chunk_size`/`chunk_overlap`은 호출자(Task 8)가 `[retrieval]`에서 읽어 넘긴다.
- 상태: **신규 구현 — Builder 시작 대기(5-F 보고 후 착수)**

## 목표

Task 2·4가 만든 Markdown `Document`를 검색 단위 청크로 나눈다. Confluence 문서는 헤딩(h1~h3) 경계로 나누고 각 청크 앞에 `[breadcrumb > 섹션 경로]` 접두어를 붙여 문맥을 보존한다. OpenAPI 문서는 endpoint 하나가 검색 단위이므로 매우 길 때만 나눈다.

## 설계

### 컴포넌트

`src/service/chunk_service.py` 단일 모듈. 외부 의존: `langchain_core.documents.Document`, `langchain_text_splitters.MarkdownHeaderTextSplitter`, `langchain_text_splitters.RecursiveCharacterTextSplitter`. 내부 의존 없음(순수 함수).

### 의존성 확인 (Builder 작업 0)

`langchain-text-splitters`는 `requirements.in`에 직접 명시돼 있지 않다. `[미확인]` `langchain` 1.x의 전이 의존성으로 설치돼 있는지. Builder는 구현 전에 `source .venv/bin/activate && python -c "from importlib.metadata import version; print(version('langchain-text-splitters'))"`로 확인한다(패키지에 `__version__` 속성 없음 — Builder·Validator 확인으로 정정).
- 설치돼 있으면 그대로 진행. 직접 import하므로 Task 2의 `beautifulsoup4`와 같은 이유로 `requirements.in`에 명시하는 것이 맞지만, **의존성 파일 변경은 사용자 허가 사항**(CLAUDE.md §7)이므로 Builder는 변경하지 말고 완료 보고에 "requirements.in 명시 필요 여부"를 적는다. 리드가 사용자에게 안내한다.
- 설치돼 있지 않으면 **ESCALATE** — 코드 작성 없이 리드에게 보고.

### 데이터 흐름

```
split_documents(docs, chunk_size, chunk_overlap)
  └─ page_content가 공백뿐인 문서 → 청크 0개
  └─ metadata.source == "openapi" → _split_openapi
  └─ 그 외(confluence) → _split_confluence

_split_confluence(doc)
  └─ MarkdownHeaderTextSplitter(h1/h2/h3, strip_headers=False).split_text
  └─ 섹션마다: section_path = "h1 > h2 > h3"(있는 것만)
                prefix = "[breadcrumb > section_path]\n"   (breadcrumb 없으면 title)
                body_limit = max(chunk_size - len(prefix), chunk_size // 2)
                body가 body_limit 이하 → 1조각, 초과 → RecursiveCharacterTextSplitter(body_limit, overlap)
  └─ 각 조각 → _make_chunk(doc, index, prefix + piece, section_path)

_split_openapi(doc)
  └─ len(text) <= chunk_size * 3 → 청크 1개(원문 그대로, section "")
  └─ 초과 → 첫 줄(## METHOD path — summary)을 header로 떼고 나머지를
             RecursiveCharacterTextSplitter(limit - len(header) - 1, overlap)로 나눠
             각 조각 앞에 header 재부착
```

### 인터페이스 (Produces)

```python
def split_documents(docs: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]
```

상수: `_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]`, `_OPENAPI_SPLIT_FACTOR = 3`.

**청크 metadata** = 원본 metadata 전체 복사 + 아래 3개 (Chroma 제약 `str|int` 준수):

| key | 타입 | 값 |
|---|---|---|
| `chunk_id` | str | `"{doc_id}#{n}"`, n은 문서 내 0부터 순번 |
| `chunk_index` | int | n |
| `section` | str | confluence: `"h1 > h2"` 헤딩 경로(헤딩 없으면 `""`), openapi: 항상 `""` |

**청크 본문 규칙**:
- confluence: `"[{breadcrumb} > {section_path}]\n{본문}"`. section_path가 비면 `"[{breadcrumb}]\n{본문}"`. 접두어 첫 줄은 Task 10 `_strip_prefix`가 스니펫에서 제거한다(`[`로 시작·`]`로 끝나는 첫 줄).
- openapi: 원문 그대로, 분할 시 각 조각이 header 줄로 시작.
- 청크 총길이는 `chunk_size + len(prefix)`를 넘지 않는다(접두어가 chunk_size의 절반을 넘는 극단 케이스 제외).

### Consumes

- Task 2 Document: `doc_id`, `source="confluence"`, `breadcrumb`(없으면 `title` 폴백), 나머지 키는 복사만
- Task 4 Document: `doc_id`, `source="openapi"`, 나머지 키는 복사만

### 알려진 라이브러리 동작

`[검증]`(langchain-text-splitters 1.1.2 소스 확인, Validator) `MarkdownHeaderTextSplitter(strip_headers=False)`는 **빈 줄로 분리된 블록을 합칠 때** `"  \n"`(공백 2 + 개행)을 쓰고, 빈 줄 없이 이어진 줄은 `"\n"`으로 잇는다. 예: `"## 요청\n\n요청 설명."` → `'## 요청  \n요청 설명.'`, `"## 요청\n요청 설명."` → `'## 요청\n요청 설명.'`. Task 2 `convert_storage_to_markdown`은 헤딩과 본문 사이에 빈 줄을 넣으므로 운영 경로에서는 `"  \n"` 형태가 된다(계획서 기록과 일치). 테스트는 부분 문자열만 확인하므로 영향 없음.

`[추측]` `MarkdownHeaderTextSplitter`는 펜스 코드블록(```` ``` ````) 내부의 `#`을 헤딩으로 취급하지 않는다. Task 2가 코드 매크로를 펜스 블록으로 변환하므로 `# 주석`이 포함된 Python 코드가 섹션을 쪼개면 안 된다. Validator 확인 항목.

### 기각한 대안

- OpenAPI 문서도 `### Parameters`/`### Responses` 헤딩으로 분할: endpoint가 검색·인용의 자연 단위이며, 분할하면 메서드·경로와 필드 목록이 다른 청크로 떨어져 "필수 파라미터" 질의에 불리. 3×chunk_size 초과 시에만 분할하고 header를 재부착.
- 토큰 기반 길이(`tiktoken`): 새 의존성. bge-m3 컨텍스트(8k 토큰)에 비해 1000자 청크는 충분히 작아 문자 기준으로 충분.
- 접두어를 본문 대신 metadata에만 두기: 임베딩·BM25가 문맥(상위 페이지 제목)을 보지 못해 "인증 > 요청" 같은 계층 질의에 불리. 본문에 넣고 스니펫에서만 제거.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 6 Step 3 코드는 참조 구현.

0. 의존성 확인(위 절). 미설치면 ESCALATE.
1. `test/test_chunk_service.py` 작성 — 상위 계획 Task 6 Step 1 그대로(6개). 변경 금지.
2. `pytest --active-profile=local test/test_chunk_service.py -v` → `ModuleNotFoundError` 확인.
3. `src/service/chunk_service.py` 작성 — 상위 계획 Task 6 Step 3 참조.
4. 같은 명령 → 6 PASSED.
5. 전체 `pytest --active-profile=local -v` → 회귀 없음(5-F 반영 후 기준선 + 6 기대).
6. 완료 보고: 실행 명령·결과, 생성 파일, 참조 구현과 다른 점, **`langchain_text_splitters` 버전과 requirements.in 명시 필요 여부**.

**하지 않을 것:** 커밋, `requirements.in`/`requirements.txt` 변경, Task 2·4 모듈 수정, `Profile` 참조.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 6개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_chunk_service.py -v` |
| 회귀 없음 | 전체 green |
| 네트워크 비의존 | 소켓 차단 상태에서 통과 |
| 헤딩 경계 분할·접두어·section | 계획서 테스트 + h3까지 3단 헤딩 문서에서 `section == "h1 > h2 > h3"` |
| 펜스 코드블록 내 `#` 미분할 | Task 2 출력 형식의 ```` ```python\n# 주석\nx = 1\n``` ```` 포함 문서 → 코드블록이 별도 섹션으로 쪼개지지 않음 |
| 길이 상한 | 긴 섹션 분할 시 모든 청크 `len <= chunk_size + len(prefix)`; 접두어가 매우 길어도(`chunk_size//2` 하한) 예외 없음 |
| chunk_index·chunk_id | 문서 내 0부터 연속, `chunk_id == f"{doc_id}#{chunk_index}"`, 문서 2개 입력 시 각각 0부터 시작 |
| metadata 보존 | 원본 키(`title`, `url`, `version`, `breadcrumb` / `service`, `method`, `path`, `tags`)가 모든 청크에 그대로 복사됨, 값 타입 `str|int` |
| breadcrumb 폴백 | `breadcrumb` 키 없는 confluence 문서 → 접두어에 `title` 사용 |
| 공백 문서 | `"   \n\n"` → 청크 0개 |
| openapi 분할 | 3×chunk_size 이하 → 1청크·원문 동일·`section == ""`; 초과 → 각 조각이 첫 줄 header로 시작, `chunk_index` 연속 |
| `"  \n"` 결합 동작 | 현재 설치 버전에서 계획서 기록과 동일한지 확인(보고서 기록용) |
| 구현이 명세와 일치 | 인터페이스·metadata 표·본문 규칙 대조 |

## 완료 기준

- [x] `test/test_chunk_service.py` 6 PASSED (Validator 추가 후 22 passed)
- [x] 전체 green (143 passed), 소켓 차단 상태 통과
- [x] 펜스 코드블록 내 `#`이 섹션을 나누지 않음
- [x] 모든 청크 metadata에 `chunk_id`/`chunk_index`/`section` 존재, 원본 키 보존, 값 타입 `str|int`
- [x] 길이 상한 준수 (접두어가 chunk_size 절반 초과 시 하한 적용도 확인)
- [x] 구현이 이 문서의 인터페이스·규칙과 일치 (계획서 Step 3과 IDENTICAL)
- [x] `langchain-text-splitters` 1.1.2 설치 확인·보고됨 (전이 의존성 → `requirements.in` 명시 권고, 사용자 결정)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. `source` 키 없는 Document → confluence 경로: 명세 규칙("그 외")대로. 변경 없음.
2. openapi 분할 조각이 `3×chunk_size`(~3000자)에 근접 — `[추측]` bge-m3 컨텍스트(8192 토큰)에 비해 충분히 작아 임베딩 절단은 없을 것으로 본다. **Task 7 통합 테스트 항목으로 추가**: 3000자 텍스트 `embed_query`가 예외 없이 1024차원을 반환하는지.

## 판정

**READY FOR REVIEW** (2026-09-21, 검증 회차 1). 모든 완료 기준 통과, 전체 143 passed, 설계 문서와 구현 일치.
→ **리뷰 2 통과 (2026-09-21) — 커밋 대기.** 상세: `review-02-task6-8.md`

커밋 대상(사용자 수행): `src/service/chunk_service.py`, `test/test_chunk_service.py`.
**사용자 결정**: `requirements.in`에 `langchain-text-splitters` 명시 여부.

## 범위 제외

- `chunk_size`/`chunk_overlap` 설정 읽기 → Task 8
- 표(table) 행 단위 분할 보호, 문장 경계 분할
- 토큰 기반 길이 계산
- 청크 임베딩·저장 → Task 7·8
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 작성. Builder에게 지시(5-F 보고 후 착수).
- 2026-09-21 Builder 완료: `langchain-text-splitters` 1.1.2 설치 확인(전이 의존성, `# via langchain-classic`). RED → 6 passed → 전체 127 passed. 생성 `src/service/chunk_service.py`, `test/test_chunk_service.py`. 참조 구현과 다른 점 없음. 펜스 코드블록 내 `#` 미분할 `[검증]`. **`requirements.in` 명시 권고** — Task 2 `beautifulsoup4`와 같은 상황(직접 import하는데 전이 의존성으로만 설치). 사용자 결정 사항.
- 2026-09-21 Validator 사전 확인: 코드블록 `#` 미분할 `[검증]` 동일. 줄 결합 동작이 Builder(`"  \n"`)와 Validator(`"\n"`) 관측에서 달랐으나 Validator가 소스 확인으로 해소 — 빈 줄 유무에 따른 차이로 둘 다 맞음(위 "알려진 라이브러리 동작"에 조건 반영). 테스트 영향 없음.
- 2026-09-21 리드: 구현 대조 후 Validator에게 검증 지시.
- 2026-09-21 Validator 회차 1: 완료 기준 전부 PASS. 테스트 +16. 계획서 테스트 입력으로 결합 문자 `"  \n"` 확정. 발견 버그 없음. 비차단 2건.
- 2026-09-21 리드: READY FOR REVIEW 선언. Task 7 지시.
