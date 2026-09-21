# Task 1: 프로젝트 골격 (Profile, 인자, 로거, 설정 파일, pytest)

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 1
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 상태: **구현 완료·커밋됨(`6b5295b`) — 검증만 남음**

## 목표

`--active-profile` 인자로 `resources/config_{profile}.ini`를 읽는 `Profile` 싱글톤, 로거 팩토리, pytest 구성을 갖춰 이후 Task가 설정값과 로거를 한 곳에서 가져오게 한다.

## 리드 판단 (2026-09-21)

`[검증]` 아래 파일이 모두 존재하고 내용이 상위 계획 Task 1 Step 3 코드와 동일하다. git 커밋 `6b5295b`에 포함돼 있다.

- `global_variable.py`
- `src/__init__.py`, `src/config/__init__.py`, `src/config/argument.py`, `src/config/profile.py`
- `src/library/__init__.py`, `src/library/global_logger.py`
- `resources/config_local.ini`, `resources/openapi_sources.yaml`
- `pytest.ini`, `test/__init__.py`, `test/conftest.py`, `test/test_profile.py`

`[미확인]` 테스트 실행 결과(green 여부)는 리드가 직접 확인하지 못했다.

**결정:** Builder 작업은 없다. Validator가 아래 검증 전략을 수행하고 결과를 보고한다. Builder를 거치지 않는 이유: 구현이 이미 존재하고 설계와 일치하므로 재구현/수정할 항목이 없다. 검증에서 결함이 나오면 그때 Builder 작업 명세를 이 문서에 추가한다.

## 설계

### 컴포넌트

| 파일 | 책임 |
|---|---|
| `global_variable.py` | `PROJECT_ROOT_DIR`, `PROJECT_RESOURCE_DIR` (경로 구분자 `/`로 정규화) |
| `src/config/argument.py` | `CommandlineArgument` 싱글톤. `parse_known_args`로 `--active-profile`만 파싱, 나머지(pytest/uvicorn 인자) 무시 |
| `src/config/profile.py` | `Profile` 싱글톤. `configparser(interpolation=None, inline_comment_prefixes=(";",))`, `{project_root}` 치환 |
| `src/library/global_logger.py` | `GlobalLogger.get_logger(name)`. 최초 호출 시 `basicConfig` 1회, `logs/app.log` + stdout |
| `resources/config_local.ini` | spec §9 설정값. 인증 정보(`email`, `api-token`)는 빈 값 |
| `resources/openapi_sources.yaml` | OpenAPI 소스 2건 |
| `pytest.ini` / `test/conftest.py` | `--active-profile` 옵션 등록, `integration` 마커 기본 제외 |

### 인터페이스 (Produces)

```python
global_variable.PROJECT_ROOT_DIR: str
global_variable.PROJECT_RESOURCE_DIR: str

CommandlineArgument().get_active_profile() -> str

Profile().active_profile: str
Profile().api_root: str
Profile().get_config(section: str) -> dict[str, str]   # {project_root} 치환 완료
Profile().get_common_config() -> dict[str, str]
Profile.get_value(config: dict, key: str, default=None)

GlobalLogger.get_logger(name: str) -> logging.Logger
```

### 데이터 흐름

`sys.argv` → `CommandlineArgument` → `Profile.__init__`이 `resources/config_{profile}.ini` 로드 → 섹션 dict 반환. `GlobalLogger`는 `Profile().get_common_config()`의 `log-level`, `log-file-path`를 읽는다.

### 기각한 대안

- pydantic-settings / 환경변수 기반 설정: 팀 컨벤션(`ailab_general_chatbot`의 Profile 싱글톤·ini)과 다르므로 기각.

## 작업 목록

1. (Validator) `pytest --active-profile=local test/test_profile.py -v` 실행, 4 PASSED 확인.
2. (Validator) `pytest --active-profile=local -v` 전체 실행. Task 2 테스트가 함께 수집되므로 Task 1 테스트 결과만 이 티켓의 판정에 사용하고, 나머지 결과는 참고로 보고.
3. (Validator) 아래 완료 기준을 하나씩 체크해 보고.

## 검증 전략

| 완료 기준 | 검증 방법 |
|---|---|
| Profile 4개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_profile.py -v` |
| 다른 프로파일 인자가 반영됨 | `pytest --active-profile=local` 로 실행했을 때 `Profile().active_profile == "local"` (test_active_profile_is_local) |
| 단위 테스트가 Ollama·네트워크 없이 통과 | 위 테스트를 Ollama 미기동 상태로 실행해도 통과 |
| `integration` 마커 기본 제외 | `pytest --markers` 출력에 `integration` 존재, `pytest.ini`의 `addopts = -m "not integration"` 확인 |
| 설정값이 spec §9와 일치 | `resources/config_local.ini` 값과 상위 계획 Task 1 Step 3의 ini 내용을 대조 (리드 `[검증]` 일치) |
| 인증 정보 미커밋 | `resources/config_local.ini`의 `email=`, `api-token=`이 빈 값 |
| 로거가 파일·콘솔에 출력 | Python REPL 또는 임시 스크립트로 `GlobalLogger.get_logger("t").info("x")` 실행 후 `logs/app.log` 생성 확인. 생성된 `logs/`는 커밋 대상 아님 (`.gitignore` 여부 보고) |

## 완료 기준

- [x] `test/test_profile.py` 4 PASSED (Validator 추가 후 13 passed)
- [x] Ollama·네트워크 없이 통과 (소켓 전면 차단 상태에서 통과)
- [x] `pytest.ini`에 `integration` 마커와 `-m "not integration"` 존재 (임시 integration 테스트로 deselect 확인)
- [x] `config_local.ini`가 상위 계획 Task 1 Step 3 값과 일치, 인증 정보 빈 값
- [x] `GlobalLogger.get_logger()` 호출 시 `logs/app.log` 생성, 예외 없음. `.gitignore`에 `logs/` 존재
- [x] 구현이 이 문서의 인터페이스와 일치

## 범위 제외

- `config_dev.ini`, `config_prod.ini` 등 다른 프로파일 파일 (사내 서버 이전 시 별도 Task)
- 로그 로테이션, 구조화 로깅
- 설정값 타입 변환(`int()`, `float()`)은 각 사용처(Task 6~) 책임
- 커밋: 이미 사용자가 수행함. 추가 커밋 필요 시 사용자가 직접 한다.

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. **설계 스펙 §9 ini에 `[chroma] manifest-path`가 없음** — `[검증]` 상위 계획(커밋 `6c8867b` 재검토 반영)과 실제 ini에는 있다. 계획·ini가 최신이며 Task 8(manifest)에서 사용한다. 스펙 §9 문서 동기화는 코드에 영향 없는 문서 정리이므로 사용자에게 별도 안내하고 이 티켓에서는 처리하지 않는다(리드 쓰기 영역은 `docs/plans/`만).
2. **스펙 §9의 `api-token=  ; 환경변수 우선` 인라인 주석 누락** — 값은 동일. 환경변수 우선 로직은 Task 3 명세에 인터페이스로 명시하므로 ini 주석은 불필요. 변경 없음.
3. **`GlobalLogger`가 root 로거에 핸들러가 이미 있으면 `basicConfig`가 no-op** — `[검증]` 재현됨. Task 1 완료 기준에는 영향 없음. ~~uvicorn과의 상호작용은 Task 11(`main.py`) 검증 항목으로 이관한다.~~ **리뷰 1(2026-09-21)에서 Task 8로 앞당김**: pytest 환경에서는 항상 no-op이라 현재 테스트로 파일 기록을 검증할 수 없음이 확인됨. `ingest.py`(Task 8)가 첫 실사용 진입점이므로 Task 8 명세에서 프로덕션 수정과 실기록 확인을 완료 기준에 포함한다. 상세: `docs/plans/review-01-task1-5.md`.
4. (Task 2 관련) `int(version.get("number", 0))`의 명시적 `null` TypeError — Task 2 문서에 기록.

## 판정

**READY FOR REVIEW** (2026-09-21, 검증 회차 1). 모든 완료 기준 통과, 전체 테스트 green(38 passed), 설계 문서와 구현 일치.
→ **리뷰 1 통과 (2026-09-21) — 커밋 대기.** 상세: `review-01-task1-5.md`

## 진행 기록

- 2026-09-21 리드: 구현·커밋 완료 상태 확인. Validator에게 검증 요청.
- 2026-09-21 Validator 회차 1: 완료 기준 전부 PASS. 테스트 추가 — `test/test_profile.py` +9, `test/test_global_logger.py` 신규 4. 발견 버그 없음. 비차단 의견 3건(위 절).
- 2026-09-21 리드: READY FOR REVIEW 선언. Validator가 추가한 테스트 파일은 사용자가 커밋할 때 포함.
