# Task 14 (후속): 소스 카드 — 인용된 카드 강조, 나머지 접기

- 배경: 실사용 피드백(2026-09-22). "주제 생성 API 스펙 페이지 찾아줘"처럼 정답이 1개인 질문에서도 `top-k=6` 청크가 모두 카드로 표시되어 나머지 5개가 노이즈로 보임.
- 관련: Task 10 설계(sources = 검색 청크 전체, 인용 파싱 필터링은 기각 — 모델이 인용을 빠뜨리면 근거가 사라짐), Task 12 UI 규칙.
- 사용자 결정: 선택지 **B**(인용 강조 + 나머지 접기). A(인용만 표시)·C(`top-k` 축소)·D(임계값)는 기각/보류.
- 상태: **신규 구현 — Builder 진행 중** (2026-09-22 지시)

## 목표

서버·API 계약은 그대로 두고 **UI만** 바꾼다. 답변 본문에 `[n]`으로 인용된 소스 카드를 위쪽에 강조 표시하고, 인용되지 않은 카드는 "기타 참고 N건" 접힘 영역으로 내린다. 인용이 하나도 파싱되지 않으면 기존처럼 전부 펼쳐 표시한다(근거 손실 없음).

## 설계

### 변경 범위
`resources/static/index.html`의 `renderSources()`(및 필요 시 CSS 몇 줄)만. `rag_service`·컨트롤러·DTO·SSE 포맷 변경 없음.

### 동작 규칙

| 항목 | 규칙 |
|---|---|
| 인용 파싱 시점 | `sources` 이벤트 수신 시. 이 시점에 `token` 이벤트는 모두 끝나 `answerEl.textContent`가 완전한 답변 |
| 인용 추출 | `answerEl.textContent`에서 정규식 `/\[(\d+)\]/g`로 정수 집합 추출. `[1][2]`·`[1], [2]`·`[1]·[2]` 등 모두 포함. 존재하지 않는 index(예: `[9]`)는 무시 |
| 분류 | `cited = sources.filter(s => citedSet.has(s.index))`, `rest = 나머지`. 원래 `index` 순서 유지 |
| 인용 0개 | `cited`가 비면 **기존 동작** — 모든 카드를 펼쳐 표시, 접힘 영역 없음 |
| 인용 ≥1 | `cited` 카드를 먼저 렌더(클래스 `cited` 추가로 시각 강조), `rest`가 1개 이상이면 `<details>` 안에 `<summary>기타 참고 N건</summary>` + 카드들. `rest`가 0이면 `<details>` 생략 |
| 카드 내용 | 기존과 동일(`[index] title` 링크 새 탭, source 배지, snippet). **번호는 원래 `index` 그대로** — 답변의 `[n]`과 대응이 깨지지 않게 재번호 매기지 않음 |
| 삽입 방식 | 기존 규칙 유지 — `createElement`/`textContent`만, `innerHTML`에 서버 데이터 금지. `<details>`/`<summary>` 텍스트는 정적 문자열 + 숫자 |
| 강조 스타일 | `.src.cited` 테두리/배경 강조 1~2줄(기존 카드 클래스명이 `src` — 초안의 `.card.cited`는 변수명을 잘못 적은 것, Builder 지적으로 정정). `details.more summary` 커서·여백 1~2줄 |
| 오류·결과 없음 | `sources`가 빈 배열이면 기존과 동일하게 아무것도 렌더하지 않음 |

### 기각한 대안
- A(인용만 표시): 모델이 인용을 빠뜨리면 근거가 사라짐(Task 10 기각 이유와 동일). B는 접혀 있어도 전부 남는다.
- 서버에서 `cited` 플래그를 내려주기: `SourceRef` 계약 변경 + 모델 출력 파싱을 서버로 옮기는 것 — UI 표시 문제에 API 변경은 과함.
- `top-k` 축소(C): 응답 시간 단축 효과가 있어 별도 검토 가치는 있으나 ini 변경(사용자 결정)이고 복합 질문 근거 부족 위험. 이 티켓 범위 밖.

## 작업 목록 (Builder)

1. `index.html` `renderSources(container, sources)` 수정 — 위 동작 규칙대로. 기존 카드 생성 코드는 헬퍼(`buildCard(s)`)로 묶어 `cited`·`rest` 양쪽에서 재사용.
2. CSS: `.card.cited`, `details.more`/`summary` 최소 스타일.
3. 정적 확인: `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write` 부재, 외부 URL 부재(기존 규칙).
4. `pytest --active-profile=local test/test_web_ui.py test/test_ask_controller.py -v` → 기존 테스트 전부 PASS(계약·XSS 테스트가 새 코드에도 적용됨).
5. 전체 `pytest --active-profile=local -v` → 회귀 없음.
6. 완료 보고: diff, 참조(기존) 구현과 다른 점.

**하지 않을 것:** 커밋, 서버·DTO·SSE 변경, `top-k` ini 변경, 답변 텍스트 가공(인용 번호 제거 등), 서버 기동.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 회귀 없음 | 전체 green, `test_web_ui.py` 15개 유지 |
| 인용 파싱 존재 | `test_web_ui.py` 추가: `/\[(\d+)\]/` 정규식 사용, `cited`/`rest` 분류 코드 존재, `<details>`·`summary` 생성이 `createElement`로만 |
| 폴백 존재 | 인용 0개 시 전체 펼침 분기(`cited.length === 0` 류) 존재 |
| 번호 유지 | 카드 라벨이 `s.index`를 그대로 사용(재번호 없음) |
| XSS 규칙 | 서버 데이터 `innerHTML` 미삽입 유지 |
| **수동 확인(사용자)** | 서버 기동 후 "주제 생성 API 스펙 페이지 찾아줘"(소스: Confluence) → 인용된 카드가 위에 강조, "기타 참고 N건" 접힘; 접힘 클릭 시 펼침; 인용이 없는 답변(예: NOT_FOUND)에서는 접힘 영역 없음 |

## 완료 기준

- [x] 기존 테스트 전부 PASS + Validator 추가 정적 테스트 9건 PASS (전체 317 passed, 소켓 차단 동일)
- [x] 인용 카드 강조·나머지 접힘·인용 0개 폴백이 코드에 존재 — 뮤테이션 점검(재번호로 변형·폴백 삭제 시 테스트 실패)으로 테스트 유효성 확인
- [x] 카드 번호가 답변 `[n]`과 일치(재번호 패턴 부재, 부정 검사)
- [x] `innerHTML` 서버 데이터 미삽입, 외부 리소스 없음
- [ ] **사용자 육안 확인**(강조·접힘·펼침·인용 0개 시 접힘 없음) — 에이전트는 JS 실행 불가

## 판정

**조건부 READY FOR REVIEW** (2026-09-22). 코드·정적 계약 충족. 남은 조건: 사용자 육안 확인.

**설계 메모(Validator 비차단)**: `renderSources`가 `container`에 카드를 붙이면서 같은 요소의 텍스트를 인용 원본으로 쓰므로, `answerText`를 **인자로 미리 넘기는 현재 구조**가 카드 텍스트의 `[n]`이 인용으로 오인되는 것을 막는다. 향후 인자를 없애고 함수 안에서 `container.textContent`를 읽도록 바꾸면 버그가 된다 — 유지할 것.

커밋 대상: `resources/static/index.html`, `test/test_web_ui.py`.

## 진행 기록 (계속)
- 2026-09-22 Validator: 정적 테스트 +9(함수 본문 단위 검사, 재번호 부정 검사, 뮤테이션으로 유효성 확인). 317 passed. 사용자 서버 미접촉(5010 리스너 2개 = 리로더·워커 추정). 조건부 READY FOR REVIEW.

## 범위 제외

- 인용되지 않은 소스를 아예 숨기기(A)
- `top-k` 조정(C) — 응답 시간 관점 별도 검토
- 답변 텍스트 내 `[n]`을 카드로 링크(앵커) — 다음 개선 후보
- 커밋: 사용자

## 진행 기록

- 2026-09-22 리드: 사용자 결정 B. 명세 작성, Builder 지시.
- 2026-09-22 Builder 완료: `renderSources(container, sources, answerText)` + `buildCard`/`buildCardGrid` 헬퍼, CSS 3줄. 39 passed(web_ui+controller), 전체 308 passed. `node --check` 통과, DOM 스텁 6케이스(인용 2/1/0개, 없는 index 무시, 전부 인용, 빈 sources) 동작 확인. 기존과 다른 점 2건 — (1) `answerText` 인자 추가(호출부에서 `answerEl.textContent` 전달), (2) 클래스 `.src.cited`.
- 2026-09-22 리드: 2건 수용(명세 표기 정정). Validator에게 검증 지시.
