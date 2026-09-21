# Task 3: Confluence REST v2 저장소 (인증·페이지네이션·재시도)

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 3
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 선행: Task 1 (`Profile`, `GlobalLogger`) — READY FOR REVIEW. Task 2 산출물(`build_documents` 입력 형식)과 계약을 맞춘다.
- 상태: **신규 구현 — Builder 시작 대기**

## 목표

Confluence Cloud REST API v2로 `KUDOS` 스페이스의 현재(`status=current`) 페이지 전체를 storage 본문 포함으로 가져온다. 인증 실패는 즉시 중단, 일시 오류는 제한 재시도, 커서 페이지네이션을 따른다.

## 설계

### 컴포넌트

`src/repository/confluence_repository.py` 단일 모듈 + `src/repository/__init__.py`(빈 파일).

외부 의존: `requests`(이미 `requirements.in`에 있음). 내부 의존: `Profile`, `GlobalLogger`.

### 데이터 흐름

```
from_profile()  ──► Profile().get_config("confluence") + env CONFLUENCE_API_TOKEN
       │
fetch_pages()
  └─ fetch_space_id()   GET {base}/api/v2/spaces?keys={space_key}   → results[0].id
  └─ GET {base}/api/v2/spaces/{id}/pages?status=current&body-format=storage&limit=250
  └─ _links.next ("/wiki/api/v2/...") 가 있으면 {site_root}{next} 로 반복 (params=None)
  └─ results 누적 → list[dict]  (Task 2 build_documents 입력)
```

`_get(url, params)` 공통 처리:

| 상황 | 동작 |
|---|---|
| 200 | `response.json()` 반환 |
| 401, 403 | 즉시 `ConfluenceAuthError` (재시도 없음). 메시지에 `CONFLUENCE_API_TOKEN`·`[confluence] email` 확인 안내 |
| 429, 500, 502, 503, 504 | 최대 3회 시도. 시도 간 `sleep(2 ** (attempt-1))` (1s, 2s) |
| 그 외 4xx/5xx (404 등) | 재시도 없이 즉시 루프 종료 → `ConfluenceFetchError` |
| `requests.RequestException` | 재시도 대상 (3회) |
| 3회 소진 | `ConfluenceFetchError` (마지막 상태 포함) |

### 인터페이스 (Produces)

```python
class ConfluenceAuthError(Exception): ...
class ConfluenceFetchError(Exception): ...

class ConfluenceRepository:
    def __init__(self, base_url: str, space_key: str, email: str, api_token: str,
                 session=None, sleep=time.sleep):
        # base_url 은 끝 '/' 제거. base_url 이 '/wiki' 로 끝나면 site_root = base_url[:-5]
        # session 미지정 시 requests.Session(); session.auth = (email, api_token)
        # public 속성: base_url, space_key, email, api_token
    @classmethod
    def from_profile(cls) -> "ConfluenceRepository":
        # [confluence] base-url, space-key, email. 토큰은 env CONFLUENCE_API_TOKEN 우선, 없으면 api-token
    def fetch_space_id(self) -> str
    def fetch_pages(self) -> list[dict]
```

상수: `_PAGE_LIMIT = 250`, `_MAX_ATTEMPTS = 3`, `_TIMEOUT_SEC = 30`, `_RETRY_STATUS = {429, 500, 502, 503, 504}`.

`session.get(url, params=..., timeout=...)` 시그니처만 사용한다(테스트의 FakeSession과 계약).

### Consumes

- `Profile().get_config("confluence")` → `base-url`, `space-key`, `email`, `api-token` (Task 1)
- `GlobalLogger.get_logger(__name__)` (Task 1)

### 기각한 대안

- `atlassian-python-api` 라이브러리: 새 의존성이고 v2 커서 페이지네이션 지원이 불명확. `requests` 직접 호출로 충분.
- `urllib3.Retry` 어댑터: 429/5xx 재시도는 가능하지만 401 즉시 실패 메시지, 테스트용 `sleep` 주입이 어려움. 수동 루프 채택.
- REST v1 `content?expand=body.storage`: v2가 현행 API이고 스펙에서 v2로 확정.

## 작업 목록 (Builder)

상위 계획 Task 3의 Step 1~4 순서를 따른다. **코드 작성 규칙은 `docs/plans/conventions.md`를 따른다** — 계획서 Step 3 코드는 참조 구현이며, 이 문서의 인터페이스·`_get` 동작 표·테스트를 지키는 범위에서 더 간결하게 작성해도 된다.

1. `test/test_confluence_repository.py` 작성 — 상위 계획 Task 3 Step 1 코드 그대로 (7개 테스트). 테스트는 계약이므로 변경하지 않는다.
2. `pytest --active-profile=local test/test_confluence_repository.py -v` → `ModuleNotFoundError`로 실패 확인.
3. `src/repository/__init__.py`(빈 파일), `src/repository/confluence_repository.py` 작성 — 상위 계획 Task 3 Step 3을 참조 구현으로 삼되 간결화 가능.
4. 같은 명령 → 7 PASSED 확인.
5. `pytest --active-profile=local -v` 전체 실행 → 회귀 없음(기존 38 + 7 = 45 passed 기대).
6. 완료 보고: 실행 명령·결과, 생성 파일 목록, **참조 구현과 다르게 작성한 점**(없으면 "없음").

**하지 않을 것:** 커밋, `resources/config_local.ini` 수정(토큰 값 기입 금지), 실제 Confluence 호출, 다른 모듈 생성.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 7개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_confluence_repository.py -v` |
| 회귀 없음 | `pytest --active-profile=local -v` 전체 green |
| 네트워크 비의존 | 소켓 차단 상태에서 통과. `from_profile()`은 세션만 만들고 요청하지 않아야 함 |
| 401/403 즉시 실패 | `test_auth_error_raises_immediately` + 403 케이스 추가 확인, `sleep` 호출 0회 |
| 재시도 정책 | 429→503→200 성공(`test_retries_on_429_then_succeeds`), 500×3 실패, `sleep` 인자가 `[1, 2]`인지 기록용 sleep으로 확인 |
| 404는 재시도 없음 | 404 1회 후 `ConfluenceFetchError`, 호출 1회 |
| `RequestException` 재시도 | `session.get`이 `requests.ConnectionError`를 raise → 3회 시도 후 `ConfluenceFetchError` |
| 커서 페이지네이션 | `test_fetch_pages_follows_cursor`: 2번째 호출 URL이 `https://ihunet.atlassian.net/wiki/api/v2/...`(중복 `/wiki` 없음), `params=None` |
| 첫 요청 params | `{"status": "current", "body-format": "storage", "limit": 250}` |
| 환경변수 토큰 우선 | `test_from_profile_prefers_env_token`; 환경변수 미설정 시 ini `api-token`(빈 문자열) 사용 확인 |
| base_url 정규화 | 끝 `/` 있는 base_url 입력 → `base_url`에 `/` 없음, `/wiki` 아닌 base_url → `site_root == base_url` |
| 인증 정보 미커밋 | `resources/config_local.ini`의 `api-token=` 여전히 빈 값, `git diff resources/` 없음 |
| 구현이 명세와 일치 | "인터페이스"·"`_get` 표"와 코드 대조 |

## 완료 기준

- [x] `test/test_confluence_repository.py` 7 PASSED (Validator 추가 후 25 passed)
- [x] 전체 `pytest --active-profile=local` green (63 passed)
- [x] 소켓 차단 상태에서 통과. `from_profile()`은 요청 없음
- [x] 401/403 → `ConfluenceAuthError` 즉시(1회 호출, sleep 없음)
- [x] 429/5xx → 최대 3회, 백오프 `[1, 2]`; 404·400 → 재시도 없음; `RequestException` 3회 재시도
- [x] `_links.next` 처리 시 `/wiki` 중복 없음, `params=None`
- [x] `CONFLUENCE_API_TOKEN` 환경변수 우선, 미설정 시 ini 폴백
- [x] `resources/` 변경 없음
- [x] 구현이 이 문서의 인터페이스와 일치 (계획서 Step 1 테스트 미수정 `IDENTICAL`)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. **env `CONFLUENCE_API_TOKEN`이 빈 문자열이면 ini로 폴백** — 의도된 동작으로 확정. 빈 env는 미설정과 동일 취급. 변경 없음.
2. **모듈 import 시 `logs/app.log` 생성** — Task 1 합의 동작. 진입점 로깅 구성 순서는 Task 11 완료 기준으로 이관(Task 1 문서 판단 3과 동일).
3. **`_links.next` 순환 시 무한 루프 가능** — `[추측]` Confluence 커서 페이지네이션은 단조 진행이라 발생하지 않을 것으로 본다. 명세 동작 표 밖의 방어이므로 추가하지 않는다(§4 불가능한 상황 방어 금지). Task 9 실데이터 인제스트에서 수집 건수 로그로 이상 여부를 확인한다.

## 판정

**READY FOR REVIEW** (2026-09-21, 검증 회차 1). 모든 완료 기준 통과, 전체 63 passed, 설계 문서와 구현 일치.
→ **리뷰 1 통과 (2026-09-21) — 커밋 대기.**

커밋 대상(사용자 수행): `src/repository/__init__.py`, `src/repository/confluence_repository.py`, `test/test_confluence_repository.py`.

## 범위 제외

- 페이지 본문 → Markdown 변환 (Task 2에서 완료)
- 첨부파일·댓글·라벨 수집
- 증분 수집(`version` 비교) — Task 8·9(manifest, ingest_service)에서 처리
- 실제 Confluence 연동 통합 테스트 — 토큰 필요. Task 9 이후 `@pytest.mark.integration`으로 별도 검토
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 작성. Builder에게 시작 지시.
- 2026-09-21 리드: 사용자 요청으로 코드 간결화 허용 규칙(`docs/plans/conventions.md`) 추가, 작업 목록 3·6 수정. Builder에게 재안내.
- 2026-09-21 Builder 완료 보고: RED(`ModuleNotFoundError`) → 7 passed → 전체 45 passed(기대치 38+7 일치). 생성: `src/repository/__init__.py`, `src/repository/confluence_repository.py`, `test/test_confluence_repository.py`. `resources/` 변경 없음. 참조 구현과 다른 점 없음 — `try/except/else`·`last_status`는 동작 표(RequestException 재시도, 마지막 상태 포함)가 요구하므로 간결화 지점 없다고 판단.
- 2026-09-21 리드: 구현을 명세 인터페이스·`_get` 동작 표와 대조해 일치 확인(`[검증]`). Builder의 "간결화 지점 없음" 판단 수용 — 간결화는 허용이지 의무가 아니며(conventions.md §1), 동작 표를 만족하는 최소 구조로 판단. Validator에게 검증 지시.
- 2026-09-21 Validator 회차 1: 완료 기준 전부 PASS. `test/test_confluence_repository.py` +18(append만). 발견 버그 없음. 비차단 의견 3건(위 절).
- 2026-09-21 리드: READY FOR REVIEW 선언. Task 4 명세 작성으로 이동.
