# Task 4: OpenAPI 스펙 → endpoint/schema Document 렌더링

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 4
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 1 (`GlobalLogger`). Task 2·3과 독립.
- 상태: **신규 구현 — Builder 시작 대기**

## 목표

OpenAPI 3.x 스펙(dict)을 endpoint 1개 = Document 1개, components.schemas 1개 = Document 1개로 렌더링한다. `$ref`는 인라인으로 펼치되 깊이 제한과 순환 차단을 둔다. 이후 Task 5(스펙 다운로드)·Task 9(인제스트)의 입력이 된다.

## 설계

### 컴포넌트

`src/service/openapi_document_service.py` 단일 모듈. 외부 의존: `langchain_core.documents.Document`. 내부 의존: `GlobalLogger`. `Profile` 미사용(순수 함수).

### 데이터 흐름

```
spec: dict, source: OpenApiSource
  ├─ paths[path][method] (get/post/put/patch/delete/head/options 순)
  │     └─ render_endpoint(...) → Markdown  ── OpenApiRefError 시 warning 로그 후 해당 endpoint 건너뜀
  │     └─ Document(metadata: source/doc_id/service/method/path/tags/url/title)
  └─ components.schemas[name]
        └─ render_schema(...) → Markdown    ── OpenApiRefError 시 warning 로그 후 건너뜀
        └─ Document(metadata: 동일 키, method=""/path=""/tags="")
```

### 인터페이스 (Produces)

```python
SOURCE_OPENAPI = "openapi"

@dataclass(frozen=True)
class OpenApiSource:
    name: str
    spec_url: str
    docs_url: str

class OpenApiRefError(Exception): ...

def resolve_ref(spec: dict, ref: str) -> dict
    # "#/..." 내부 참조만 지원. JSON Pointer 이스케이프(~1→/, ~0→~) 처리. 대상 없음·외부 ref → OpenApiRefError
def render_endpoint(spec: dict, source: OpenApiSource, path: str, method: str, operation: dict) -> str
def render_schema(spec: dict, name: str, schema: dict) -> str
def build_documents(spec: dict, source: OpenApiSource) -> list[Document]
```

상수: `_MAX_DEPTH = 3`, `_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")`.

### 렌더링 규칙

**endpoint** (`render_endpoint`):

| 순서 | 출력 | 조건 |
|---|---|---|
| 1 | `## {METHOD} {path} — {summary}` (summary 없으면 ` — ` 제거) | 항상 |
| 2 | `서비스: {info.title} ({source.name})` (title 없으면 source.name) | 항상 |
| 3 | `태그: a, b` | tags 있을 때 |
| 4 | 빈 줄 + description | description 있을 때 |
| 5 | `### Parameters` + 표 `| name | in | type | required | description |` (required는 `예`/`아니오`) | parameters 있을 때. 항목이 `$ref`면 resolve |
| 6 | `### Request Body ({타입 라벨})` + 필드 목록 | requestBody.content에 스키마 있을 때. `application/json` 우선, 없으면 첫 media |
| 7 | `### Responses` + `- {status}: {description} → {타입 라벨}`; 2xx는 필드 목록을 2칸 들여 추가 | responses 있을 때 |

**schema** (`render_schema`): `## Schema {name}` → (description) → `타입: {라벨}` → 필드 목록. `seen`에 자기 이름을 넣고 시작해 자기참조를 이름으로 끊는다.

**타입 라벨** (`_type_label`): `$ref` → 참조 이름, `anyOf/oneOf` → ` | ` 결합, `array` → `array<items 라벨>`, 그 외 `type`(없고 `properties` 있으면 `object`, 둘 다 없으면 `any`).

**필드 목록** (`_schema_lines`): `- {field} ({라벨})[ (필수)][: {description}]`. 중첩 object / object 배열은 depth+1로 2칸 들여 펼친다. `$ref` 이름이 `seen`에 있거나 depth > `_MAX_DEPTH`면 `- ({name})`만 출력하고 재귀하지 않는다.

**metadata** (Chroma 제약: `str` 값만, `None` 금지):

| key | endpoint | schema |
|---|---|---|
| `source` | `"openapi"` | `"openapi"` |
| `doc_id` | `"{service}:{METHOD}:{path}"` | `"{service}:schema:{name}"` |
| `service` | `source.name` | `source.name` |
| `method` | `"POST"` | `""` |
| `path` | path | `""` |
| `tags` | `", ".join(tags)` | `""` |
| `url` | `source.docs_url` | `source.docs_url` |
| `title` | `"{METHOD} {path}"` | `"Schema {name}"` |

### 오류 처리

- 깨진 `$ref`(`OpenApiRefError`)는 **해당 endpoint/schema만** `logger.warning` 후 건너뛴다. 나머지 문서는 정상 생성.
- 외부 파일 `$ref`(`other.yaml#/...`)는 지원하지 않음 → `OpenApiRefError`.

### 기각한 대안

- 스펙 전체를 하나의 Document로 넣고 청킹에 맡기기: endpoint 경계와 무관하게 잘려 검색 시 메서드·경로가 섞임. endpoint 단위 문서가 인용에도 유리.
- `$ref`를 펼치지 않고 이름만 표기: 요청 필드명(`service_key` 등)이 본문에 없어 BM25가 필드명 질의를 못 잡음. 깊이 3까지 인라인.
- `openapi-spec-validator`/`prance` 등 외부 파서: 새 의존성. 내부 `#/` 참조만 필요하므로 직접 해석.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 4 Step 3 코드는 참조 구현이며, 위 인터페이스·렌더링 규칙·테스트를 지키는 범위에서 간결화 가능.

1. `test/fixtures/openapi_sample.json`, `test/test_openapi_document_service.py` 작성 — 상위 계획 Task 4 Step 1 그대로(픽스처 1개, 테스트 6개). 테스트는 계약이므로 변경하지 않는다.
2. `pytest --active-profile=local test/test_openapi_document_service.py -v` → `ModuleNotFoundError`로 실패 확인.
3. `src/service/openapi_document_service.py` 작성 — 상위 계획 Task 4 Step 3을 참조 구현으로.
4. 같은 명령 → 6 PASSED 확인.
5. `pytest --active-profile=local -v` 전체 → 회귀 없음(기존 63 + 6 = 69 passed 기대).
6. 완료 보고: 실행 명령·결과, 생성 파일 목록, 참조 구현과 다르게 작성한 점(없으면 "없음").

**7. (ESCALATE 회차 1 수정)** `src/service/openapi_document_service.py:74`를 위 "리드 결정" 절의 "변경 후" 코드로 수정한다. 그 한 줄만 변경. 이후:
   - `pytest --active-profile=local test/test_openapi_document_service.py -v` → 전부 PASS (Validator가 추가한 결함 증거 테스트 2건 포함, 26 passed 기대)
   - 전체 `pytest --active-profile=local -v` → green (89 passed 기대)
   - 완료 보고: 변경 diff 한 줄, 테스트 결과. **Validator가 추가한 테스트는 수정하지 않는다.**

**하지 않을 것:** 커밋, 스펙 URL 실제 호출(다운로드는 Task 5), `openapi_sources.yaml` 로딩(Task 5), 설정파일 수정.

## 리드 결정: ESCALATE 회차 1 — 중첩 `$ref` 미전개 결함 (2026-09-21)

**Validator 보고** `[검증]`: `_schema_lines` 호출부(`:74`)가 `seen | {name}`으로 이름을 미리 넣어 재귀하고, 재귀 진입부(`:58`)가 `if name in seen`으로 즉시 차단 → 중첩 `$ref`는 depth·seen 조건과 무관하게 항상 `- ({name})`만 출력되고 `resolve_ref`가 호출되지 않는다. 파생: schema 내부의 깨진 `$ref`가 예외 없이 `- (Missing)`으로 조용히 렌더된다. 재현: `render_schema(SPEC, "MessageResponse", ...)`에서 `request` 하위 필드(`service_key` 등)가 전개되지 않음.

**리드 확인** `[검증]`: 코드 추적으로 동일 결론. 결함은 상위 계획 Task 4 Step 3 **참조 구현 자체**에 있으며, Builder 산출물은 참조 구현과 동일하다. 계획서 테스트 6개는 최상위 `$ref`만 다루어 이 결함을 잡지 못한다.

**결정: 수정한다 (선택지 a).** 근거:
- 설계 "기각한 대안"에서 `$ref` 이름만 표기하는 방식을 기각한 이유(필드명이 본문에 없으면 BM25가 필드명 질의를 못 잡음)가 중첩 ref에서 그대로 무력화된다. 현행 동작을 규칙으로 인정하면 설계 의도와 충돌한다.
- 명세 "오류 처리"의 "깨진 `$ref`는 해당 endpoint/schema만 누락 + warning"은 현행 구현으로 schema 쪽에서 원리적으로 충족 불가.

**수정 내용** (Builder 작업 7): `src/service/openapi_document_service.py:74`
```python
# 변경 전
lines.extend(_schema_lines(spec, nested, depth + 1, seen | ({name} if name else set()), indent + "  "))
# 변경 후 — 이름 추가는 재귀 진입부(:60)가 수행하므로 호출부는 seen 그대로 전달
lines.extend(_schema_lines(spec, nested, depth + 1, seen, indent + "  "))
```
이 한 줄 외 변경 금지. 규칙별 영향(리드 추적): 자기참조는 `:72`의 `continue`로 유지, 상호순환 A→B→A는 B 전개 후 A에서 차단(종료), 깊이 제한은 `:70` 그대로, 깨진 중첩 ref는 `OpenApiRefError`로 전파돼 해당 schema만 누락.

**계획서와의 차이**: 이 수정으로 구현이 상위 계획 Task 4 Step 3 코드와 한 줄 달라진다. conventions.md §3에 따라 **명세가 우선**한다. 계획서(`docs/superpowers/plans/`)는 리드 쓰기 영역이 아니므로 동기화는 사용자에게 안내한다.

**비차단 의견(Validator)**: 상호순환 시 `- b (B)` 아래 `  - (B)` 같은 중복 표기가 남을 수 있음 — 규칙대로의 출력이며 변경하지 않는다.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 6개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_openapi_document_service.py -v` |
| 회귀 없음 | 전체 green |
| 네트워크 비의존 | 소켓 차단 상태에서 통과 |
| 순환 `$ref` 무한 재귀 없음 | `test_circular_ref_is_cut_by_name` + 상호 순환(A→B→A) 스키마 2개를 만들어 `render_schema`·`build_documents`가 반환되는지 확인 |
| 깊이 제한 | 4단계 중첩 object 스키마 → 3단계까지만 펼쳐지고 그 아래는 펼치지 않음 |
| 깨진 `$ref` 부분 실패 | `test_broken_ref_skips_only_that_item` + schema 쪽 깨진 ref도 해당 schema만 누락. `logger.warning` 호출 확인(caplog) |
| 외부 `$ref` 거부 | `resolve_ref(spec, "other.yaml#/x")` → `OpenApiRefError` |
| JSON Pointer 이스케이프 | `components.schemas` 키에 `/`가 포함된 이름(`a/b` → `#/components/schemas/a~1b`) resolve 성공 |
| metadata 타입 | 모든 Document metadata 값이 `str`, `None` 없음 (schema 문서의 `method`/`path`/`tags`가 `""`) |
| Parameters 표 | `$ref` 파라미터(`#/components/parameters/...`)도 resolve돼 표에 나옴 |
| Request Body media 폴백 | `application/json` 없이 `multipart/form-data`만 있을 때 그 스키마 사용 |
| summary 없는 endpoint | 헤더가 `## GET /x`로 끝나고 ` — `가 남지 않음 |
| 빈 spec | `paths`·`components` 없는 `{}` 입력 → `[]` 반환, 예외 없음 |
| 구현이 명세와 일치 | "인터페이스"·"렌더링 규칙"·"metadata" 표와 코드 대조 |

## 완료 기준

- [x] `test/test_openapi_document_service.py` 6 PASSED (Validator 추가 후 27 passed)
- [x] 전체 `pytest --active-profile=local` green (90 passed)
- [x] 소켓 차단 상태에서 통과
- [x] 자기참조·상호참조 `$ref`에서 무한 재귀 없음, 깊이 3 초과 미전개(중첩 object·`$ref` 체인 모두)
- [x] 깨진 `$ref`는 해당 항목만 누락 + warning 로그 (endpoint·schema 양쪽)
- [x] 모든 metadata 값 `str`, `None` 없음
- [x] 구현이 이 문서의 인터페이스·렌더링 규칙과 일치 (계획서 Step 3과의 차이는 `:74` 한 줄만)

## 판정

**READY FOR REVIEW** (2026-09-21, 검증 회차 2). 회차 1 결함(중첩 `$ref` 미전개) 해소 확인, 전체 90 passed, 설계 문서와 구현 일치.
→ **리뷰 1 통과 (2026-09-21) — 커밋 대기.** 리드 결정(`:74`)은 리뷰에서 타당성 재확인됨.

커밋 대상(사용자 수행): `src/service/openapi_document_service.py`, `test/fixtures/openapi_sample.json`, `test/test_openapi_document_service.py`.

**계획서 재유입 주의**: 상위 계획 Task 4 Step 3 코드 블록(1041행 부근)에 수정 전 `seen | ({name} if name else set())` 줄이 남아 있다. 이후 Task에서 이 함수를 참조 구현으로 다시 쓰는 경우는 없지만(단일 모듈), 계획서를 동기화하지 않으면 문서와 코드가 불일치한 상태로 남는다. 동기화는 사용자 결정.

## 범위 제외

- 스펙 다운로드·`openapi_sources.yaml` 로딩 → Task 5
- Swagger 2.0(`swagger: "2.0"`) 스펙
- 외부 파일 `$ref`, `allOf` 병합(현재는 `type` 라벨로만 표기)
- `security`, `servers`, `examples` 렌더링
- 청킹 → Task 6
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 작성. Builder에게 시작 지시.
- 2026-09-21 Builder 완료 보고: RED → 6 passed → 전체 69 passed(기대치 63+6 일치). 생성: `src/service/openapi_document_service.py`, `test/fixtures/openapi_sample.json`, `test/test_openapi_document_service.py`. 참조 구현과 다른 점 없음 — 제거 후보(`_content_schema` 폴백, `.rstrip(" —")`, `or {}` None 처리, `seen`/`depth` 이중 차단)가 모두 검증 전략 항목과 직결되어 유지.
- 2026-09-21 리드: 구현을 인터페이스·렌더링 규칙·metadata 표와 대조해 일치 확인(`[검증]`). Builder 질의(검증 전략 추가 테스트 담당) → Validator 담당으로 확정, `conventions.md` §2-2 기록. Validator에게 검증 지시.
- 2026-09-21 Validator 회차 1: **ESCALATE TO LEAD**. 87 passed / 2 failed(추가한 결함 증거 테스트). 중첩 `$ref` 미전개 결함 — 참조 구현 자체의 문제. Validator 추가 테스트 +20(기존 6개 미수정).
- 2026-09-21 리드: 코드 추적으로 결함 확인, **수정 결정(a)**. 작업 7 추가, Builder에게 지시. 계획서 참조 구현과 한 줄 달라지므로 사용자에게 계획서 동기화 안내.
- 2026-09-21 Builder 작업 7 완료: `:74` 한 줄 수정(`seen | ({name} if name else set())` → `seen`), 주석 미추가. `test_openapi_document_service.py` 26 passed(실패 2건 → PASS), 전체 89 passed. 변경 파일 1개 1라인.
- 2026-09-21 리드: 주석 미추가 수용(수정 근거는 이 문서에 기록됨, 코드 최소 변경 우선). Validator에게 회차 2 검증 지시.
- 2026-09-21 Validator 회차 2: 완료 기준 전부 PASS. 결함 증거 2건 PASS 전환, 소켓 차단 90 passed, 계획서 대비 차이 `:74` 한 줄만. 추가 테스트 +1(`$ref` 체인 깊이 경계), 누적 21. 발견 버그 없음.
- 2026-09-21 리드: READY FOR REVIEW 선언. Task 5 지시로 이동.
