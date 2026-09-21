# 리뷰 1: Task 1~5 코드 리뷰 결과와 조치

- 일자: 2026-09-21
- 대상: Task 1~5 READY FOR REVIEW 산출물 (전체 116 passed 기준선)
- 방식: 리드 지시로 읽기 전용 리뷰 에이전트가 5개 관점(metadata 계약, 리드 결정 2곳, 비차단 판단 재검토, 테스트 품질, 코드) 리뷰. 리드가 should-fix 항목을 직접 재확인한 뒤 결정.

## 요약

- blocker: 없음
- should-fix 3건 → 이 문서의 조치 A·B로 처리(코드 1줄 + 테스트 정리). 1건은 Task 8로 이관.
- nit/info: 기록만. 아래 "변경하지 않는 항목" 참조.
- Document metadata 계약 `[검증]`: Task 6/8/9/10이 필수로 읽는 키는 `doc_id`·`source`·`chunk_id`(Task 6 생성)뿐이고 나머지는 `.get` + 기본값. 소스별 키 차이로 인한 KeyError 지점 없음. doc_id 충돌 없음. **계약 변경 불필요.**
- 리드 결정 2곳(Task 4 `:74`, Task 5 `_parse`) `[검증]`: 리뷰어가 코드 추적·실행으로 타당성 재확인, 부작용 없음.

## 조치 A (Builder): body-only 매크로의 `ac:parameter` 텍스트 누출 수정

**발견** `[검증]`(리뷰어 `python -c` 재현, 리드 코드 확인): `confluence_document_service.py` `_preprocess_macros`의 body-only 분기(`info`/`expand`/`panel` 등)는 `rich-text-body`와 매크로를 `unwrap`만 하므로 형제 `<ac:parameter ac:name="title">주의 제목</ac:parameter>`가 남는다. markdownify `strip=["ac:parameter"]`는 **태그만 제거하고 텍스트는 유지**하므로 `'주의 제목\n\n본문'`처럼 파라미터 값이 본문에 섞인다. Task 2 명세 매크로 표 "rich-text-body 내용만 남기고 껍데기 제거"와 불일치.

**결정: 코드 수정.** 파라미터 텍스트(`title`, `icon`, `bgColor` 등)는 대부분 검색 노이즈(`더보기`, `#FFFFFF`)이고, 명세 규칙과 구현을 일치시키는 것이 우선. `expand` 제목 등 의미 있는 파라미터가 검색 품질에 필요하다고 판단되면 Task 13 평가 후 별도 티켓으로 재검토한다.

**변경** — `src/service/confluence_document_service.py` body-only 분기(`elif name in _BODY_ONLY_MACROS:`)에서 `body.unwrap()` 전에 매크로 직속 `ac:parameter`를 제거:
```python
elif name in _BODY_ONLY_MACROS:
    body = macro.find("ac:rich-text-body")
    if body:
        # title 등 파라미터 값이 본문 텍스트로 새지 않도록 제거한다
        for param in macro.find_all("ac:parameter", recursive=False):
            param.decompose()
        body.unwrap()
        macro.unwrap()
    else:
        macro.decompose()
```
이 분기 외 변경 금지. 기존 테스트 21개 영향 없어야 함.

**완료 기준**: `pytest --active-profile=local test/test_confluence_document_service.py -v` 전부 PASS(Validator 추가분 포함), 전체 green. Validator가 `info(title=…)`·`expand(title=…)` 입력에서 제목 텍스트가 결과에 없고 본문은 남는지 테스트 추가.

## 조치 B (Validator): `test/test_global_logger.py` 정리

**발견** `[검증]`(리드 파일 확인):
1. `test_get_logger_writes_message_to_file`(28~45행) — 테스트가 **자기 FileHandler를 직접 부착**해 기록을 확인하므로 `GlobalLogger`의 파일 기록 동작을 검증하지 않는다. 이름과 검증 내용 불일치.
2. `test_get_logger_uses_profile_log_dir_by_default`(61~69행) — 프로젝트 실제 `logs/` 디렉터리를 `shutil.rmtree`한다. 테스트가 작업 트리를 파괴적으로 건드림.

**배경** `[검증]`(리뷰어): pytest logging 플러그인이 수집 단계부터 root 로거에 `LogCaptureHandler`를 부착하므로, 테스트 실행 중 `GlobalLogger.get_logger()`의 `logging.basicConfig`는 **항상 no-op**이다. `logs/app.log`는 `FileHandler` 생성자의 파일 열기 부작용으로만 생성되고 핸들러는 부착되지 않는다. 즉 현재 테스트로 "파일 기록"은 검증 불가.

**결정**:
- 1번 테스트 **삭제**. 실제 기록 검증은 프로덕션 수정(아래 이관)과 함께 Task 8에서 한다.
- 2번 테스트 **삭제**. 파일 생성 경로는 `test_get_logger_creates_log_file`(tmp_path 사용)이 이미 검증한다.
- `_reset_configured_flag`의 name-mangled 속성 접근(11행)은 1회성 플래그를 되돌릴 다른 수단이 없으므로 **유지**(nit 수용).

**완료 기준**: 파일에 `test_get_logger_creates_log_file`, `test_get_logger_is_idempotent` 2개만 남고 PASS. `shutil` import 제거. 전체 green.

## Task 8로 이관: `GlobalLogger` 파일 기록이 실제로 동작하는지

`[검증]` root 로거에 핸들러가 이미 있으면 `basicConfig`가 무시되어 `logs/app.log`에 기록되지 않는다(Task 1 비차단 3번). 리뷰에서 추가 확인된 사실: pytest 환경에서는 항상 no-op. `[미확인]` uvicorn 기본 로깅 설정이 root에 핸들러를 붙이는지.

**결정**: 프로덕션 수정은 **Task 8(인제스트 CLI)** 명세에 포함한다 — `ingest.py`가 사용자가 처음 실행하는 진입점이고, 로그 파일이 실제로 필요해지는 시점이다(기존 Task 11 이관을 Task 8로 앞당김). Task 8 완료 기준에 추가할 항목:
- `python ingest.py --active-profile=local ...` 실행 시 `logs/app.log`에 INFO 로그가 기록된다(수동 확인 또는 subprocess 테스트).
- 수정 방식 후보: `basicConfig(..., force=True)` 또는 root 핸들러 직접 부착. pytest의 caplog와 충돌하지 않는 쪽을 Task 8 명세에서 확정.
Task 11에서는 uvicorn 기동 경로만 추가 확인.

## 변경하지 않는 항목 (기록)

| # | 항목 | 심각도 | 판단 |
|---|---|---|---|
| 1 | `confluence_document_service.py:94,103` `body`/`_links` 명시적 `null` → `AttributeError`, `webui` null → `"...None"` url | nit | `[미확인]` Confluence v2 실응답에서 null 여부. Task 9 실데이터 연동 시 드러나면 처리(Task 2 비차단 판단과 동일 기준) |
| 2 | `confluence_repository.py:59` 200이지만 JSON 아닌 응답이 raw `JSONDecodeError` 전파 | nit | 명세 표 밖. Confluence API가 200에 non-JSON을 줄 시나리오 없음 |
| 3 | `openapi_repository.py` 최상위가 리스트인 yaml → `AttributeError` | nit | 잘못된 설정 파일은 예외로 드러나는 것이 맞음. Task 5 후속 수정(5-F)(`sources: None` → `[]`)만 처리 |
| 4 | `openapi_document_service.py:42` `_type_label`의 `seen` 파라미터 미사용 | nit | 참조 구현 그대로. 재귀 시그니처 통일 목적. 변경 이득 없음 |
| 5 | `openapi_document_service.py:51` OpenAPI 3.1 `type: ["string","null"]` 배열 라벨 | nit | `[추측]` FastAPI 생성 스펙은 `anyOf` 사용. Task 9 실데이터에서 확인 |
| 6 | `openapi_document_service.py:58` `depth > _MAX_DEPTH` 분기 도달 불가 | info | 해롭지 않음. 직접 호출 방어 |
| 7 | `.rstrip(" —")`가 summary 끝 `—`/공백도 제거 | info | 실질 영향 없음 |
| 8 | metadata 키 집합 완전 일치 assert (test 2건) | info | 계약 고정 목적으로 의도됨. 유지 |
| 9 | markdownify 출력 `==` 비교 (test 4건) | nit | 버전 업 시 깨질 수 있으나 현재 고정 버전. 유지 |
| 10 | Chroma 빈 문자열 metadata 허용 | info | `[미확인]` 리뷰어 환경에서 chromadb 초기화 hang. Task 7 Validator가 실제 upsert로 확인 |
| 11 | responses `$ref`(`#/components/responses/…`) 경로 테스트 부재 | nit | Validator가 조치 B와 함께 테스트 1개 추가해도 좋음(선택) |
| 12 | OpenAPI 문서 `url`이 endpoint별이 아닌 서비스 `docs_url` | 설계 관찰 | 스펙 결정 사항. Swagger `#/{tag}/{operationId}` 앵커로 개선 가능. Task 10 이후 사용자 판단 |

## 진행 기록

- 2026-09-21 리드: 리뷰 결과 수신, should-fix 3건 재확인. 조치 A → Builder, 조치 B → Validator 지시. GlobalLogger 프로덕션 수정은 Task 8로 이관.
- 2026-09-21 Builder 조치 A 완료: body-only 분기에 `+3`줄(명세 블록과 동일). 21 passed / 전체 116 passed. 동작 확인: `info(title)`·`expand(title)`·`panel(bgColor)` 파라미터 텍스트 제거, 본문 보존, code 매크로 `language` 파라미터 영향 없음(`recursive=False`).
- 2026-09-21 리드: diff 일치 확인. Validator에게 조치 A 검증 지시.
- 2026-09-21 Validator 조치 B 완료: `test_global_logger.py` 테스트 2건 삭제·`shutil` import 제거, 남은 2건 PASS. 조치 A 검증: 변경 +3줄 한정 확인, 추가 테스트 4건(title/expand/panel 파라미터 제거, 중첩 code 매크로 `language` 보존) PASS. 선택 항목 11(responses `$ref`) 테스트 1건 추가. **전체 119 passed**, 소켓 차단 119 passed. 결함·비차단 의견 없음.
- 2026-09-21 리드: **리뷰 1 종결.** Task 1~5 READY FOR REVIEW 유지(Task 2는 조치 A 반영본 기준). 사용자 지시에 따라 대기.

## 종결 상태 (재개 시 기준선)

- 전체 119 passed (소켓 차단 포함)
- 미커밋: Task 1~5 산출물 + 리뷰 1 변경분(`src/service/confluence_document_service.py` +3줄, `test/test_global_logger.py`, `test/test_confluence_document_service.py`, `test/test_openapi_document_service.py`) + `docs/plans/` 전체
- 재개 시 순서: Task 5 후속 수정(5-F)(`load_sources` `or []`, Task 5 문서) → Task 6 명세 → Task 8 명세에 GlobalLogger 프로덕션 수정 포함
