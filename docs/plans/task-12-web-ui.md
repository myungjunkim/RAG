# Task 12: 최소 웹 채팅 UI

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 12 (2944~3126행)
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 공통 규칙: `docs/plans/conventions.md`
- 선행: Task 11 (`/v1/ask/stream` SSE, `/check`, 정적 마운트, 임시 `index.html`)
- 상태: **신규 구현 — Builder 진행 중** (리뷰 3 종결 후 2026-09-21 지시)

## 목표

`resources/static/index.html` 한 파일(HTML+CSS+JS, 외부 의존 없음)로 질문 입력 → SSE 스트리밍 답변 표시 → 완료 후 소스 카드 표시 → 오류 표시를 제공한다. 헤더에 `/check` 결과를 보여준다.

## 설계

### 컴포넌트

정적 파일 1개. Task 11의 임시 1줄 파일을 교체한다. 빌드 도구·프레임워크·CDN 없음(사내 문서 내용이 브라우저→로컬 서버 외 어디로도 가지 않는다).

### 데이터 흐름

```
로드 → GET /check → 헤더 "상태: ok|degraded · Ollama 연결됨|끊김 · 청크 N개"
질문 제출 → POST /v1/ask/stream {question, source, top_k?}  (fetch + ReadableStream, EventSource는 POST 불가)
  ← event: token  → 답변 영역에 append (data는 JSON 문자열 → JSON.parse)
  ← event: sources → 카드 목록 렌더 (index, title(링크 url, 새 탭), source 배지, snippet)
  ← event: done   → (JS는 별도 분기 없이 무시) 스트림 종료 후 finally 에서 입력 재활성화
  ← event: error  → 빨간 오류 메시지(data 문자열), 입력 재활성화
fetch 실패(서버 다운, 5xx) → 동일 오류 표시
```

**`done` 처리 결정**(2026-09-21, Builder 질의): JS에 `done` 분기를 두지 않는다. 서버가 `done` 직후 스트림을 닫으므로 `reader.read()`의 종료가 동일한 신호이며, 입력 해제는 `finally`가 담당한다(계획서 JS와 동일). Validator의 계약 테스트는 `event === 'token'|'sources'|'error'` 3개 분기 존재를 확인하고, `done`은 "서버가 보내는 이벤트 목록에 있으나 클라이언트가 무시해도 되는 것"으로 취급한다(단순 문자열 grep은 `reader.read()`의 `done` 플래그와 혼동되므로 금지).

### Consumes (Task 11 계약)

- SSE 프레임 `event: <name>\ndata: <JSON>\n\n`. `token` data = JSON 문자열, `sources` = `[{index,title,url,source,snippet}]`, `done` = `""`, `error` = detail 문자열.
- `GET /check` → `{status, ollama, chunk_count}`.
- 소스 선택: `all|confluence|openapi` — `AskRequest.source` Literal과 일치.

### UI 규칙

| 항목 | 규칙 |
|---|---|
| 답변 렌더 | 텍스트 그대로(`textContent`) — Markdown 렌더·HTML 삽입 없음(XSS 회피, 의존성 없음). 줄바꿈은 `white-space: pre-wrap` |
| 인용 `[n]` | 별도 하이라이트 없음. 소스 카드의 `index`와 육안 대응 |
| 소스 카드 | 제목 클릭 → `url` 새 탭(`target=_blank rel=noopener`). Confluence는 페이지, OpenAPI는 Swagger `/docs` |
| 스트림 파싱 | `\n\n` 단위로 프레임 분리, 마지막 불완전 프레임은 버퍼 유지. `event:`·`data:` 두 줄만 사용 |
| 입력 잠금 | 요청 중 버튼·입력 disabled, `done`/`error`/fetch 실패 시 해제 |
| HTTP 오류 본문 | `!res.ok`일 때 `detail`이 **문자열(503/504) 또는 배열(422 — `[{loc, msg, type}]`)** 둘 다 가능. `Array.isArray(detail) ? detail.map(d => d.msg).join(", ") : detail`로 표시(리뷰 3 인계 — 계획서 JS는 문자열만 가정해 422에서 `[object Object]`가 뜸) |
| 한국어 UI 문구 | 헤더 상태, 플레이스홀더, 오류 문구 |

### 기각한 대안

- `EventSource` API: GET만 지원. 질문 본문을 쿼리스트링에 넣으면 길이·인코딩 문제. `fetch` 스트림 사용.
- Markdown 렌더 라이브러리(marked 등): CDN 의존 또는 번들 필요. PoC는 pre-wrap 텍스트.
- 별도 프론트엔드 프로젝트(React/Vite): 빌드 파이프라인·의존성 추가. 정적 1파일로 충분.

## 작업 목록 (Builder)

`conventions.md` 적용 — 계획서 Task 12 Step 1의 HTML은 참조 구현. 위 UI 규칙·데이터 흐름을 지키면 구조를 바꿔도 된다.

1. `resources/static/index.html`을 계획서 Step 1 내용으로 교체(임시 파일 덮어쓰기).
2. `pytest --active-profile=local test/test_ask_controller.py -v` → 8 PASSED(`test_root_serves_ui` 포함).
3. 정적 검증: `python -c "import html.parser"` 수준의 파싱 대신, 파일이 `<!doctype html>`로 시작하고 `lang="ko"`·`charset="utf-8"`이 있는지 확인. 외부 URL(`http://`, `https://`)이 `<script src>`/`<link href>`에 없는지 `grep`.
4. 전체 `pytest --active-profile=local -v` → 회귀 없음.
5. 완료 보고: 파일 크기·라인 수, 외부 리소스 없음 확인, 참조 구현과 다른 점.

**하지 않을 것:** 커밋, 서버 기동·브라우저 확인(Validator 담당), 컨트롤러·DTO 수정, 외부 CDN 참조.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 회귀 없음 | 전체 green |
| 외부 리소스 없음 | `grep -nE "https?://" resources/static/index.html`에서 `<script src`/`<link href`/`fetch(` 대상에 외부 호스트 없음(문서 링크·주석 제외) |
| 계약 일치 | JS가 파싱하는 이벤트 이름 4개(`token`/`sources`/`done`/`error`)와 소스 필드 5개가 Task 11 명세와 일치, 소스 선택값 3개가 Literal과 일치 |
| XSS 회피 | 답변·snippet·title 삽입이 `textContent`(또는 동등)로만 이루어짐, `innerHTML`에 서버 데이터 미삽입 |
| **수동 확인(조건부: Ollama+모델+인제스트)** | 계획서 Step 3: 헤더 상태 표시, OpenAPI 질의 스트리밍·소스 카드·새 탭, Ollama 종료 후 빨간 오류. 조건 미충족 시 **Ollama 없이 기동**해 헤더 `degraded`·청크 0 표시 확인. 빈 컬렉션에서는 질의가 오류가 아닌 `NOT_FOUND` 스트리밍이 되므로(Task 11 실기동 확인), **오류 경로는 서버를 내린 뒤 질의**(fetch 실패 → 빨간 오류)로 강제한다 — 설정 파일 변경 없이 가능한 방법 |
| 서버 없이 정적 확인 | `TestClient(main.app).get("/")` 본문에 `<form`/`<button`/`fetch(` 존재 |
| **정적 계약 테스트**(Validator 제안, 채택) | 새 `test/test_web_ui.py`: 외부 리소스 없음, 이벤트 이름 4개, 소스 필드 5개, `source` 선택값을 `ask_dto.SourceFilter`에서 꺼내 대조, `innerHTML`에 서버 데이터 미삽입, `Array.isArray(detail)` 분기 존재, 기본 구조(doctype/lang/charset/viewport). Task 13 이후 UI 수정 시 계약 회귀를 잡는다 |
| **브라우저 렌더링 육안 확인** | 에이전트는 브라우저를 띄울 수 없다 → `curl`로 `/` 본문·SSE 프레임까지만 확인하고 **실제 렌더링은 사용자 확인 항목**으로 `[미확인]` 기록 |

## 완료 기준

- [x] `test_ask_controller.py` 8 PASSED, 전체 green (287 passed / 5 deselected, 소켓 차단 포함). `test_web_ui.py` 15개 신설
- [x] 외부 리소스 참조 없음 (`https?://` 매치 0)
- [x] 이벤트·필드 계약이 Task 11과 일치 — `SourceFilter`·`SourceRef.model_fields`에서 값을 꺼내 대조(서버 변경 시 테스트가 깨지도록)
- [x] 서버 데이터 `innerHTML` 미삽입 (`innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write` 부재)
- [x] 422 detail 배열 처리 — 실기동에서 **422 detail이 실제로 배열임을 실측**(리뷰 3 인계가 필요했던 것 입증)
- [x] 새 탭 링크: `a.target='_blank'; a.rel='noopener'` JS 프로퍼티 방식(테스트로 고정)
- [x] 실기동 대체 경로: 헤더 `degraded`·청크 0, `/` 응답이 파일과 바이트 동일, SSE 프레임 정상, 서버 다운 시 연결 실패 → `catch` 경로, `app.log`에 `watchfiles` 0줄
- [ ] **브라우저 육안 확인 — 사용자**: 헤더 문구·레이아웃(소스 카드 그리드·스티키 입력창), 소스 카드 클릭 새 탭, 스트리밍 자동 스크롤, 소스 카드가 답변 요소 내부(`pre-wrap`)에 붙는 렌더링

## Validator 비차단 의견에 대한 리드 판단 (2026-09-21)

1. `error` 이벤트 수신 시 부분 토큰이 오류 문구로 **대체**됨 — 명세 UI 규칙대로. 부분 답변을 남기고 오류를 덧붙이는 편이 나을 수 있으나 PoC 범위에서는 유지. **개선 후보**로 기록(사용자 육안 확인 후 판단).
2. 소스 카드가 답변 요소 내부에 append — 렌더링 `[미확인]`, 사용자 확인 항목.

## 판정

**조건부 READY FOR REVIEW** (2026-09-21, 검증 회차 1). 코드·계약 기준 완료 기준 충족, 참조 구현 대비 11줄 차이(모두 명세 규칙 준수 목적). 남은 조건: 브라우저 육안 확인(사용자), 모델 설치 후 full 경로.
→ **리뷰 4 통과 (2026-09-21) — 커밋 대기.** 리뷰 4 A-4로 접근성 속성 3개 추가.

커밋 대상(사용자 수행): `resources/static/index.html`, `test/test_web_ui.py`.

## 범위 제외

- Markdown 렌더, 코드 하이라이트, 대화 이력, 다크 모드
- 인증
- 모바일 최적화(viewport 메타만)
- 커밋: 사용자가 직접 수행

## 진행 기록

- 2026-09-21 리드: 명세 초안 작성(Task 10 진행 중). Task 11 READY FOR REVIEW 후 Builder 지시 예정.
- 2026-09-21 리드: 리뷰 3 종결 확인, 422 detail 배열 처리 규칙 반영됨. Builder에게 시작 지시.
- 2026-09-21 Builder 완료: `index.html` 152줄/6,369B. 외부 리소스 0, `innerHTML` 계열 0, `textContent`/`createElement`만. 272 passed. 참조 구현과 다른 점 2건 — `formatDetail()`(422 배열 처리, 명세 지시), `input.disabled` 추가(명세 UI 규칙 "버튼·입력 disabled"). `done` 분기 없음(참조 구현과 동일) → 리드 결정: 불필요.
- 2026-09-21 리드: 2건 수용, `done` 결정 기록. Validator에게 검증 지시.
- 2026-09-21 Validator 회차 1: 완료 기준(코드·계약) 전부 PASS, 287 passed. `test_web_ui.py` 15개. 실기동 대체 경로 확인, 422 배열 실측. 브라우저 육안 `[미확인]`. 비차단 2건.
- 2026-09-21 리드: 조건부 READY FOR REVIEW.
