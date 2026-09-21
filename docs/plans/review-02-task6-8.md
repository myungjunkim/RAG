# 리뷰 2: Task 6~8 코드 리뷰 결과와 조치

- 일자: 2026-09-21
- 대상: Task 6(청킹), 7(LLM 팩토리·Chroma), 8(manifest·인제스트·CLI, GlobalLogger 수정) — 전체 195 passed 기준선
- 방식: 리드 지시로 읽기 전용 리뷰 에이전트가 6개 관점(증분 정확성, 청크→저장→검색 계약, 리드 결정 3곳, CLI·운영, 테스트 품질, 코드) 리뷰. 리드가 should-fix·nit를 재확인한 뒤 결정.

## 요약

- blocker: 없음
- should-fix 1건 → 조치 A
- nit 중 채택 2건 → 조치 A에 포함. 나머지 nit는 Task 13(README) 인계 또는 기록.
- 청크→저장→검색 계약 `[검증]`: Task 9·10 계획이 소비하는 키(`chunk_id`, `source`, `page_content`, `title`, `url`)가 모두 존재하고 타입 제약 준수. `_strip_prefix`가 confluence 접두어만 제거하고 openapi 헤더는 유지. **계약 변경 불필요.**
- 리드 결정 3곳(텔레메트리 `client_settings`, GlobalLogger root 직접 부착, `data/` 남김) `[검증]`: 모두 타당·부작용 없음. uvicorn과의 상호작용은 인프로세스 재현으로 기록 지속 확인(`[추측]` 실제 `main.py` 기동 순서·`reload=True` 이중 프로세스는 Task 11에서 확인).

## 조치 A (Builder): `ingest.py` 임베딩 사전 점검 + 로그 노이즈 + manifest 원자적 저장

### A-1. 임베딩 사전 점검 (should-fix)

**발견** `[검증]`(리뷰어 재현, 리드 코드 확인): `ingest.py`는 `VectorStoreRepository.from_profile()` → `--full`이면 `reset_all()` → 인제스트 순서로 진행한다. 임베딩 모델이 없거나 Ollama가 미기동이면 첫 `upsert`에서 `ollama.ResponseError`(404) 또는 `ConnectionError`가 나는데, 이 시점엔 이미 컬렉션과 manifest가 비워진 뒤다. 예외도 포착되지 않아 스택트레이스로 종료한다(종료 코드 1은 계약대로).

**결정: 수정.** `store` 생성 전에 임베딩 1회 호출로 가용성을 확인하고, 실패 시 안내 후 종료 1. `reset_all()`은 그 뒤에만 실행된다.

**변경** — `ingest.py` `main()`에서 `store = VectorStoreRepository.from_profile()` 줄을 아래로 교체:
```python
embeddings = llm_factory.create_embeddings()
try:
    embeddings.embed_query("연결 확인")
except Exception as e:  # 모델 미설치(404)·미기동(연결 거부) 등 — 종류를 가리지 않고 안내 후 종료
    model = Profile().get_config("ollama")["embedding-model"]
    print(f"오류: 임베딩 모델을 사용할 수 없습니다. Ollama 기동 여부와 `ollama pull {model}` 을 확인하세요. ({e})",
          file=sys.stderr)
    return 1
store = VectorStoreRepository.from_profile(embeddings)
```
`from src.service import llm_factory` import 추가. 기존 `from_profile(embeddings=None)` 인자를 재사용하므로 인터페이스 변경 없음. `ollama` 패키지 직접 import 없음(Global Constraint: LLM/임베딩 관련 import는 `llm_factory`만).

**참조 구현과의 차이**: `ingest.py`가 계획서 Task 8 Step 3과 이 블록만큼 달라진다. 명세 우선(conventions §3).

### A-2. 서드파티 로거 레벨 고정 (nit 채택)

**발견** `[검증]`: root 레벨이 ini `log-level=DEBUG`라 `httpcore.http11`, `urllib3.connectionpool`, `chromadb.config` DEBUG와 `httpx` INFO(`HTTP Request: POST /api/embed`)가 `app.log`에 기록된다. 현재 81줄 중 프로젝트 로그는 39줄. `[추측]` 실데이터 인제스트(임베딩 수백 회)에서는 httpx 줄이 지배한다.

**결정: 수정.** ini를 바꾸는 대안(`log-level=INFO`)은 프로젝트 자체 DEBUG 로그도 잃고 설정 변경(사용자 결정)이 필요해 기각. `GlobalLogger`에서 서드파티 로거만 WARNING으로 고정한다.

**변경** — `src/library/global_logger.py`의 `root.setLevel(...)` 직후:
```python
# 서드파티 HTTP·Chroma 내부 로그는 노이즈가 커서 WARNING 이상만 남긴다
for noisy in ("httpx", "httpcore", "urllib3", "chromadb"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
```

### A-3. manifest 원자적 저장 (nit 채택, 방식 변경)

**발견** `[검증]`: `Manifest.save()`가 대상 파일에 직접 `json.dump`한다. 인제스트 중단(Ctrl-C, 프로세스 종료)이 쓰기 도중이면 JSON이 손상되고, 다음 실행은 `load()`에서 raw `JSONDecodeError`로 죽는다. 리뷰어는 손상 시 안내 메시지를 제안했으나, **손상 자체를 막는 원자적 쓰기**가 더 작고 근본적이다(문서마다 `save()`하는 구조라 중단 확률이 낮지 않다).

**변경** — `src/service/manifest.py` `save()`:
```python
def save(self) -> None:
    os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
    tmp_path = f"{self._path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(self.entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, self._path)  # 같은 디렉터리 내 rename 은 원자적이다
```
인터페이스 변경 없음. 기존 테스트 11개 영향 없어야 함.

### 조치 A 완료 기준
- `pytest --active-profile=local` 전체 green(기존 195 + Validator 추가분)
- Ollama 미기동(예: `base-url`을 포트 1로 monkeypatch) 또는 모델 없는 상태에서 `python ingest.py --full --source openapi` → stderr에 안내 문구, 종료 1, **`data/manifest.json`·컬렉션 내용 변경 없음**(reset 미실행) — Validator 확인
- `app.log`에 새 실행 이후 `httpx`/`httpcore`/`urllib3`/`chromadb` DEBUG·INFO 라인 없음
- `.tmp` 파일이 저장 후 남지 않음

## 조치 B (Validator): CLI 자동 테스트 + 조치 A 검증

1. 새 `test/test_ingest_cli.py`: `VectorStoreRepository.from_profile`, `llm_factory.create_embeddings`, `ConfluenceRepository.from_profile`, `OpenApiRepository.sources_from_profile`/`fetch_spec`을 monkeypatch해 가짜 store·가짜 임베딩으로 `ingest.main()`을 호출. 고정할 동작: (a) 임베딩 `embed_query` 예외 → 종료 1 + stderr 안내 + `reset_all` 미호출 + manifest 미변경, (b) `--full` 정상 → `reset_all` 호출 후 인제스트, (c) openapi 일부 소스 실패 → 종료 1 + 요약 출력, (d) `--help` 종료 0. `sys.argv`는 monkeypatch.
2. `test_manifest.py`에 원자적 저장 테스트: 저장 후 `.tmp` 없음, 저장된 파일이 유효 JSON.
3. 조치 A 완료 기준 전부 확인. `app.log` 노이즈는 실행 전후 줄 수·로거명 집계로.

## Task 13(README) 인계 사항

`--full` 재인제스트가 필요한 경우를 README에 명시 `[검증]`(리뷰어 재현):
1. `[retrieval] chunk-size`/`chunk-overlap` 변경 후 — fingerprint에 청킹 설정이 없어 증분 실행은 `unchanged`로 판정(재청킹 안 됨).
2. 인제스트가 중간에 중단된 뒤 — **added** 문서의 배치 일부만 저장되고 manifest에 없으면, 다음 실행에서 문서가 짧아졌을 때 초과 청크가 고아로 남을 수 있음(changed 경로는 자동 복구).
3. `openapi_sources.yaml`에서 서비스를 제거한 뒤 — 제거된 서비스는 succeeded/failed 어디에도 없어 문서가 영구 잔존(removable 설계의 필연).

## 변경하지 않는 항목 (기록)

| # | 항목 | 심각도 | 판단 |
|---|---|---|---|
| 1 | `removable` prefix 매칭은 서비스 이름에 `:`가 있으면 충돌 가능 | info | `openapi_sources.yaml` 이름에 `:` 없음. 이름 규칙으로 충분 |
| 2 | 같은 doc_id가 소스를 바꾸는 경우 | info | doc_id 형식(숫자 vs `name:…`)이 겹칠 수 없음 |
| 3 | 입력 doc_id 중복 시 마지막 문서만 채택, 경고 없음 | info | yaml에 같은 `name` 2개는 설정 오류. Task 13 README에 "name 유일" 명시 |
| 4 | Chroma persist 디렉터리 권한 오류 시 스택트레이스 | nit | PoC 수용. 로컬 단일 사용자 |
| 5 | openapi 첫 줄이 `3×chunk_size-1` 이상이면 `ValueError` | info | 운영값 1000에서 헤더 한 줄 3000자 불가 |
| 6 | 문서마다 manifest 전체 재기록 | info | 200건 규모 무해 |
| 7 | Validator 테스트의 private 접근 | info | 리드 수용 사항 유지 |
| 8 | uvicorn `reload=True` 이중 프로세스의 `app.log` 동시 append | `[추측]` | Task 11 검증 항목 |
| 9 | Task 7 명세 리드 결정 1의 `[추측]` 문구("settings가 인자보다 우선될 수 있음") | info | 실제는 반대(`persist_directory` 인자가 `PersistentClient(path=…)`로 우선, 중복 지정 무해). 명세 문구 정정(리드) |

## 진행 기록

- 2026-09-21 리드: 리뷰 결과 수신, should-fix 1건·nit 채택 2건 → 조치 A(Builder), CLI 테스트·검증 → 조치 B(Validator). Task 13 인계 사항 기록. Task 7 명세 문구 정정.
- 2026-09-21 Builder 조치 A 완료: 3개 diff 명세 블록과 동일. 195 passed. 사전 확인 `[검증]`: 포트 1로 `--full --source openapi` → 안내 문구 + 종료 1, `data/` 수정시각 불변(reset 미실행), 서드파티 로거 WARNING, `.tmp` 잔여 없음.
- 2026-09-21 리드: diff 확인. Validator에게 조치 B 실행·조치 A 검증 지시.
- 2026-09-21 Validator 조치 B 완료: `test_ingest_cli.py` 신설 10개(임베딩 실패 → 종료 1·reset 미호출·manifest 보존, `--full` 순서, 일부 실패 종료 1, 재실행 변경 0, 401 종료 1 등), `test_manifest.py` 원자 저장 +2. 조치 A 완료 기준 전부 PASS — 모델 없는 상태 `--full` 실행 전후 `data/` sha 동일, `app.log` 서드파티 라인 0건, `.tmp` 없음. **전체 207 passed**(소켓 차단 포함). 결함 없음.
- 2026-09-21 리드: **리뷰 2 종결.** Task 6·7·8 "리뷰 2 통과 — 커밋 대기"(7·8은 모델 설치 후 통합·실데이터 재실행 조건 유지). Task 9 지시.

## 종결 상태 (재개 시 기준선)

- 전체 207 passed / 3 deselected (소켓 차단 포함)
- 미커밋: Task 6~8 산출물 + 리뷰 2 변경분(`ingest.py`, `src/library/global_logger.py`, `src/service/manifest.py`, `test/test_ingest_cli.py`, `test/test_manifest.py`) + `docs/plans/` 갱신분
- 모델 설치 후 Validator 재실행 항목(**순서 확정**): ① Task 7 임베딩 통합 2건 → ② Task 8 `ingest.py --source openapi` 실데이터 + 재실행 변경 0 + 실인제스트 중 `app.log` httpx 라인 부재 → ③ Task 9 실데이터 sanity. 사용자가 `ollama pull bge-m3` 완료를 알리면 리드가 한 번에 지시.
- `[미확인]` 리뷰 2 비차단: 모델 없는 환경에서 `app.log`가 비어 있는 것은 A-1 도입 후 정상(점검 성공 후에만 `--full` 라인 기록)
