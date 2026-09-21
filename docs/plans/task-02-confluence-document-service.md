# Task 2: Confluence storage HTML → Markdown Document 변환

- 상위 계획: `docs/superpowers/plans/2026-09-17-kudos-rag-poc.md` §Task 2
- 설계 스펙: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`
- 선행: Task 1 (커밋됨). 단, 이 모듈은 `Profile`을 import하지 않으므로 Task 1 검증과 병행 가능.
- 상태: **구현 파일 존재(미커밋) — Builder가 마무리·확인 후 Validator 검증**

## 목표

Confluence REST v2가 돌려주는 storage format(XHTML) 페이지 목록을, 매크로를 정리한 Markdown `Document` 리스트로 변환한다. 이후 Task 6(청킹)·Task 9(인제스트)의 입력이 된다.

## 리드 판단 (2026-09-21)

`[검증]` 아래 파일이 이미 존재하고 내용이 상위 계획 Task 2 Step 2·4 코드와 동일하다. 모두 git 미추적 상태다.

- `src/service/__init__.py`, `src/service/confluence_document_service.py`
- `test/fixtures/confluence_storage_sample.html`
- `test/test_confluence_document_service.py`
- `requirements.in` 마지막 줄에 `beautifulsoup4` 추가됨 (`M` 상태). `requirements.txt`도 `M` 상태.

`[미확인]` 테스트 통과 여부, `requirements.txt`가 `pip-compile`로 재생성된 결과인지, 표(table) 변환 문자열이 markdownify 실제 출력과 일치하는지.

**결정:** Builder는 새로 작성하지 않고, 기존 파일을 명세 기준으로 확인·마무리한다. 코드 변경은 테스트가 실패하는 경우에만, 명세의 인터페이스를 유지하는 범위에서 한다.

## 설계

### 컴포넌트

`src/service/confluence_document_service.py` 단일 모듈. 외부 의존: `bs4.BeautifulSoup`, `markdownify.markdownify`, `langchain_core.documents.Document`. `Profile`·로거 사용 없음(순수 함수).

### 데이터 흐름

```
pages: list[dict] (Confluence v2 page 객체)
  └─ build_breadcrumbs(pages)          → {page_id: "상위 > 중위 > 제목"}
  └─ 각 page.body.storage.value
       └─ BeautifulSoup(html.parser)
       └─ _preprocess_macros(soup)     매크로/링크/첨부 정리 (아래 규칙)
       └─ markdownify(ATX, escape off) → Markdown
       └─ 빈 줄 3개 이상 → 2개
  └─ Document(page_content=md, metadata={...})
```

### 매크로 처리 규칙

| 대상 | 처리 |
|---|---|
| `ac:structured-macro[ac:name=code]` | `<pre data-lang=…>`로 치환 → 펜스 코드블록(` ```python `) |
| `info, note, warning, tip, expand, panel, excerpt, section, column` | `ac:rich-text-body` 내용만 남기고 껍데기 제거. 본문 없으면 통째로 제거 |
| 그 외 매크로(`toc` 등) | 통째로 제거 |
| `ac:link` | `ac:plain-text-link-body` → `ac:link-body` → `ri:page[ri:content-title]` 순으로 텍스트만 남김 |
| `ac:image`, `ri:attachment` | 제거 (PoC 범위 밖) |
| `escape_underscores/asterisks` | **False**. `company_seq` 같은 식별자가 `company\_seq`로 깨지면 BM25 매칭이 실패함 |

### 인터페이스 (Produces)

```python
SOURCE_CONFLUENCE = "confluence"

def convert_storage_to_markdown(storage_html: str) -> str
def build_breadcrumbs(pages: list[dict]) -> dict[str, str]
    # 부모가 목록에 없음(권한 등) 또는 순환 → 자기 제목만
def build_documents(pages: list[dict], base_url: str) -> list[Document]
```

`pages` 원소 형식(Confluence v2, `body-format=storage`):
`id`, `title`, `parentId`(nullable), `version.number`, `version.createdAt`, `body.storage.value`, `_links.webui`

`Document.metadata` (Chroma 제약상 `str|int|float|bool`만, `None` 금지):

| key | 타입 | 값 |
|---|---|---|
| `source` | str | `"confluence"` |
| `doc_id` | str | `str(page.id)` |
| `title` | str | `page.title` |
| `url` | str | `f"{base_url}{_links.webui}"` |
| `breadcrumb` | str | `build_breadcrumbs` 결과 |
| `version` | int | `version.number` (없으면 0) |
| `last_modified` | str | `version.createdAt` (없으면 `""`) |

### 의존성

`requirements.in`에 `beautifulsoup4` 명시 (markdownify의 전이 의존성이지만 직접 import하므로). 반영 절차:
```bash
source .venv/bin/activate && pip-compile --quiet --output-file=requirements.txt requirements.in && pip install -q -r requirements.txt
```

### 기각한 대안

- Confluence `body-format=view`(렌더링된 HTML) 사용: 매크로가 이미 HTML로 풀려 있어 처리는 쉽지만, 코드블록 언어·페이지 링크 대상 제목 등 구조 정보가 손실됨. storage format 유지.
- `html2text` 등 다른 변환기: 이미 `markdownify`가 의존성에 있음(§7 새 의존성 금지).

## 작업 목록 (Builder)

1. `requirements.txt` 정합성 확인: `beautifulsoup4` 항목이 있고 주석에 `# via -r requirements.in` 형태로 직접 의존성이 표시되는지 확인. 아니면 위 pip-compile 명령 실행. **`requirements.in`에 `beautifulsoup4` 외 다른 줄을 추가·삭제하지 않는다.**
2. `pytest --active-profile=local test/test_confluence_document_service.py -v` 실행.
3. 7 PASSED면 코드 변경 없이 보고. 실패 시:
   - `test_headings_and_table_preserved`의 표 문자열 실패 → markdownify 실제 출력을 확인해 **테스트의 기대 문자열만** 실제 출력에 맞춘다(표 내용 보존이 요구사항, 정확한 공백 수는 아님). 코드는 바꾸지 않는다.
   - 그 외 실패 → 원인·재현 결과를 리드에게 보고하고 대기. 인터페이스나 매크로 규칙을 임의로 바꾸지 않는다.
4. `pytest --active-profile=local -v` 전체 실행하여 Task 1 테스트 포함 회귀 없음 확인.
5. 완료 보고: 실행한 명령과 결과, 변경한 파일 목록(없으면 "없음").

**하지 않을 것:** 커밋(`git add/commit`), `src/` 다른 모듈 생성, 설정파일 수정, 코드 정리/리팩터링.

## 검증 전략 (Validator)

| 완료 기준 | 검증 방법 |
|---|---|
| 7개 테스트 통과 | `source .venv/bin/activate && pytest --active-profile=local test/test_confluence_document_service.py -v` |
| 회귀 없음 | `pytest --active-profile=local -v` 전체 green (Task 1 4개 + Task 2 7개 = 11) |
| 네트워크·Ollama 불필요 | 위 테스트를 오프라인/Ollama 미기동 상태로 실행 |
| 코드 매크로 → 펜스 블록 | `test_code_macro_becomes_fenced_block` |
| toc 제거·info 본문 유지 | `test_toc_macro_removed_and_info_body_kept` |
| 페이지 링크 텍스트화 | `test_page_link_becomes_text` |
| 식별자 이스케이프 없음 | `test_identifiers_are_not_escaped` |
| breadcrumb 체인·순환 방지 | `test_build_breadcrumbs_follows_parent_chain` + 추가 확인: 순환(`1→2→1`)과 부모 누락 케이스를 REPL/임시 테스트로 실행해 무한 재귀 없이 자기 제목 반환 |
| metadata에 `None` 없음 | `version`/`_links` 누락 페이지를 `build_documents`에 넣어 모든 metadata 값이 `str|int` 인지 확인 (Chroma 제약) |
| 의존성 파일 정합성 | `requirements.txt`에 `beautifulsoup4` 존재, `requirements.in` diff가 `+beautifulsoup4` 한 줄뿐 (`git diff requirements.in`) |
| 구현이 명세와 일치 | 이 문서 "인터페이스"·"매크로 처리 규칙"과 코드 대조 |

Validator가 추가 테스트를 작성할 경우 `test/test_confluence_document_service.py`에 추가하고, 애플리케이션 코드는 수정하지 않는다.

## 완료 기준

- [x] `test/test_confluence_document_service.py` 7 PASSED (Validator 추가 후 21 passed)
- [x] 전체 `pytest --active-profile=local` green (38 passed)
- [x] Ollama·네트워크 없이 통과 (소켓 전면 차단 상태에서 통과)
- [x] `requirements.txt`에 `beautifulsoup4==4.15.0` 반영(`# via -r requirements.in, markdownify`), `requirements.in` 변경은 `+beautifulsoup4` 한 줄
- [x] `build_documents` metadata 값에 `None` 없음 (sparse 페이지 입력으로 확인)
- [x] 순환 부모(상호·자기참조)·부모 누락 시 무한 재귀 없음
- [x] 구현이 이 문서의 인터페이스·규칙과 일치

## 범위 제외

- Confluence REST 호출·인증·페이지네이션 → Task 3
- 이미지/첨부파일 내용 추출
- 청킹, 청크 id 부여 → Task 6
- `ac:structured-macro` 이외의 매크로 문법(`ac:macro`, 레거시 wiki markup)
- 커밋: 사용자가 직접 수행

## 리드 결정: 순환 부모 그래프에서의 breadcrumb 결과 (2026-09-21)

Builder 보고: `build_breadcrumbs`의 `crumbs` 캐시는 특정 `seen` 경로에서 계산된 값을 저장하므로, 순환 그래프(`1→2→1`)에서는 `pages` 순서에 따라 결과 문자열이 달라질 수 있다. 무한 재귀는 없음(`[검증]` Builder 확인).

**결정: 코드 변경 없음.** 근거:
- Confluence 페이지 트리는 부모가 단일이고 순환이 생기지 않는 구조라 실데이터에 순환 입력은 없다. 방어 코드의 목적은 "무한 재귀 방지"이며 그 요구는 충족된다.
- 순환 시 어느 노드를 잘라 어떤 문자열을 만들지는 검색 품질에 영향 없는 임의 규칙이므로, 결정성 보장을 위한 코드 추가는 §4(불가능한 상황을 위한 과도한 방어) 위반이다.
- 완료 기준 "순환 부모·부모 누락 시 무한 재귀 없음"은 그대로 유지하고, 문자열 결정성은 요구하지 않는다.

Validator는 순환 케이스 검증 시 "예외·무한 재귀 없이 반환된다"만 확인하고, 반환 문자열의 특정 값은 assert하지 않는다.

## 진행 기록

- 2026-09-21 리드: 미커밋 구현 파일 확인, 계획 코드와 동일. Builder에게 마무리·확인 지시.
- 2026-09-21 Builder 완료 보고: `requirements.txt`에 `beautifulsoup4==4.15.0` (`# via -r requirements.in`) 존재 → pip-compile 재실행 불필요. `test_confluence_document_service.py` 7 passed, 전체 11 passed(Task 1 4 + Task 2 7). Ollama·네트워크 없이 통과. 변경 파일 없음, 커밋 없음.
- 2026-09-21 리드: 순환 그래프 결정성 질의 → 코드 변경 없음으로 결정(위 절). Validator에게 Task 2 검증 지시.
- 2026-09-21 Validator 회차 1: 완료 기준 전부 PASS. `test/test_confluence_document_service.py` +14. 발견 버그 없음.
- 2026-09-21 리드 판단(비차단 의견): `int(version.get("number", 0))`는 `version.number`가 명시적 `null`이면 TypeError — `[추측]` Confluence v2 `pages` 응답의 `version.number`는 항상 정수라 발생하지 않을 것으로 보고 변경하지 않는다. Task 9(인제스트) 실데이터 연동 시 예외가 나오면 그 티켓에서 처리.

## 리뷰 1 후속 (2026-09-21)

`[검증]` body-only 매크로의 `ac:parameter`(title 등) 텍스트가 본문으로 새는 결함 발견 — 매크로 처리 표와 불일치. 수정 지시: `docs/plans/review-01-task1-5.md` 조치 A. 완료 시 이 문서 매크로 표의 body-only 행은 "파라미터 제거 + `ac:rich-text-body` 내용만 유지"로 읽는다.

## 판정

**READY FOR REVIEW** (2026-09-21, 검증 회차 1 + 리뷰 1 조치 A 반영). 리뷰 1 조치 A(파라미터 텍스트 누출 수정) 반영본 기준으로 confluence 테스트 25 passed, 전체 119 passed. 설계 문서와 구현 일치.
→ **리뷰 1 통과 (2026-09-21) — 커밋 대기.**

커밋 대상(사용자 수행): `requirements.in`, `requirements.txt`, `src/service/`, `test/fixtures/`, `test/test_confluence_document_service.py`, 그리고 Validator가 추가한 `test/test_profile.py`(수정), `test/test_global_logger.py`(신규).
