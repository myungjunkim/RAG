# Task 5: OpenAPI 소스 목록 로딩·스펙 다운로드 저장소

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 5
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 1 (`Profile`, `GlobalLogger`), Task 4 (`OpenApiSource`)
- 상태: **신규 구현 — Builder 진행 중** (Task 4 READY FOR REVIEW 확인 후 2026-09-21 지시)

## 목표

`resources/openapi_sources.yaml`에서 OpenAPI 소스 목록을 읽고, 각 `spec_url`에서 스펙(JSON 또는 YAML)을 다운로드해 dict로 돌려준다. 일시 오류는 제한 재시도한다.

## 설계

### 컴포넌트

`src/repository/openapi_repository.py` 단일 모듈. 외부 의존: `requests`, `yaml`(PyYAML — 이미 `requirements.in`에 있음). 내부 의존: `Profile`, `GlobalLogger`, `OpenApiSource`(Task 4).

### 데이터 흐름

```
sources_from_profile()
  └─ Profile().get_config("openapi")["sources-file"]  →  load_sources(path)
       └─ yaml.safe_load → sources[*] → OpenApiSource(name, spec_url, docs_url="")

fetch_spec(url)
  └─ session.get(url, timeout=30)  (재시도 표 아래)
  └─ 200 → _parse(text): json.loads 시도 → JSONDecodeError 면 yaml.safe_load(YAMLError → 오류)
                          → 어느 경로든 결과가 dict 가 아니면 오류
```

`fetch_spec` 재시도 정책(Task 3 `_get`과 동일 규칙, 인증 분기 없음):

| 상황 | 동작 |
|---|---|
| 200 | `_parse(response.text)` 반환 |
| 429, 500, 502, 503, 504 | 최대 3회, 시도 간 `sleep(2 ** (attempt-1))` (1s, 2s) |
| 그 외 non-200 (404 등) | 재시도 없이 `OpenApiFetchError` |
| `requests.RequestException` | 재시도 대상 |
| 3회 소진 | `OpenApiFetchError` (마지막 상태 포함) |
| 파싱 실패 / dict 아님 | `OpenApiFetchError` (재시도 없음) |

### 인터페이스 (Produces)

```python
class OpenApiFetchError(Exception): ...

def load_sources(path: str) -> list[OpenApiSource]
    # 파일 없음 → FileNotFoundError 그대로 전파. 빈 파일/`sources` 없음 → []

class OpenApiRepository:
    def __init__(self, session=None, sleep=time.sleep)
    @staticmethod
    def sources_from_profile() -> list[OpenApiSource]
    def fetch_spec(self, url: str) -> dict
```

상수: `_MAX_ATTEMPTS = 3`, `_TIMEOUT_SEC = 30`, `_RETRY_STATUS = {429, 500, 502, 503, 504}`.

`session.get(url, timeout=...)`만 사용(테스트 FakeSession 계약 — `params` 인자 없음). 응답은 `.status_code`, `.text`만 사용(`.json()` 사용 금지 — YAML 응답 지원과 FakeResponse 계약).

### 리드 판단: Task 3과의 재시도 로직 중복

`ConfluenceRepository._get`과 `fetch_spec`의 재시도 루프가 구조적으로 유사하다. 공통 헬퍼로 추출하지 않는다 — 인증 분기(401/403)와 `params` 유무, 응답 처리(`json()` vs `text`)가 다르고 사용처가 2곳뿐이어서 추상화 비용이 이득보다 크다(§4). 3번째 사용처가 생기면 재검토.

### 리드 결정: ESCALATE 회차 1 — `_parse`의 dict 검사 범위 (2026-09-21)

**Builder 보고** `[검증]`: 참조 구현 `_parse`는 `isinstance(data, dict)` 검사를 YAML 분기에만 두어, 유효한 JSON이면서 dict가 아닌 응답(`[1, 2]`, `123`)이 그대로 반환된다. 명세 재시도 표의 "dict 아님 → `OpenApiFetchError`"와 반환 타입 `-> dict`에 어긋나며, 명세 "데이터 흐름" 서술은 두 가지로 읽혀 판단이 갈린다.

**결정: 수정한다 (선택지 a).** 근거: OpenAPI 스펙은 항상 object이며, `build_documents(spec: dict, ...)`(Task 4)가 dict를 전제한다. JSON 배열이 통과하면 Task 9 인제스트에서 `spec.get` 호출 시점에 `AttributeError`로 늦게 터진다. 다운로드 단계에서 URL 오류를 명확한 메시지로 잡는 것이 설계 의도. "데이터 흐름"의 모호한 서술은 명세 결함이므로 함께 정정했다(위 블록).

**수정 내용** (Builder 작업 7): `src/repository/openapi_repository.py`의 `_parse`를 아래로 교체. 다른 곳 변경 금지.
```python
@staticmethod
def _parse(text: str, url: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise OpenApiFetchError(f"OpenAPI 스펙 파싱 실패: {url}: {e}") from e
    if not isinstance(data, dict):
        raise OpenApiFetchError(f"OpenAPI 스펙 형식이 올바르지 않습니다: {url}")
    return data
```
예외 메시지 문자열은 참조 구현과 동일하게 유지한다. 기존 계획서 테스트 6개는 영향 없음(Builder `[검증]` 확인).

**계획서와의 차이**: 참조 구현(계획서 Task 5 Step 3 `_parse`)과 구조가 달라진다. conventions.md §3에 따라 명세 우선. 계획서 동기화는 사용자 결정.

### 기각한 대안

- `_parse`에서 `json.loads`를 빼고 `yaml.safe_load` 하나로 통일: PyYAML(YAML 1.1)은 JSON을 대부분 파싱하지만 탭 문자·큰 정수·일부 이스케이프에서 JSON과 다르게 동작할 수 있어 JSON 우선 유지.
- `openapi_sources.yaml`을 ini `[openapi]` 섹션에 인라인: 소스가 리스트 구조라 ini에 부적합.
- `Content-Type` 헤더로 JSON/YAML 분기: FastAPI `openapi.json`은 JSON이지만 서버 설정에 따라 헤더가 부정확할 수 있음. 내용 기반 시도(JSON → YAML)가 더 견고하고 테스트가 단순.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 5 Step 3 코드는 참조 구현.

1. `test/test_openapi_repository.py` 작성 — 상위 계획 Task 5 Step 1 그대로(6개). 변경 금지.
2. `pytest --active-profile=local test/test_openapi_repository.py -v` → `ModuleNotFoundError` 확인.
3. `src/repository/openapi_repository.py` 작성 — 상위 계획 Task 5 Step 3 참조.
4. 같은 명령 → 6 PASSED.
5. 전체 `pytest --active-profile=local -v` → 회귀 없음(기존 90 + 6 = 96 passed 기대).
6. 완료 보고: 실행 명령·결과, 생성 파일, 참조 구현과 다른 점.

**7. (ESCALATE 회차 1 수정)** `_parse`를 "리드 결정" 절의 코드로 교체. 이후 `pytest --active-profile=local test/test_openapi_repository.py -v` → 6 PASSED, 전체 → 96 passed 확인. 완료 보고에 `_parse` diff와 `python -c`로 `'[1, 2]'`·`'123'` 입력이 `OpenApiFetchError`를 내는지 확인한 출력을 포함.

**하지 않을 것:** 커밋, 실제 스펙 URL 호출, `openapi_sources.yaml`·ini 수정, Task 3 코드 리팩터링(공통화 금지 — 위 리드 판단).

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 6개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_openapi_repository.py -v` |
| 회귀 없음 | 전체 green |
| 네트워크 비의존 | 소켓 차단 상태에서 통과. `sources_from_profile()`은 파일만 읽고 요청 없음 |
| 재시도·백오프 | 503→503→200 성공, `sleeps == [1, 2]`; 500×3 → `OpenApiFetchError`, calls 3회 |
| 404 무재시도 | `test_fetch_spec_404_no_retry` + 400 동일 |
| `RequestException` 재시도 | `ConnectionError`×3 → 3회 후 `OpenApiFetchError` |
| JSON/YAML 파싱 | 기존 2개 + 잘못된 YAML(`"a: [b"`) → `OpenApiFetchError`; 스칼라/리스트 YAML(`"- a"`) → `OpenApiFetchError`; **JSON 리스트(`"[1, 2]"`)·JSON 스칼라(`"123"`) → `OpenApiFetchError`**; 파싱 실패는 재시도 없이 1회 호출 |
| `load_sources` 경계 | `docs_url` 누락 → `""`; 빈 파일 → `[]`; `sources:` 없는 파일 → `[]` |
| `sources_from_profile` | `resources/openapi_sources.yaml` 실제 파일 읽어 2건, `spec_url`이 `https://`로 시작 |
| timeout | `session.get` 호출에 `timeout=30` 전달 |
| Task 3 미변경 | `git diff src/repository/confluence_repository.py` 비어 있음 |
| 구현이 명세와 일치 | 인터페이스·재시도 표 대조 |

## 완료 기준

- [x] `test/test_openapi_repository.py` 6 PASSED (Validator 추가 후 26 passed)
- [x] 전체 green (116 passed), 소켓 차단 상태 통과
- [x] 429/5xx 3회·백오프 `[1, 2]`, 404·400 무재시도, `RequestException` 재시도
- [x] JSON → YAML 폴백, 잘못된 형식·dict 아닌 결과(JSON/YAML 모두, 빈 문자열 포함)는 `OpenApiFetchError`, 재시도 없이 1회 호출
- [x] `sources_from_profile()`이 실제 yaml에서 2건 반환, 요청 미발생
- [x] `src/repository/confluence_repository.py` 변경 없음 (`IDENTICAL`)
- [x] 구현이 이 문서의 인터페이스와 일치 (`_parse`는 리드 결정 코드와 문자열 일치)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. **`sources:` 키만 있고 값이 비어 있는 yaml → `TypeError`** `[검증]`: `yaml.safe_load`가 `{"sources": None}`을 주고 `data.get("sources", [])`가 `None`을 반환. 실사용 시나리오(소스를 전부 주석 처리)에 해당하므로 **수정 대상으로 확정**한다 — `[]` 반환이 맞다. 다만 사용자 지시(Task 5 후 대기)에 따라 지금 Builder에게 보내지 않고 **Task 5 후속 수정(5-F)**로 등록해 재개 시 Task 6 이전에 처리한다.
2. **`yaml.safe_load`가 `YAMLError` 외 예외를 낼 때 감싸지 않음** — 명세 표 밖이고 실제 스펙 응답에서 발생 가능성이 낮다. 변경 없음.

## Task 5 후속 수정 (재개 시 Builder — Task 6 지시 전에 처리. Task 8과 무관)

**5-F. `load_sources`의 `sources: None` 처리** — `src/repository/openapi_repository.py` `load_sources`에서 `data.get("sources", [])` → `data.get("sources") or []`. 이 한 곳만 변경. Validator는 `"sources:\n"` 파일 입력 → `[]` 반환 테스트를 추가한다. 완료 기준: 해당 테스트 PASS, 전체 green.

## 판정

**READY FOR REVIEW** (2026-09-21, 검증 회차 1). 모든 완료 기준 통과, 전체 116 passed, 설계 문서와 구현 일치. Task 5 후속 수정(5-F)은 완료 기준 밖의 개선이며 READY FOR REVIEW 판정에 영향을 주지 않는다.
→ **리뷰 1 통과 (2026-09-21) — 커밋 대기.** 리드 결정(`_parse`)은 리뷰에서 타당성 재확인됨.

커밋 대상(사용자 수행): `src/repository/openapi_repository.py`, `test/test_openapi_repository.py`.

**계획서 재유입 주의**: 상위 계획 Task 5 Step 3 `_parse`는 수정 전 구조(dict 검사가 YAML 분기에만)로 남아 있다. 동기화는 사용자 결정.

## 범위 제외

- 스펙 → Document 렌더링 (Task 4)
- 인증이 필요한 스펙 URL (팀 QA 서비스 `openapi.json`은 공개)
- 로컬 파일 경로 `spec_url` (`file://`) 지원
- 스펙 캐싱·ETag
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 4 진행 중). Task 4 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 사용자 지시: **Task 5 완료(READY FOR REVIEW) 후 일시 대기.** Task 6 명세 작성·Builder 지시는 사용자의 재개 지시가 있을 때까지 보류한다.
- 2026-09-21 리드: Task 4 READY FOR REVIEW 확인. Builder에게 시작 지시.
- 2026-09-21 Builder 작업 1~5 완료: RED → 6 passed → 전체 96 passed. 생성 `src/repository/openapi_repository.py`, `test/test_openapi_repository.py`. Task 3 미변경. **ESCALATE**: `_parse` JSON 분기에 dict 검사 없음(`[1, 2]`·`123` 통과). 코드 미변경 상태로 판단 요청.
- 2026-09-21 리드: **수정 결정(a)**, 명세 "데이터 흐름" 정정, 작업 7 추가. Builder에게 지시.
- 2026-09-21 Builder 작업 7 완료: `_parse`만 교체(명세 코드와 동일, 예외 메시지 유지). 6 passed / 전체 96 passed. 동작 확인: `'[1, 2]'`·`'123'`·`'- a'` → 형식 오류, `'a: [b'` → 파싱 실패, 정상 JSON/YAML object → dict 반환.
- 2026-09-21 리드: diff가 명세 교체 코드와 일치함을 확인. Validator에게 검증 지시.
- 2026-09-21 Validator 회차 1: 완료 기준 전부 PASS, 116 passed(소켓 차단 포함). 추가 테스트 +20. 발견 버그 없음. 비차단 의견 2건(위 절).
- 2026-09-21 리드: READY FOR REVIEW 선언. 비차단 1번은 Task 5 후속 수정(5-F)로 등록(재개 시 처리). **사용자 지시에 따라 대기 진입.**
- 2026-09-21 사용자 재개 지시("6 진행"). 리드: 5-F를 Builder에게 지시(Task 6과 병행, 파일 겹침 없음).
- 2026-09-21 Builder 5-F 완료: `data.get("sources") or []` 한 줄. 26 passed / 전체 119 passed. 경계 확인: `sources:` 빈 값 → `[]`(TypeError 해소), 빈 파일·키 없음·정상 1건 기존 동작 유지.
- 2026-09-21 리드: diff 확인. Validator에게 5-F 테스트 추가·검증 지시.
- 2026-09-21 Validator 5-F 검증: PASS. 테스트 +2(`sources:` 빈 값, `sources: []`). 변경 범위 한 줄 확인(계획서 대비 diff). `test_openapi_repository.py` 28 passed. **5-F 종결.**
