# Task 8: manifest 증분 갱신, 인제스트 서비스, CLI (+ GlobalLogger 파일 기록 수정)

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 8
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 2~7 전부. 리뷰 1(`review-01-task1-5.md`)에서 이관된 GlobalLogger 수정 포함.
- 상태: **신규 구현 — Builder 진행 중** (Task 7 Validator 검증과 병행, 2026-09-21 지시)

## 목표

소스(confluence/openapi)별로 문서를 수집 → 청킹 → Chroma에 **증분** 저장한다. `data/manifest.json`에 문서별 fingerprint와 chunk_id 목록을 기록해 다음 실행에서 추가·변경·삭제만 처리한다. `ingest.py` CLI가 진입점이며, 이 시점에 `logs/app.log`에 실제로 로그가 기록되어야 한다.

## 설계

### 컴포넌트

| 파일 | 책임 |
|---|---|
| `src/service/manifest.py` | `Manifest`(JSON 읽기/쓰기), `IngestDiff`, `compute_diff` |
| `src/service/ingest_service.py` | `IngestService` 오케스트레이션, `confluence_fingerprint`, `openapi_fingerprint`, `IngestSummary` |
| `ingest.py` | CLI 진입점 (`--active-profile`, `--source all\|confluence\|openapi`, `--full`) |
| `src/library/global_logger.py` | **수정** — 리드 결정 1 |
| `test/test_manifest.py`, `test/test_ingest_service.py` | 단위 테스트(가짜 임베딩, tmp_path) |
| `test/test_global_logger.py` | **수정** — 실제 파일 기록 검증 테스트로 교체(Validator) |

### 데이터 흐름

```
ingest.py main()
  ├─ Profile: [retrieval] chunk-size/chunk-overlap, [chroma] manifest-path, [confluence] base-url
  ├─ VectorStoreRepository.from_profile()  (실제 OllamaEmbeddings)
  ├─ Manifest(manifest-path)
  ├─ --full → IngestService.reset_all()  (컬렉션 삭제·재생성 + manifest 비움)
  ├─ confluence → ConfluenceRepository.from_profile().fetch_pages()
  │               → build_documents(pages, base_url) → fingerprint = str(version)
  │               → ingest_documents("confluence", docs, fps)
  └─ openapi → 소스별 fetch_spec (실패 소스는 기록 후 건너뜀)
              → build_documents(spec, source) → fingerprint = sha256(page_content)
              → ingest_documents("openapi", docs, fps, removable=성공 소스의 doc_id만)

ingest_documents(source, docs, fps, removable)
  ├─ compute_diff(manifest, source, fps, removable) → added/changed/removed/unchanged
  ├─ removed: store.delete(옛 chunk_ids) → manifest.remove
  ├─ changed+added: 옛 chunk_ids delete → split_documents → store.upsert → manifest.set → manifest.save (문서마다)
  └─ IngestSummary 로그·반환
```

**증분 규칙**:
- confluence fingerprint = `str(metadata.version)`. 페이지 버전이 오르면 변경으로 감지.
- openapi fingerprint = `sha256(page_content)`. 렌더 결과가 같으면 변경 없음.
- 삭제 판정은 `manifest.doc_ids_for_source(source)` 중 이번 수집에 없는 것. openapi는 **수집 성공한 서비스의 doc_id만** 삭제 대상(`removable`) — 한 서비스 다운로드 실패 시 그 서비스 문서가 통째로 지워지는 것을 방지.
- manifest는 **문서 단위 저장 성공 후** 갱신·저장 → 중간 실패 시 다음 실행에서 해당 문서만 재시도.

### 인터페이스 (Produces)

```python
# manifest.py
class Manifest:
    def __init__(self, path: str)            # 없으면 entries = {}
    entries: dict[str, dict]                 # doc_id → {"fingerprint", "chunk_ids", "source"}
    def load(self) -> None
    def save(self) -> None                   # 디렉터리 자동 생성, ensure_ascii=False, indent=2
    def get(self, doc_id: str) -> dict | None
    def set(self, doc_id: str, fingerprint: str, chunk_ids: list[str], source: str) -> None
    def remove(self, doc_id: str) -> None
    def doc_ids_for_source(self, source: str) -> set[str]
    def clear(self) -> None

@dataclass
class IngestDiff: added: list[str]; changed: list[str]; removed: list[str]; unchanged: list[str]
def compute_diff(manifest, source, fingerprints: dict[str, str], removable=lambda _: True) -> IngestDiff
    # removed 는 정렬됨

# ingest_service.py
@dataclass
class IngestSummary: source: str; added: int = 0; changed: int = 0; removed: int = 0;
                     chunk_count: int = 0; failed_sources: list[str] = []
def confluence_fingerprint(doc: Document) -> str
def openapi_fingerprint(doc: Document) -> str
class IngestService:
    def __init__(self, vector_store, manifest, chunk_size: int, chunk_overlap: int)
    def ingest_documents(self, source, docs, fingerprints, removable=lambda _: True) -> IngestSummary
    def ingest_confluence(self, repo: ConfluenceRepository, base_url: str) -> IngestSummary
    def ingest_openapi(self, repo: OpenApiRepository, sources: list[OpenApiSource]) -> IngestSummary
    def reset_all(self) -> None

# ingest.py
def main() -> int   # 0 성공, 1 실패(인증 실패는 즉시 1, 일부 소스 실패도 1)
```

### 리드 결정 1: `GlobalLogger` 파일 기록 수정 (리뷰 1 이관)

**문제** `[검증]`(리뷰 1): `logging.basicConfig`는 root 로거에 핸들러가 하나라도 있으면 no-op. pytest는 수집 단계부터 root에 핸들러를 붙이므로 테스트에서 파일 기록이 검증된 적이 없고, 운영에서도 다른 라이브러리가 먼저 root를 건드리면 `logs/app.log`가 비어 있게 된다.

**결정**: `basicConfig` 대신 **root 로거에 핸들러를 직접 부착**하고, 1회성 플래그 대신 **핸들러 이름으로 중복을 판정**한다.
```python
_STREAM_HANDLER_NAME = "kudos-rag-stream"
_FILE_HANDLER_NAME = "kudos-rag-file"

@classmethod
def get_logger(cls, name: str) -> logging.Logger:
    root = logging.getLogger()
    if not any(h.name == _FILE_HANDLER_NAME for h in root.handlers):
        common = Profile().get_common_config()
        log_dir = common["log-file-path"]
        os.makedirs(log_dir, exist_ok=True)
        formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        stream = logging.StreamHandler(); stream.name = _STREAM_HANDLER_NAME; stream.setFormatter(formatter)
        file = logging.FileHandler(f"{log_dir}/app.log", encoding="utf-8"); file.name = _FILE_HANDLER_NAME; file.setFormatter(formatter)
        root.addHandler(stream); root.addHandler(file)
        root.setLevel(getattr(logging, common.get("log-level", "INFO").upper(), logging.INFO))
    return logging.getLogger(name)
```
- 기존 root 핸들러(pytest, uvicorn 등)를 제거하지 않으므로 `caplog`와 충돌 없음(`force=True` 대안 기각 이유).
- `__configured` 클래스 플래그 제거. Validator의 `_reset_configured_flag` 헬퍼는 "이름이 `kudos-rag-*`인 root 핸들러 제거"로 교체.
- 공개 인터페이스 `GlobalLogger.get_logger(name) -> logging.Logger` 불변. 포맷·레벨·파일 경로 불변.
- 부작용: 테스트 실행 중에도 프로젝트 `logs/app.log`에 로그가 쌓인다(`.gitignore`에 `logs/` 있음 `[검증]`). 수용.

**기각한 대안**: `basicConfig(force=True)` — root의 기존 핸들러를 전부 제거해 pytest 수집 단계 캡처를 깨고, 다른 라이브러리 핸들러도 날린다.

### 리드 결정 2: 실데이터 인제스트 검증 범위

| 검증 | 조건 | 담당 | 실패 시 |
|---|---|---|---|
| 단위 테스트 8개(계획서) + Validator 추가 | 없음(가짜 임베딩) | Builder → Validator | 판정 FAIL |
| `python ingest.py --active-profile=local --source openapi` 실행 → 종료 0, 추가 N / 청크 N, 재실행 시 추가 0 갱신 0 | Ollama 기동 + QA OpenAPI 호스트 접근 | Validator(`@pytest.mark.integration` 아닌 **수동 실행**, 보고서 기록) | 원인 분류(Ollama/네트워크/코드) 후 코드 문제만 RETURN |
| `--source confluence` 실행 | 위 + `CONFLUENCE_API_TOKEN` env + `[confluence] email` | env가 있으면 Validator 실행, 없으면 `[미확인]` 기록 | — |
| 토큰 없이 `--source confluence` → `오류: Confluence 인증 실패(401)…` 종료 1 | Ollama 기동(embeddings 객체 생성은 호출 없음이라 사실 불필요 — 확인 항목) | Validator | 코드 문제면 RETURN |
| `logs/app.log`에 인제스트 로그 기록 | 위 실행 후 | Validator | RETURN |

실행 산출물 `data/chroma/`, `data/manifest.json`은 커밋 대상이 아니다. `[검증]`(Validator) `.gitignore` 5·6행에 `data/`·`logs/` 존재 — 사용자 안내 불필요.

**`data/` 처리 방침**: Validator의 실데이터 인제스트 후 `data/`는 **남긴다** — Task 9 하이브리드 검색 검증에서 실데이터 컬렉션을 재사용한다. Task 7의 "`data/` 오염 없음"은 *단위 테스트가* `data/`를 만들지 않는다는 기준이므로 충돌하지 않는다. 보고서에 "실데이터 인제스트 산출물 존재"를 명시한다.

환경 사전 점검 `[검증]`(Validator): QA OpenAPI 두 호스트 200 응답(21.7KB / 189KB). `CONFLUENCE_API_TOKEN` 미설정 → confluence 정상 경로는 `[미확인]`, 401 종료 1 경로는 확인 가능.

### 기각한 대안

- 매번 전체 재구축(manifest 없음): Confluence 200+ 페이지 임베딩을 매번 수행 → 로컬 bge-m3로 수 분. 증분이 PoC 반복 실행에 필수.
- fingerprint를 confluence도 content hash로: `version`이 API에서 바로 오고 본문 다운로드 전 비교가 가능해 더 싸다. 단 현재 구현은 `body-format=storage`로 본문을 항상 받으므로 절감은 렌더링·청킹·임베딩 단계. 유지.
- manifest를 Chroma metadata에 내장: 문서 단위 조회가 Chroma에서 비효율적이고, 컬렉션 손상 시 manifest도 잃음. 별도 JSON 유지.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 8 Step 3 코드는 참조 구현. **리드 결정 1은 참조 구현에 없으므로 반드시 반영.**

1. `test/test_manifest.py`(4개), `test/test_ingest_service.py`(4개) 작성 — 계획서 Step 1 그대로. 변경 금지.
2. `pytest --active-profile=local test/test_manifest.py test/test_ingest_service.py -v` → `ModuleNotFoundError` 확인.
3. `src/service/manifest.py`, `src/service/ingest_service.py`, `ingest.py` 작성 — 계획서 Step 3 참조.
4. 같은 명령 → 8 PASSED.
5. `src/library/global_logger.py`를 리드 결정 1 코드로 수정. 기존 `test/test_global_logger.py`의 `_reset_configured_flag`가 깨지면 **테스트를 고치지 말고** 완료 보고에 적는다(Validator가 교체).
6. `python ingest.py --help` 실행 → 인자 3개 표시, 예외 없음(Ollama 불필요).
7. 전체 `pytest --active-profile=local -v` → `test_global_logger.py` 외 회귀 없음.
8. 완료 보고: 실행 명령·결과, 생성·수정 파일, 참조 구현과 다른 점, `test_global_logger.py` 실패 여부.

**하지 않을 것:** 커밋, 실제 `ingest.py` 인제스트 실행(Validator 담당 — `data/` 생성 방지), `resources/config_local.ini`에 email/토큰 기입, `.gitignore` 변경, `requirements*` 변경.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 단위 8개 통과 | `pytest --active-profile=local test/test_manifest.py test/test_ingest_service.py -v` |
| 회귀 없음 | 전체 green, 소켓 차단 상태 통과 |
| GlobalLogger 실기록 | `test_global_logger.py` 교체: (a) tmp_path 로그 디렉터리로 `get_logger("x").info("hello")` 후 파일에 `INFO [x] hello` 존재, (b) 두 번 호출해도 root에 `kudos-rag-file` 핸들러 1개, (c) 기존 root 핸들러(caplog)가 제거되지 않음. 헬퍼: 테스트 전후 `kudos-rag-*` 핸들러 제거 |
| manifest 저장 시점 | 문서 2개 중 두 번째 `upsert`에서 예외를 내는 가짜 store로 → 첫 문서는 manifest에 있고 두 번째는 없음 |
| removable 범위 | 계획서 테스트 + `ingest_openapi`에서 fetch 실패 소스의 기존 문서가 삭제되지 않음(FakeSession 이용) |
| `--full` | `reset_all` 후 count 0, manifest 빈 파일 저장 |
| CLI 종료 코드 | 계획서 Step 5 조건에 따라 리드 결정 2 표대로. Ollama 미기동이면 `[미확인]`으로 기록 |
| 실데이터 openapi 인제스트 | 리드 결정 2 표. 결과(문서 수·청크 수·재실행 결과·소요 시간) 보고서 기록. `data/` 생성물은 커밋 대상 아님 |
| `logs/app.log` 기록 | 실행 후 파일에 `[ingest]` 또는 `[src.service.ingest_service]` 라인 존재 |
| `.gitignore` | `data/`, `logs/` 포함 여부 확인 → 없으면 사용자 안내 |
| 구현이 명세와 일치 | 인터페이스·증분 규칙·리드 결정 1 대조 |

## 완료 기준

- [x] 단위 테스트 전부 PASS (manifest 11 + ingest_service 18 + logger 7 교체, 전체 195 passed)
- [x] 전체 green, 소켓 차단 상태 통과
- [x] `GlobalLogger`가 pytest 안에서도 실제 파일에 기록, 기존 핸들러 보존, 중복 부착 없음, caplog 동시 동작 — **리뷰 1 이관 항목 해소**
- [x] `ingest.py --source openapi` 실데이터 실행 — `bge-m3` 설치 후 **추가 199 / 청크 199 / 8.0초**, 재실행 **추가 0 / 갱신 0 / 0.65초**, 실인제스트 중 서드파티 로그 0줄. **조건 해제 (2026-09-21, review-04 1단계).** Confluence 소스는 토큰 필요 → 사용자 실행
- [x] 실행 후 `logs/app.log`에 인제스트 로그 존재 (`INFO [ingest] --full: ...`)
- [x] 실패 소스의 기존 문서 보존(removable) 확인
- [x] 구현이 이 문서의 인터페이스와 일치 (manifest/ingest_service/ingest.py IDENTICAL, logger = 리드 결정 1)
- 추가 확인: `--help` 정상, 토큰 없이 `--source confluence` → 401 안내 + 종료 1 (모델 없이도 동작)

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. **Ollama 모델 미설치 시 `ingest.py`가 스택트레이스로 종료** — 종료 코드 1은 계약대로지만 사용자 안내가 없다. **리뷰 2 조치 후보**로 넘긴다(수정 방식: 인제스트 전 모델 존재 사전 점검 vs 예외 포착 — 리뷰 결과와 함께 결정).
2. `logs/app.log`에 chromadb·urllib3 DEBUG 대량 기록 — ini `log-level=DEBUG` 그대로의 동작. 서드파티 로거 레벨 조정은 리뷰 2 후보(nit).
3. chromadb `Starting component Posthog` 로그 — 컴포넌트 생성 로그. Task 7 소켓 차단으로 외부 전송 없음 실증. 변경 없음.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드 관련 완료 기준 전부 통과, 설계 문서와 구현 일치. 실데이터 인제스트는 `ollama pull bge-m3` 후 Task 7 통합 2건과 함께 Validator 재실행.
→ **리뷰 2 통과 (2026-09-21) — 커밋 대기.** 리뷰 2 조치 A로 `ingest.py`(임베딩 사전 점검)·`global_logger.py`(서드파티 WARNING)·`manifest.py`(원자 저장) 변경, `test_ingest_cli.py` 신설. 실데이터 인제스트 조건 유지.

`data/` 상태: `data/chroma/` 생성, `manifest.json = {}`, 청크 0건. Task 9 실데이터 sanity 전에 재인제스트 필요.

커밋 대상(사용자 수행): `src/service/manifest.py`, `src/service/ingest_service.py`, `ingest.py`, `src/library/global_logger.py`(수정), `test/test_manifest.py`, `test/test_ingest_service.py`, `test/test_global_logger.py`(교체).

## 범위 제외

- 검색·서빙 → Task 9~11
- Confluence 첨부·라벨 인제스트
- 병렬 임베딩, 진행률 표시
- 스케줄링(cron) — README(Task 13)에 수동 실행 절차만
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 7 진행 중). GlobalLogger 수정 방식 확정(root 핸들러 직접 부착, 이름 기반 중복 방지). Task 7 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 리드: Task 7 Builder 완료·리드 대조 후 Validator 검증과 병행해 Builder 지시. 사용자 지시: **Task 8 완료 후 리뷰 2 수행, 현황 보고**(conventions.md §2-4). Ollama 모델 미설치 상태 — 실데이터 인제스트 검증은 사용자가 `bge-m3`를 받은 뒤 수행.
- 2026-09-21 Builder 완료: RED → 단위 8 passed → `global_logger.py` 리드 결정 1 반영 → `ingest.py --help` 정상 → 전체 172 passed / **1 failed(`test_get_logger_creates_log_file`, 예고된 순서 의존 — 헬퍼가 옛 플래그만 리셋하고 핸들러를 제거하지 않음)** / 3 deselected. 별도 프로세스로 파일 실기록·중복 없음·기존 핸들러 보존 확인. `data/` 미생성. 참조 구현과 다른 점: `global_logger.py`만.
- 2026-09-21 리드: `global_logger.py` 대조 일치(`[검증]`). Validator에게 검증 지시(logger 테스트 교체 포함).
- 2026-09-21 Validator 회차 1: 코드 완료 기준 전부 PASS, 195 passed(소켓 차단 포함). logger 테스트 7개로 교체, manifest +7, ingest +14. 실데이터 인제스트는 모델 미설치로 미실행. 비차단 3건.
- 2026-09-21 리드: 조건부 READY FOR REVIEW. 리뷰 2(Task 6~8) 착수.
