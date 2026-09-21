# 리뷰 4 (최종): Task 12~13 + 스펙·계획서 전체 완료 기준 대조

- 일자: 2026-09-21
- 대상: `index.html`, `test_web_ui.py`, `eval/*`, `test_integration_ask.py`, `test_run_eval.py`, `README.md` + **스펙(design.md) 전체 ↔ `src/`·`ingest.py`·`main.py`** — 전체 296 passed 기준선
- 방식: 읽기 전용 리뷰 에이전트(서버 기동·Ollama 요청 금지). 소켓 차단 정순·역순 모두 green 확인.

## 요약

- blocker: 없음. **스펙 대비 문서화되지 않은 기능 차이 없음**(문구·세부 info 4건만).
- should-fix 2건(README 문구) + nit 채택 7건 → 조치 A(Builder), 조치 B(Validator).
- 계획서 전체 완료 기준 4항목: 1 충족 / 2·3 조건부 / 4 측정 전 — 모두 **모델·토큰·브라우저**라는 사용자 환경 조건에 걸려 있고 코드 결함은 없다.

## 스펙 ↔ 구현 대조 결과 `[검증]`

§9 ini(추가 키 `manifest-path`는 Task 8 문서화), §5-1~5-7 각 컴포넌트 규칙, §7 에러 표 7행, §8 평가 — 전부 일치. info:
- I-1 스펙 §7 "관련 문서를 찾지 못했습니다" vs §5-6·구현 "관련 내용을 문서에서 찾지 못했습니다" — 스펙 내부 불일치. 구현은 §5-6 기준. 조치 없음(스펙 문서는 리드 쓰기 영역 아님 — 사용자 안내).
- I-2 §5-1 "status 등 그 외 매크로는 본문 텍스트만" vs 구현 "통째 제거" — Task 2 명세 표에 문서화된 결정. status 매크로 `title`("진행중")이 사라지는 점은 실데이터 평가 후 재검토.
- I-3 `top_k` 1~20 허용이나 후보군 `bm25-k+vector-k=20`이라 dedup 후 20 미만 가능. 모순 아님.
- I-4 UI·README가 `/check`·`/v1/…` 하드코딩 — ini `api-root` 변경 시 UI 깨짐. PoC 허용, 운영 인계 메모.

## 조치 A (Builder)

### A-1. README 보강 (S-1, S-2, N-6, N-7, info)
1. **평가 절**(S-1): "인제스트 후 `data/manifest.json`에 Q3 doc_id(`message-api:GET:/check`, `general-chatbot-api:GET:/check`)가 있는지 먼저 확인하고, 없으면 실제 헬스체크 경로로 교체" — Q3 기대값은 픽스처 스펙에 없어 실스펙 실존이 `[미확인]`이며, 1문항 오기만으로 67% → 종료 1이 된다.
2. **테스트 절 `run_eval` 줄**(S-2): "(인제스트 완료·Ollama `bge-m3` 필요. 80% 미달 또는 질문 없음 → 종료 1. `--file`로 세트 지정. 프로젝트 루트에서 실행)".
3. **개발 환경**(N-6, N-7): pip-compile 명령을 `requirements.txt` 헤더와 동일하게(`pip-compile --no-index --output-file=requirements.txt requirements.in`), "Python 3.12" 명시, "운영 프로파일: `resources/config_<profile>.ini`를 만들고 `--active-profile=<profile>`로 선택(`host=0.0.0.0`, `reload=False`)".
4. **인제스트 절**(info): "`--full` 완료 직후 반드시 `POST /v1/reload`. 그 사이의 `/v1/ask`는 옛 컬렉션 참조로 500이 난다."

### A-2. `eval/run_eval.py` 소폭 수정 (N-1, N-2, N-3)
```python
import global_variable
...
parser.add_argument("--active-profile", default="local", help="설정 프로파일 (resources/config_{profile}.ini)")
parser.add_argument("--k", type=int, default=6, help="질문당 검색 청크 수 (hit@k 의 k)")
parser.add_argument("--file", default=f"{global_variable.PROJECT_ROOT_DIR}/eval/questions.yaml", help="평가 질문 yaml 경로")
...
_SOURCES = ("all", "confluence", "openapi")
# 질문 로딩 직후, retriever 생성 전에:
bad = [q["question"] for q in questions if q.get("source", "all") not in _SOURCES]
if bad:
    print(f"source 값이 올바르지 않습니다({'/'.join(_SOURCES)} 중 하나): {bad}")
    return 1
```
`source` 오타(`opanapi`)가 조용히 X로 집계되던 문제를 막는다. 기존 `test_run_eval.py` 9개 영향 없어야 함(`--file` 기본값 변경은 테스트가 `--file`을 명시하면 무관 — Validator 확인).

### A-3. `llm_factory.has_model()` 추가 (Task 13 비차단 1, N-4)
```python
def has_model(name: str) -> bool:
    """Ollama 에 모델이 설치되어 있는지 /api/tags 로 확인한다. 태그 없는 이름은 ':latest' 로 본다."""
    try:
        response = requests.get(f"{_ollama_config()['base-url']}/api/tags", timeout=3)
        if response.status_code != 200:
            return False
        installed = {m.get("name", "") for m in response.json().get("models", [])}
    except (requests.RequestException, ValueError):
        return False
    wanted = name if ":" in name else f"{name}:latest"
    return wanted in installed or name in installed
```
`[추측]` Ollama `/api/tags`는 `bge-m3`를 `bge-m3:latest`로 보고한다 — 두 표기 모두 허용. 인터페이스 추가 1개(`llm_factory.has_model(name: str) -> bool`). 통합 픽스처의 가드 교체는 Validator(조치 B-1).

### A-4. `index.html` 접근성 (N-8)
`#question`에 `aria-label="질문"`, `#source`에 `aria-label="검색 대상 소스"`, `#health`에 `aria-live="polite"`. 3개 속성만 추가. `test_web_ui.py` 15개 영향 없어야 함.

### 조치 A 완료 기준
- 전체 green(기존 296 + Validator 추가분), 계획서 테스트 미변경
- `python -m eval.run_eval --help`에 인자 설명 3개. ~~다른 디렉터리(`cd /tmp`)에서 실행~~ → **정정**: `python -m`은 CWD에 `eval` 패키지가 있어야 하므로 프로젝트 루트 실행이 전제(`PYTHONPATH` 지정 시에만 다른 CWD 가능 — Builder `[검증]`). 기준은 "루트에서 `--file` 생략 시 절대 경로 기본값으로 동봉 yaml을 찾는다"로 한정
- `source: opanapi` 문항 → 안내 후 종료 1
- `has_model("bge-m3")`가 현재 환경(모델 0개)에서 False, monkeypatch로 `{"models":[{"name":"bge-m3:latest"}]}` 주면 True

## 조치 B (Validator)

1. **통합 픽스처 가드 교체**(3곳: `test_llm_factory.py`, `test_rag_service.py`, `test_integration_ask.py`): `if not (llm_factory.ping_ollama() and llm_factory.has_model(<필요 모델>)): pytest.skip("Ollama 미기동 또는 모델 미설치: …")`. 완료 기준: 현재 환경에서 `-m integration` 실행 시 **ERROR 0** — ~~5건 전부 SKIP~~ → **정정**: `test_ping_ollama_against_real_server`는 모델이 없어도 Ollama가 떠 있으면 진짜로 통과하는 테스트라 가드를 `ping_ollama()`만으로 둔다(Validator 판단 수용). 결과 **1 passed / 4 skipped / 0 error**.
2. `test_integration_ask.py`: 미사용 `Document` import 제거, `ask_controller.context` 대입을 `monkeypatch.setattr`로(N-5).
3. `has_model` 단위 테스트(`test_llm_factory.py`): 200+목록 포함 → True, 미포함 → False, 비200 → False, 예외 → False, `bge-m3` ↔ `bge-m3:latest` 매칭.
4. `run_eval` 추가 테스트: `source` 오타 → 종료 1 + 안내, `--file` 기본값이 절대 경로.
5. **테스트 로그 격리**(info 채택): `test/conftest.py`에 autouse fixture로 `Profile().get_common_config()["log-file-path"]`를 `tmp_path_factory` 경로로 monkeypatch — `GlobalLogger`가 root에 이미 붙인 `kudos-rag-*` 핸들러는 import 시점 것이므로, fixture에서 제거 후 재부착되도록 처리(기존 `isolated_root` 패턴 재사용). 완료 기준: 전체 실행 후 프로젝트 `logs/app.log` 줄 수 불변.
6. 조치 A 완료 기준 검증, 전체 green·소켓 차단.

## 변경하지 않는 항목 (기록)

| # | 항목 | 판단 |
|---|---|---|
| 1 | I-1 스펙 문구 불일치 | 스펙 문서는 사용자 영역. 안내 |
| 2 | I-2 status 매크로 title 소실 | Task 2 문서화 결정. 실데이터 평가 후 |
| 3 | I-4 UI 경로 하드코딩 | PoC 허용. 운영 인계 메모(README에 이미 `api-root` 언급 없음 — 별도 추가하지 않음) |
| 4 | 답변 버블이 fetch 전에 빈 카드로 생성, 예외 시 빈 버블 잔존 | 사용자 육안 확인 항목에 포함(Task 12 개선 후보와 함께) |
| 5 | `data/chroma` mtime 갱신 원인 `[미확인]` | Validator 실기동(Task 11·12) 추정. 내용 무변경 확인됨 |

## 계획서 전체 완료 기준 판정 (리뷰 4 시점)

| # | 기준 | 판정 | 남은 조건 |
|---|---|---|---|
| 1 | 단위 테스트 전체 통과(Ollama 없이) | **충족** | — |
| 2 | `ingest.py --source all` + 재실행 변경 0 | 조건부 | `bge-m3`, `CONFLUENCE_API_TOKEN`·email |
| 3 | UI 스트리밍 답변 + 출처 카드 | 조건부 | `qwen3:14b`, 브라우저 육안 |
| 4 | `run_eval` hit@6 ≥ 80% | 측정 전 | 인제스트 + Confluence 문항 10개 이상 + Q3 실존 확인 |

## 운영 인계 (사내 서버 Docker 이전 시) — README 밖 메모

1. `[fastapi] host=0.0.0.0`, `reload=False` 운영 프로파일 ini
2. `[ollama] base-url` → compose 서비스명. 모델 2개(~10GB) pull을 ollama 컨테이너 기동에 포함
3. `data/`·`logs/` 볼륨 + 컨테이너 UID 쓰기 권한
4. `CONFLUENCE_API_TOKEN` secret, ini `email`
5. Python 3.12, 단일 uvicorn 워커, UI 경로 하드코딩(I-4)
6. `--full` ↔ `/v1/reload` 사이 500 창 (README A-1-4로 안내)

## 진행 기록

- 2026-09-21 리드: 리뷰 결과 수신. should-fix 2 + nit 7 채택 → 조치 A(Builder 4건), 조치 B(Validator 6건). 스펙 I-1은 사용자 안내.
- 2026-09-21 Builder 조치 A 완료: README 4곳, `run_eval.py`(절대 경로 기본값·`_SOURCES` 검증·help), `has_model`(현재 환경 False, stub `bge-m3:latest` → True), `index.html` 속성 3개. 296 passed ×3. 확인 요청 2건 → (1) `cd /tmp` 기준 문구 정정(위), (2) `test_profile.py::test_common_config_log_settings_are_resolved` 1회 실패 후 미재현 — 누출값이 `tmp_path_factory` 형태. `[추측]` Validator가 동시 작성 중인 조치 B-5 conftest fixture가 `Profile().get_common_config()` 반환 dict(싱글톤 내부 객체)를 복사 없이 변형한 것. Validator 확인 지시.
- 2026-09-21 Validator 조치 B 완료: **플래키 원인 규명** — B-5 첫 버전이 `Profile.get_common_config`를 세션 스코프로 monkeypatch해 ini 값 확인 테스트가 결정적으로 실패한 것(Validator 스스로 발견·교체). 최종 conftest는 `Profile`을 건드리지 않고 root에 `kudos-rag-file` 이름의 tmp 핸들러를 선점하는 방식 → GlobalLogger가 재부착하지 않아 테스트 로그가 tmp로만 감. 7회(정순 3·역순·소켓 차단+역순·단독·조합) 전부 통과, `logs/app.log` 줄 수 불변. B-1 가드 3곳(ini 모델명 연동), B-2, B-3 7케이스, B-4, B-6 조치 A 검증 전부 PASS. `-m integration` → 1 passed / 4 skipped / 0 error. **전체 307 passed**. 계획서 테스트 파일 7개 중 5개 0줄 차이, 2개는 지시된 변경만. 가치 낮은 실네트워크 테스트 1개 자체 삭제.
- 2026-09-21 리드: B-1 기준 정정(ERROR 0), **리뷰 4 종결. 전 13 Task 리뷰 완료.**

## 종결 상태 (최종)

- 전체 **307 passed / 5 deselected** (소켓 차단 정순·역순 포함). `-m integration`: 1 passed / 4 skipped(모델 미설치 사유 메시지에 `ollama pull` 안내 포함).
- 미커밋: Task 1~13 산출물 전체 + 리뷰 1~4 변경분 + `docs/plans/` 전체.
- 모델 설치 후 Validator 재실행 순서: ① Task 7 임베딩 통합 2 → ② Task 8 `ingest.py --source openapi`(+재실행 변경 0, httpx 노이즈 부재) → ③ Task 9 sanity → ④ `/v1/reload` 지연 측정 [여기까지 `bge-m3`] → ⑤ Task 10 LLM 통합 → ⑥ Task 11 full 실기동 → ⑦ Task 13 `run_eval`·`test_integration_ask` [`qwen3:14b`]. 사용자 알림 시 리드가 한 번에 지시.

## 모델 설치·재실행 (2026-09-21 사용자 지시 "올라마 설정해줘")

사용자가 모델 다운로드를 명시적으로 지시 → 리드가 **Validator에게 위임**(리드는 실행 도구 없음, Builder는 코드 담당). 절차:
1. `ollama pull bge-m3` → `ollama list` 확인 → 재실행 ①~④ 수행·보고
2. `ollama pull qwen3:14b`(약 9GB, 시간 소요) → 재실행 ⑤~⑦ 수행·보고
- 제약: `resources/config_local.ini` 변경 금지, Confluence 인제스트(토큰 필요)는 수행하지 않음(`--source openapi`만), `data/`는 실데이터 인제스트 결과로 남김, 서버 기동 시 종료 필수, 커밋 금지.
- 코드 결함 발견 시 RETURN TO BUILDER가 아니라 **리드에게 보고**(티켓 재개 판단은 리드).

### 1단계 결과 (2026-09-21, `bge-m3` 설치 후) — ①~④ 전부 PASS `[검증]`
- 모델: `bge-m3:latest` 1.08GB, embedding_length 1024, context 8192.
- ① Task 7 임베딩 통합 3 passed(ping·1024차원·3000자). **Task 7 조건 해제.**
- ② Task 8 `ingest.py --source openapi`: 1회차 추가 199 / 청크 199 / 8.0초(message-api 182 + general-chatbot-api 17), 2회차 추가 0 / 갱신 0 / 0.65초. `app.log` 2줄, 서드파티 라인 0 → 리뷰 2 A-2 `[미확인]` 해소. **Task 8 조건 해제(OpenAPI 부분; Confluence는 토큰 필요).**
- ③ Task 9 sanity: chunk_count 199 = manifest, "메시지 등록 API"·`/v1/messages/message`·자연어 질의 모두 기대 문서 **2위**(0.02~0.06초). **Task 9 조건 해제.** 관찰: 1위는 `POST /v1/dialogs/dialog`·`GET /v1/messages/message/{seq}` → Task 13 튜닝 대상(가중치, `id_key`).
- ④ `/v1/reload` 평균 0.018초(199청크), reload 중 `/check` 0.004초. `reopen()` 비용 무시 수준 → 리뷰 3 비차단 3 해소. `[추측]` 수천 청크에서는 BM25 재구성이 지배적.
- Q3 `expected_doc_ids` 둘 다 manifest에 실존 → 리뷰 4 S-1 리스크 없음(README 절차는 유지).
- 리드: 2단계(`qwen3:14b` → ⑤~⑦) 지시.

### 2단계 중간 (다운로드 대기 중, `bge-m3`만으로 선행) `[검증]`
- ⑦ 일부: `run_eval --k 6` → **hit@6 = 3/3 = 100%**, 종료 0, 1.7초. **계획서 완료 기준 ④ 충족** — 단 3문항(OpenAPI)이라 통계적 의미 제한, Confluence 문항 추가 후가 실질 평가(리드 결정 2).
- `-m integration`: 3 passed(ping·임베딩 2) / 2 skipped(`qwen3:14b` 필요) / 0 error — 리뷰 4 B-1 가드가 모델 단위로 정확히 동작.
- `qwen3:14b` 다운로드 12%, 속도 변동(0.27~5.4MB/s), 잔여 `[미확인]`(약 40분 추정).
- 60분 시점 22%(2.0GB), 평균 0.55MB/s, 진행률 두 번 후퇴(재시도로 진척 손실 `[추측]`). Validator가 선택지 3개 제시(대기 / 중단 후 사용자 재시도 / `qwen3:4b` 대체).
- **사용자 결정: 2번 — pull 중단, 사용자가 직접 다운로드.** 리드가 Validator에게 중단 지시. 받은 2GB는 Ollama 캐시에 보존되어 재pull 시 이어받음(`[추측]`, Ollama 동작). `qwen3:14b` 설치가 확인되면 ⑤~⑦ 재지시.
- Validator 중단 처리 완료(24% 시점, 프로세스 종료, 오류 0, `bge-m3` 온전, partial 5.6GB 보존).
- **2026-09-21 사용자: `qwen3:14b` 설치 완료 알림.** 리드가 Validator에게 ⑤~⑦ 지시.
- Validator 정정 `[검증]`: `ollama list`에 `qwen3:14b` 9.3GB 등록됨. CLI pull 프로세스를 종료한 뒤에도 다운로드가 완료된 것으로 관측 — `[추측]` 블롭 전송은 `ollama serve`가 수행하므로 CLI 종료가 서버 측 전송을 멈추지 않았고, "표시 2.3GB vs 블롭 5.6GB" 불일치와 일관됨(사용자가 직접 pull을 재실행했을 가능성과 구분 불가). 직전 "중단 완료" 보고는 CLI 기준으로만 정확. ⑤~⑦ 착수.

### 2단계 결과 (2026-09-21, `qwen3:14b` 설치 후) — ⑤~⑦ 전부 PASS `[검증]`
- ⑤ Task 10 LLM 통합 1 passed(3.3초): answer `str`, `<think>` 부재(`reasoning=False` 실동작), 인용 `[1]` 포함. **Task 10 조건 해제.**
- ⑥ Task 11 full 실기동: `/check` `{"status":"ok","ollama":true,"chunk_count":199}`. `POST /v1/ask`(openapi, "메시지 등록 API 호출 방법") 1회차 30.4초(모델 로딩) / 2회차 13.0초, answer에 `POST /v1/messages/message`·`[2]`·`[3]` 인용, sources 6건, **필수 파라미터 필드명(`service_key`, `page_key`, `chatbot_key`, `user_id`, `original_message`) 정확 추출** — Task 4 중첩 `$ref` 수정의 직접 효과. `/v1/ask/stream` 350프레임(token 348 → sources → done), 조립 answer 855자 = 동기 응답과 동일. 포트 해제, `app.log` 서드파티 0. **Task 11 조건 해제.**
- ⑦ `-m integration` **5 passed**, `run_eval` hit@6 = 3/3 = 100%, 전체 **307 passed**(소켓 차단 동일), 테스트 로그 격리 유지.

### 최종 판정 — 계획서 전체 완료 기준
| # | 기준 | 판정 |
|---|---|---|
| 1 | 단위 테스트 전체 통과(Ollama 없이) | **충족** |
| 2 | `ingest.py` 인제스트 + 재실행 변경 0 | **충족**(OpenAPI 199청크). Confluence는 사용자 토큰 영역 |
| 3 | UI 스트리밍 답변 + 출처 카드 | **서버·API 층 충족**(SSE 348토큰·sources 6). 브라우저 육안 `[미확인]` — 사용자 |
| 4 | `run_eval` hit@6 ≥ 80% | **충족**(100%, 3문항 — 문항 확충 후 재측정 권장) |

### 후속 후보 (판정 무관, 사용자 판단)
1. README에 "첫 질의는 모델 로딩으로 30초 안팎 걸릴 수 있음" 한 줄(Validator 비차단 1). 기동 시 워밍업은 PoC에 과함.
2. 답변이 v1·v2 엔드포인트를 함께 제시 — 검색 결과 그대로의 정확한 동작. 실사용 피드백 후 프롬프트에 "최신 버전 우선" 규칙 검토.
3. sources 1위가 `POST /v1/dialogs/dialog`(기대 문서 2위) — 순위 튜닝: `bm25-weight`/`vector-weight`, RRF `id_key="chunk_id"`(리뷰 3 인계). Confluence 문항 포함 평가 후.
4. Task 12 개선 후보: `error` 시 부분 답변 유지, 빈 답변 버블.
5. `requirements.in` 3건, 계획서 동기화, 스펙 §7 문구, `.serena/` gitignore.

**PoC 종결 (2026-09-21).** 에이전트 작업 완료. 커밋·브라우저 확인·Confluence 인제스트는 사용자 영역.

### 종결 후 후속 1: `main.py` 실행 시 "라이브러리 미설치" 보고 (2026-09-21)
- Validator 진단 `[검증]`: venv 안 정상(`pip check` 이상 없음, requirements.txt 120개 누락·불일치 0), venv 밖 시스템 `python3`에 `fastapi` 없음 → **venv 미활성화가 원인**. 설치 불필요, 미수행.
- 추가 관찰: venv 미활성화 시 `python` 명령 자체가 없음(`python3`만) → README 실행 예시(`python main.py …`)가 그대로 실패.
- **조치(Builder)**: README "인제스트"·"서버"·"테스트" 절 코드 블록 첫 줄에 `source .venv/bin/activate` 추가, "개발 환경" 절 끝에 "이하 모든 명령은 venv 활성화 상태(프롬프트 `(.venv)`)를 전제한다" 한 문장. 그 외 변경 없음.
- Builder 완료: README 4곳(44~45행 안내 문장, 62·89·116행 activate). 코드·설정·테스트 미변경. 리드 diff 확인 일치. **후속 1 종결.**
