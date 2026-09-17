# KUDOS RAG PoC 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팀 Confluence `KUDOS` 스페이스 페이지와 팀 FastAPI 서비스 OpenAPI 스펙을 로컬 Ollama 기반으로 인제스트·검색·답변하는 RAG PoC(인제스트 CLI + FastAPI `/v1/ask` + 최소 웹 UI)를 만든다.

**Architecture:** 인제스트 CLI(`ingest.py`)가 Confluence REST v2와 OpenAPI URL에서 문서를 수집해 Markdown Document로 정규화하고, 헤딩 기반 청킹 후 `bge-m3` 임베딩으로 Chroma(로컬 persist)에 증분 저장한다. 서빙(`main.py`)은 기동 시 Chroma 전체 청크로 BM25 인메모리 인덱스를 만들고, BM25+벡터 하이브리드(RRF) 검색 결과를 `qwen3:14b`에 전달해 근거 인용이 포함된 답변을 반환한다. 두 프로세스는 Chroma 디렉터리만 공유한다.

**Tech Stack:** Python 3.12, FastAPI, LangChain 1.x (`langchain-core`, `langchain-community`, `langchain-classic`, `langchain-text-splitters`, `langchain-ollama`, `langchain-chroma`), chromadb, rank-bm25, markdownify(+beautifulsoup4), requests, PyYAML, pytest

**Spec:** `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`

## Global Constraints

- 사내 문서를 외부 LLM/임베딩 API로 전송하지 않는다. LLM/임베딩은 로컬 Ollama(`base-url=http://127.0.0.1:11434`)만 사용한다.
- LLM/임베딩 객체 생성은 `src/service/llm_factory.py` 한 곳에서만 수행한다.
- LangChain 1.x import 경로 고정: `EnsembleRetriever` → `langchain_classic.retrievers`, `BM25Retriever` → `langchain_community.retrievers`, 스플리터 → `langchain_text_splitters`, `ChatOllama`/`OllamaEmbeddings` → `langchain_ollama`, `Chroma` → `langchain_chroma`, `Document` → `langchain_core.documents`.
- 코드 컨벤션은 `ailab_general_chatbot`과 동일: `--active-profile` 인자, `resources/config_{profile}.ini`, `Profile` 싱글톤(`advanced_python_singleton`), 디렉터리 `src/{config,controller,dto,repository,service,library}`.
- 새로 작성하는 주석·docstring·커밋 메시지는 한국어. 코드 identifier는 영어.
- 의존성 추가는 `requirements.in`에 추가 후 `pip-compile --output-file=requirements.txt requirements.in` → `pip install -r requirements.txt`. 이미 설치된 패키지 외 추가 필요 시 해당 Task에 명시.
- 테스트 실행: 프로젝트 루트에서 `source .venv/bin/activate && pytest --active-profile=local <path> -v`. 단위 테스트는 Ollama·네트워크 없이 통과해야 한다. Ollama가 필요한 테스트는 `@pytest.mark.integration`으로 표시하고 기본 실행에서 제외한다.
- Chroma 메타데이터 값은 `str|int|float|bool`만 허용된다. `None`은 넣지 않고 리스트는 쉼표 결합 문자열로 저장한다.
- Chroma 컬렉션 이름은 3~512자(`[a-zA-Z0-9._-]`, 영숫자로 시작·종료)여야 한다(`[검증]` chromadb 1.5.9에서 `"c"` 같은 1글자 이름은 `InvalidArgumentError`). 테스트에서도 `test_col` 같은 이름을 쓴다.
- 커밋: 각 Task 마지막 Step에서 커밋. 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 추가.
- 설정파일(`resources/*.ini`, `openapi_sources.yaml`)의 값은 spec §9 값을 그대로 사용한다. 인증 정보는 커밋하지 않는다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `global_variable.py` | `PROJECT_ROOT_DIR`, `PROJECT_RESOURCE_DIR` 상수 |
| `src/config/argument.py` | `--active-profile` 커맨드라인 인자 파싱 싱글톤 |
| `src/config/profile.py` | ini 로딩, `{project_root}` 치환, 섹션 dict 반환 |
| `src/library/global_logger.py` | `logging` 기반 로거 팩토리 |
| `resources/config_local.ini`, `resources/openapi_sources.yaml` | 설정 |
| `src/repository/confluence_repository.py` | Confluence REST v2 호출(인증·페이지네이션·재시도) |
| `src/service/confluence_document_service.py` | storage HTML → Markdown, breadcrumb, `Document` 생성 |
| `src/repository/openapi_repository.py` | `openapi_sources.yaml` 로딩, 스펙 다운로드 |
| `src/service/openapi_document_service.py` | OpenAPI → endpoint/schema `Document` 렌더링 |
| `src/service/chunk_service.py` | Markdown 헤딩 기반 청킹, 청크 id 부여 |
| `src/service/llm_factory.py` | `ChatOllama`, `OllamaEmbeddings` 생성 |
| `src/repository/vector_store_repository.py` | Chroma upsert/delete/get_all/reset |
| `src/service/manifest.py` | `data/manifest.json` 읽기/쓰기/diff |
| `src/service/ingest_service.py` | 소스별 수집→청킹→증분 인덱싱 오케스트레이션 |
| `ingest.py` | 인제스트 CLI 진입점 |
| `src/service/retriever_service.py` | BM25 토크나이저, 소스별 BM25 인덱스, 하이브리드 검색 |
| `src/service/rag_service.py` | 프롬프트 조립, LLM 호출, 스트리밍 |
| `src/dto/ask_dto.py` | `AskRequest`, `AskResponse`, `SourceRef` |
| `src/controller/ask_controller.py` | `/v1/ask`, `/v1/ask/stream`, `/v1/reload`, `/check` |
| `main.py` | FastAPI 앱 진입점, 정적 파일, Swagger |
| `resources/static/index.html` | 최소 채팅 UI |
| `eval/questions.yaml`, `eval/run_eval.py` | 검색 품질 평가 |
| `README.md` | 실행 방법 |

---

### Task 1: 프로젝트 골격 (Profile, 인자, 로거, 설정 파일, pytest)

**Files:**
- Create: `global_variable.py`
- Create: `src/__init__.py`, `src/config/__init__.py`, `src/config/argument.py`, `src/config/profile.py`
- Create: `src/library/__init__.py`, `src/library/global_logger.py`
- Create: `resources/config_local.ini`, `resources/openapi_sources.yaml`
- Create: `pytest.ini`, `test/__init__.py`, `test/conftest.py`
- Test: `test/test_profile.py`

**Interfaces:**
- Produces:
  - `global_variable.PROJECT_ROOT_DIR: str`, `global_variable.PROJECT_RESOURCE_DIR: str`
  - `CommandlineArgument().get_active_profile() -> str`
  - `Profile().get_config(section: str) -> dict[str, str]` — `{project_root}`가 실제 경로로 치환된 값
  - `Profile().get_common_config() -> dict[str, str]`, `Profile().api_root: str`, `Profile().active_profile: str`
  - `Profile.get_value(config: dict, key: str, default=None)`
  - `GlobalLogger.get_logger(name: str) -> logging.Logger`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/conftest.py`:
```python
def pytest_addoption(parser):
    parser.addoption("--active-profile", action="store", default="local")
```

`pytest.ini`:
```ini
[pytest]
asyncio_default_fixture_loop_scope = function
markers =
    integration: Ollama 등 외부 프로세스가 필요한 테스트 (기본 실행에서 제외)
addopts = -m "not integration"
```

`test/__init__.py`, `src/__init__.py`, `src/config/__init__.py`, `src/library/__init__.py`: 빈 파일.

`test/test_profile.py`:
```python
import global_variable
from src.config.profile import Profile


def test_active_profile_is_local():
    assert Profile().active_profile == "local"


def test_project_root_placeholder_is_replaced():
    chroma = Profile().get_config("chroma")
    assert "{project_root}" not in chroma["persist-dir"]
    assert chroma["persist-dir"].startswith(global_variable.PROJECT_ROOT_DIR)


def test_retrieval_config_has_expected_keys():
    retrieval = Profile().get_config("retrieval")
    assert retrieval["top-k"] == "6"
    assert Profile.get_value(retrieval, "missing-key", "fallback") == "fallback"


def test_common_config():
    assert Profile().api_root == "v1"
    assert Profile().get_common_config()["health_check_endpoint"] == "check"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `source .venv/bin/activate && pytest --active-profile=local test/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'global_variable'`

- [ ] **Step 3: 구현**

`global_variable.py`:
```python
import os

PROJECT_ROOT_DIR = os.path.dirname(os.path.abspath(__file__)).replace(os.sep, "/")
PROJECT_RESOURCE_DIR = f"{PROJECT_ROOT_DIR}/resources"
```

`src/config/argument.py`:
```python
import argparse

from advanced_python_singleton.singleton import Singleton


class CommandlineArgument(metaclass=Singleton):
    """--active-profile 인자를 한 번만 파싱해 보관한다. pytest/uvicorn 등 다른 인자는 무시한다."""

    def __init__(self):
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--active-profile", dest="active_profile", default="local")
        args, _ = parser.parse_known_args()
        self.__active_profile = args.active_profile

    def get_active_profile(self) -> str:
        return self.__active_profile
```

`src/config/profile.py`:
```python
import configparser

from advanced_python_singleton.singleton import Singleton

import global_variable
from src.config.argument import CommandlineArgument


class Profile(metaclass=Singleton):
    """resources/config_{profile}.ini 를 읽어 섹션 단위 dict 로 제공한다."""

    __CONFIG_PROFILE_PATH = "{dir}/config_{profile}.ini"
    __CONFIG_SECTION_COMMON = "common"
    __CONFIG_API_ROOT = "api-root"
    __PLACEHOLDER_PROJECT_ROOT = "{project_root}"

    def __init__(self):
        self.active_profile = CommandlineArgument().get_active_profile()
        # 값 안의 '%' 를 보간하지 않도록 interpolation 을 끈다
        self.__config = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
        self.__config.read(
            self.__CONFIG_PROFILE_PATH.format(dir=global_variable.PROJECT_RESOURCE_DIR, profile=self.active_profile),
            encoding="utf-8",
        )
        self.__common_config = self.get_config(self.__CONFIG_SECTION_COMMON)
        self.api_root = self.__common_config[self.__CONFIG_API_ROOT]

    def get_config(self, section: str) -> dict:
        return {
            key: value.replace(self.__PLACEHOLDER_PROJECT_ROOT, global_variable.PROJECT_ROOT_DIR)
            for key, value in self.__config.items(section)
        }

    def get_common_config(self) -> dict:
        return self.__common_config

    @staticmethod
    def get_value(config: dict, key: str, default=None):
        return config[key] if key in config else default
```

`src/library/global_logger.py`:
```python
import logging
import os

from src.config.profile import Profile


class GlobalLogger:
    """프로파일의 log-level / log-file-path 설정을 따르는 로거를 반환한다."""

    __configured = False

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        if not cls.__configured:
            common = Profile().get_common_config()
            log_dir = common["log-file-path"]
            os.makedirs(log_dir, exist_ok=True)
            handlers = [logging.StreamHandler(), logging.FileHandler(f"{log_dir}/app.log", encoding="utf-8")]
            logging.basicConfig(
                level=getattr(logging, common.get("log-level", "INFO").upper(), logging.INFO),
                format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                handlers=handlers,
            )
            cls.__configured = True
        return logging.getLogger(name)
```

`resources/config_local.ini`:
```ini
[common]
log-level=DEBUG
log-file-path={project_root}/logs
version=1.0
api-root=v1
health_check_endpoint=check

[swagger]
title=KUDOS RAG API
summary=팀 Confluence + OpenAPI 기반 RAG (local)

[fastapi]
host=127.0.0.1
port=5010
reload=True

[ollama]
base-url=http://127.0.0.1:11434
llm-model=qwen3:14b
embedding-model=bge-m3
num-ctx=16384
temperature=0
llm-timeout=120

[chroma]
persist-dir={project_root}/data/chroma
collection=kudos_rag
manifest-path={project_root}/data/manifest.json

[confluence]
base-url=https://ihunet.atlassian.net/wiki
space-key=KUDOS
email=
api-token=

[openapi]
sources-file={project_root}/resources/openapi_sources.yaml

[retrieval]
chunk-size=1000
chunk-overlap=150
top-k=6
bm25-k=10
vector-k=10
bm25-weight=0.4
vector-weight=0.6
embed-batch-size=32
```

`resources/openapi_sources.yaml`:
```yaml
sources:
  - name: general-chatbot-api
    spec_url: https://qa-general-chatbot-api.hunet.ai/openapi.json
    docs_url: https://qa-general-chatbot-api.hunet.ai/docs
  - name: message-api
    spec_url: https://message-api.qa.hunet.io/openapi.json
    docs_url: https://message-api.qa.hunet.io/docs
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_profile.py -v`
Expected: 4 PASSED

- [ ] **Step 5: 커밋**

```bash
git add global_variable.py src/ resources/ pytest.ini test/
git commit -m "$(cat <<'EOF'
프로젝트 골격 추가: Profile/인자/로거/설정 파일/pytest 구성

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Confluence storage HTML → Markdown Document 변환

**Files:**
- Modify: `requirements.in` (`beautifulsoup4` 추가 — markdownify 의존성으로 이미 설치돼 있으나 직접 import 하므로 명시)
- Create: `src/service/__init__.py`, `src/service/confluence_document_service.py`
- Create: `test/fixtures/confluence_storage_sample.html`
- Test: `test/test_confluence_document_service.py`

**Interfaces:**
- Consumes: 없음(순수 함수)
- Produces:
  - `convert_storage_to_markdown(storage_html: str) -> str`
  - `build_breadcrumbs(pages: list[dict]) -> dict[str, str]` — `page_id → "상위 > 중위 > 제목"`
  - `build_documents(pages: list[dict], base_url: str) -> list[Document]` — `pages`는 Confluence v2 페이지 객체(`id`, `title`, `parentId`, `version.number`, `version.createdAt`, `body.storage.value`, `_links.webui`). metadata: `source="confluence"`, `doc_id`, `title`, `url`, `breadcrumb`, `version:int`, `last_modified`

- [ ] **Step 1: requirements.in 갱신**

`requirements.in`에 `beautifulsoup4` 한 줄 추가 후:
```bash
source .venv/bin/activate && pip-compile --quiet --output-file=requirements.txt requirements.in && pip install -q -r requirements.txt
```

- [ ] **Step 2: 픽스처와 실패하는 테스트 작성**

`test/fixtures/confluence_storage_sample.html`:
```html
<h1>인증 서버 연동</h1>
<p>본 문서는 <strong>GW</strong> 연동 절차를 설명한다.</p>
<ac:structured-macro ac:name="toc"><ac:parameter ac:name="maxLevel">2</ac:parameter></ac:structured-macro>
<h2>요청 예시</h2>
<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body><![CDATA[import requests
requests.post("/v1/messages/message", json={"a": 1})]]></ac:plain-text-body></ac:structured-macro>
<h2>환경 정보</h2>
<table><tbody>
<tr><th>환경</th><th>호스트</th></tr>
<tr><td>qa</td><td>message-api.qa.hunet.io</td></tr>
</tbody></table>
<ac:structured-macro ac:name="info"><ac:rich-text-body><p>토큰은 헤더로 전달한다.</p></ac:rich-text-body></ac:structured-macro>
<p>참고: <ac:link><ri:page ri:content-title="회원 · 인증(IAM) 서비스 정책" /><ac:plain-text-link-body><![CDATA[IAM 정책]]></ac:plain-text-link-body></ac:link></p>
```

`test/test_confluence_document_service.py`:
```python
from pathlib import Path

from src.service.confluence_document_service import (
    build_breadcrumbs,
    build_documents,
    convert_storage_to_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures" / "confluence_storage_sample.html"


def test_code_macro_becomes_fenced_block():
    md = convert_storage_to_markdown(FIXTURE.read_text(encoding="utf-8"))
    assert "```python" in md
    assert 'requests.post("/v1/messages/message"' in md


def test_headings_and_table_preserved():
    md = convert_storage_to_markdown(FIXTURE.read_text(encoding="utf-8"))
    assert "# 인증 서버 연동" in md
    assert "## 환경 정보" in md
    assert "| qa | message-api.qa.hunet.io |" in md


def test_toc_macro_removed_and_info_body_kept():
    md = convert_storage_to_markdown(FIXTURE.read_text(encoding="utf-8"))
    assert "maxLevel" not in md
    assert "토큰은 헤더로 전달한다." in md


def test_page_link_becomes_text():
    md = convert_storage_to_markdown(FIXTURE.read_text(encoding="utf-8"))
    assert "IAM 정책" in md
    assert "ri:page" not in md


def test_identifiers_are_not_escaped():
    md = convert_storage_to_markdown("<p>company_seq - affiliated_company_seq 정의 (별표 * 표시)</p>")
    assert "company_seq - affiliated_company_seq" in md
    assert "\\_" not in md and "\\*" not in md


def _page(page_id, title, parent_id=None, body="<p>본문</p>"):
    return {
        "id": page_id,
        "title": title,
        "parentId": parent_id,
        "version": {"number": 3, "createdAt": "2026-09-15T01:00:00.000Z"},
        "body": {"storage": {"value": body}},
        "_links": {"webui": f"/spaces/KUDOS/pages/{page_id}"},
    }


def test_build_breadcrumbs_follows_parent_chain():
    pages = [_page("1", "루트"), _page("2", "중간", "1"), _page("3", "리프", "2")]
    crumbs = build_breadcrumbs(pages)
    assert crumbs["3"] == "루트 > 중간 > 리프"
    assert crumbs["1"] == "루트"


def test_build_documents_metadata():
    pages = [_page("1", "루트"), _page("2", "리프", "1", "<h2>섹션</h2><p>내용</p>")]
    docs = build_documents(pages, base_url="https://ihunet.atlassian.net/wiki")
    leaf = next(d for d in docs if d.metadata["doc_id"] == "2")
    assert leaf.metadata["source"] == "confluence"
    assert leaf.metadata["title"] == "리프"
    assert leaf.metadata["breadcrumb"] == "루트 > 리프"
    assert leaf.metadata["url"] == "https://ihunet.atlassian.net/wiki/spaces/KUDOS/pages/2"
    assert leaf.metadata["version"] == 3
    assert leaf.metadata["last_modified"] == "2026-09-15T01:00:00.000Z"
    assert "## 섹션" in leaf.page_content
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_confluence_document_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.service.confluence_document_service'`

- [ ] **Step 4: 구현**

`src/service/__init__.py`: 빈 파일.

`src/service/confluence_document_service.py`:
```python
"""Confluence storage format(XHTML) 페이지를 Markdown Document 로 변환한다."""
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from markdownify import markdownify

SOURCE_CONFLUENCE = "confluence"
# 내부 본문(rich-text-body)만 남기고 껍데기를 벗길 매크로. 그 외 이름은 통째로 제거한다.
_BODY_ONLY_MACROS = {"info", "note", "warning", "tip", "expand", "panel", "excerpt", "section", "column"}


def _preprocess_macros(soup: BeautifulSoup) -> None:
    for macro in list(soup.find_all("ac:structured-macro")):
        name = macro.get("ac:name", "")
        if name == "code":
            lang_param = macro.find("ac:parameter", attrs={"ac:name": "language"})
            lang = lang_param.get_text(strip=True) if lang_param else ""
            body = macro.find("ac:plain-text-body")
            code = body.get_text() if body else ""
            pre = soup.new_tag("pre")
            pre["data-lang"] = lang
            pre.string = code
            macro.replace_with(pre)
        elif name in _BODY_ONLY_MACROS:
            body = macro.find("ac:rich-text-body")
            if body:
                body.unwrap()
                macro.unwrap()
            else:
                macro.decompose()
        else:
            macro.decompose()

    # 페이지 링크는 표시 텍스트(없으면 대상 제목)만 남긴다
    for link in list(soup.find_all("ac:link")):
        body = link.find("ac:plain-text-link-body") or link.find("ac:link-body")
        ri_page = link.find("ri:page")
        text = body.get_text() if body else (ri_page.get("ri:content-title", "") if ri_page else "")
        link.replace_with(soup.new_string(text))

    # 이미지 등 첨부 참조는 PoC 범위 밖 → 제거
    for tag in list(soup.find_all(["ac:image", "ri:attachment"])):
        tag.decompose()


def convert_storage_to_markdown(storage_html: str) -> str:
    soup = BeautifulSoup(storage_html, "html.parser")
    _preprocess_macros(soup)
    md = markdownify(
        str(soup),
        heading_style="ATX",
        code_language_callback=lambda el: el.get("data-lang") or "",
        strip=["ac:parameter"],
        # company_seq → company\_seq 처럼 식별자가 깨지면 BM25 매칭이 실패하므로 이스케이프를 끈다
        escape_underscores=False,
        escape_asterisks=False,
    )
    # 빈 줄 3개 이상은 2개로 정리
    lines = [line.rstrip() for line in md.splitlines()]
    cleaned, blank = [], 0
    for line in lines:
        blank = blank + 1 if not line else 0
        if blank <= 2:
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def build_breadcrumbs(pages: list[dict]) -> dict[str, str]:
    by_id = {str(p["id"]): p for p in pages}
    crumbs: dict[str, str] = {}

    def crumb(page_id: str, seen: set) -> str:
        if page_id in crumbs:
            return crumbs[page_id]
        page = by_id[page_id]
        parent_id = page.get("parentId")
        parent_id = str(parent_id) if parent_id else None
        title = page["title"]
        # 부모가 목록에 없거나(권한 등) 순환이면 자기 제목만
        if parent_id and parent_id in by_id and parent_id not in seen:
            title = f"{crumb(parent_id, seen | {page_id})} > {title}"
        crumbs[page_id] = title
        return title

    for pid in by_id:
        crumb(pid, {pid})
    return crumbs


def build_documents(pages: list[dict], base_url: str) -> list[Document]:
    crumbs = build_breadcrumbs(pages)
    docs = []
    for page in pages:
        page_id = str(page["id"])
        storage = page.get("body", {}).get("storage", {}).get("value", "") or ""
        version = page.get("version", {}) or {}
        docs.append(
            Document(
                page_content=convert_storage_to_markdown(storage),
                metadata={
                    "source": SOURCE_CONFLUENCE,
                    "doc_id": page_id,
                    "title": page["title"],
                    "url": f"{base_url}{page.get('_links', {}).get('webui', '')}",
                    "breadcrumb": crumbs[page_id],
                    "version": int(version.get("number", 0)),
                    "last_modified": version.get("createdAt", "") or "",
                },
            )
        )
    return docs
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_confluence_document_service.py -v`
Expected: 7 PASSED. 표 변환 assert가 실패하면 markdownify 출력의 셀 공백 형식을 확인해 테스트의 기대 문자열을 실제 출력(`| qa | message-api.qa.hunet.io |`)에 맞춘다 — 표 내용이 보존되는 것이 요구사항이고 정확한 공백 수는 아니다.

- [ ] **Step 6: 커밋**

```bash
git add requirements.in requirements.txt src/service/ test/
git commit -m "$(cat <<'EOF'
Confluence storage HTML → Markdown Document 변환 서비스 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Confluence REST 저장소 (인증·페이지네이션·재시도)

**Files:**
- Create: `src/repository/__init__.py`, `src/repository/confluence_repository.py`
- Test: `test/test_confluence_repository.py`

**Interfaces:**
- Consumes: `Profile().get_config("confluence")` (Task 1)
- Produces:
  - `class ConfluenceAuthError(Exception)`, `class ConfluenceFetchError(Exception)`
  - `ConfluenceRepository(base_url: str, space_key: str, email: str, api_token: str, session=None, sleep=time.sleep)`
  - `ConfluenceRepository.from_profile() -> ConfluenceRepository` — 토큰은 환경변수 `CONFLUENCE_API_TOKEN` 우선
  - `.fetch_space_id() -> str`
  - `.fetch_pages() -> list[dict]` — `status=current`, `body-format=storage` 페이지 객체 전체(Task 2 `build_documents` 입력 형식)

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_confluence_repository.py`:
```python
import pytest

from src.repository.confluence_repository import (
    ConfluenceAuthError,
    ConfluenceFetchError,
    ConfluenceRepository,
)

BASE = "https://ihunet.atlassian.net/wiki"


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    """호출 순서대로 미리 정해둔 응답을 돌려주는 세션."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.auth = None

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


def _repo(session):
    return ConfluenceRepository(BASE, "KUDOS", "me@hunet.co.kr", "token", session=session, sleep=lambda s: None)


def test_fetch_space_id():
    session = FakeSession([FakeResponse(200, {"results": [{"id": "622596", "key": "KUDOS"}]})])
    assert _repo(session).fetch_space_id() == "622596"
    url, params = session.calls[0]
    assert url == f"{BASE}/api/v2/spaces"
    assert params["keys"] == "KUDOS"


def test_fetch_pages_follows_cursor():
    session = FakeSession([
        FakeResponse(200, {"results": [{"id": "622596"}]}),
        FakeResponse(200, {"results": [{"id": "1", "title": "a"}],
                           "_links": {"next": "/wiki/api/v2/spaces/622596/pages?cursor=abc&limit=250"}}),
        FakeResponse(200, {"results": [{"id": "2", "title": "b"}], "_links": {}}),
    ])
    pages = _repo(session).fetch_pages()
    assert [p["id"] for p in pages] == ["1", "2"]
    first_url, first_params = session.calls[1]
    assert first_url == f"{BASE}/api/v2/spaces/622596/pages"
    assert first_params == {"status": "current", "body-format": "storage", "limit": 250}
    # next 링크는 사이트 루트 기준 절대 경로이므로 그대로 이어 붙인다
    assert session.calls[2][0] == "https://ihunet.atlassian.net/wiki/api/v2/spaces/622596/pages?cursor=abc&limit=250"


def test_auth_error_raises_immediately():
    session = FakeSession([FakeResponse(401)])
    with pytest.raises(ConfluenceAuthError):
        _repo(session).fetch_space_id()
    assert len(session.calls) == 1


def test_retries_on_429_then_succeeds():
    session = FakeSession([FakeResponse(429), FakeResponse(503),
                           FakeResponse(200, {"results": [{"id": "9"}]})])
    assert _repo(session).fetch_space_id() == "9"
    assert len(session.calls) == 3


def test_gives_up_after_three_failures():
    session = FakeSession([FakeResponse(500), FakeResponse(500), FakeResponse(500)])
    with pytest.raises(ConfluenceFetchError):
        _repo(session).fetch_space_id()


def test_space_not_found():
    session = FakeSession([FakeResponse(200, {"results": []})])
    with pytest.raises(ConfluenceFetchError):
        _repo(session).fetch_space_id()


def test_from_profile_prefers_env_token(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "env-token")
    repo = ConfluenceRepository.from_profile()
    assert repo.api_token == "env-token"
    assert repo.space_key == "KUDOS"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_confluence_repository.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/repository/__init__.py`: 빈 파일.

`src/repository/confluence_repository.py`:
```python
"""Confluence Cloud REST API v2 호출. 인증·페이지네이션·재시도를 담당한다."""
import os
import time

import requests

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger

logger = GlobalLogger.get_logger(__name__)

_PAGE_LIMIT = 250
_MAX_ATTEMPTS = 3
_TIMEOUT_SEC = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ConfluenceAuthError(Exception):
    pass


class ConfluenceFetchError(Exception):
    pass


class ConfluenceRepository:
    def __init__(self, base_url: str, space_key: str, email: str, api_token: str, session=None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        # _links.next 는 "/wiki/api/v2/..." 형태의 사이트 루트 기준 경로
        self._site_root = self.base_url[: -len("/wiki")] if self.base_url.endswith("/wiki") else self.base_url
        self.space_key = space_key
        self.email = email
        self.api_token = api_token
        self._sleep = sleep
        self._session = session or requests.Session()
        self._session.auth = (email, api_token)

    @classmethod
    def from_profile(cls) -> "ConfluenceRepository":
        config = Profile().get_config("confluence")
        token = os.environ.get("CONFLUENCE_API_TOKEN") or config.get("api-token", "")
        return cls(config["base-url"], config["space-key"], config.get("email", ""), token)

    def _get(self, url: str, params: dict | None = None) -> dict:
        last_status = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(url, params=params, timeout=_TIMEOUT_SEC)
            except requests.RequestException as e:
                logger.warning("Confluence 요청 실패(%s/%s) %s: %s", attempt, _MAX_ATTEMPTS, url, e)
                last_status = str(e)
            else:
                if response.status_code in (401, 403):
                    raise ConfluenceAuthError(
                        f"Confluence 인증 실패({response.status_code}). "
                        "CONFLUENCE_API_TOKEN 환경변수와 [confluence] email 설정을 확인하세요."
                    )
                if response.status_code == 200:
                    return response.json()
                last_status = response.status_code
                if response.status_code not in _RETRY_STATUS:
                    break
                logger.warning("Confluence 응답 %s (%s/%s) %s", response.status_code, attempt, _MAX_ATTEMPTS, url)
            if attempt < _MAX_ATTEMPTS:
                self._sleep(2 ** (attempt - 1))
        raise ConfluenceFetchError(f"Confluence 요청 실패: {url} (마지막 상태: {last_status})")

    def fetch_space_id(self) -> str:
        data = self._get(f"{self.base_url}/api/v2/spaces", params={"keys": self.space_key})
        results = data.get("results", [])
        if not results:
            raise ConfluenceFetchError(f"스페이스를 찾을 수 없습니다: {self.space_key}")
        return str(results[0]["id"])

    def fetch_pages(self) -> list[dict]:
        space_id = self.fetch_space_id()
        url = f"{self.base_url}/api/v2/spaces/{space_id}/pages"
        params: dict | None = {"status": "current", "body-format": "storage", "limit": _PAGE_LIMIT}
        pages: list[dict] = []
        while url:
            data = self._get(url, params=params)
            pages.extend(data.get("results", []))
            next_link = (data.get("_links") or {}).get("next")
            url = f"{self._site_root}{next_link}" if next_link else None
            params = None  # next 링크에 쿼리가 포함돼 있다
        logger.info("Confluence 페이지 %s건 수집 (space=%s)", len(pages), self.space_key)
        return pages
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_confluence_repository.py -v`
Expected: 7 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/repository/ test/test_confluence_repository.py
git commit -m "$(cat <<'EOF'
Confluence REST v2 저장소 추가 (인증, 커서 페이지네이션, 재시도)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: OpenAPI 스펙 → endpoint/schema Document 렌더링

**Files:**
- Create: `src/service/openapi_document_service.py`
- Create: `test/fixtures/openapi_sample.json`
- Test: `test/test_openapi_document_service.py`

**Interfaces:**
- Consumes: 없음(순수 함수)
- Produces:
  - `@dataclass OpenApiSource(name: str, spec_url: str, docs_url: str)`
  - `resolve_ref(spec: dict, ref: str) -> dict`
  - `render_endpoint(spec: dict, source: OpenApiSource, path: str, method: str, operation: dict) -> str`
  - `render_schema(spec: dict, name: str, schema: dict) -> str`
  - `build_documents(spec: dict, source: OpenApiSource) -> list[Document]` — metadata: `source="openapi"`, `doc_id`(`"{service}:{METHOD}:{path}"` / `"{service}:schema:{name}"`), `service`, `method`, `path`, `tags`(쉼표 문자열), `url`(docs_url), `title`(`"{METHOD} {path}"` / `"Schema {name}"`)

- [ ] **Step 1: 픽스처와 실패하는 테스트 작성**

`test/fixtures/openapi_sample.json`:
```json
{
  "openapi": "3.1.0",
  "info": {"title": "Message Management API", "version": "1.0"},
  "paths": {
    "/v1/messages/message": {
      "post": {
        "tags": ["message 등록"],
        "summary": "Add Message",
        "description": "메시지를 등록한다.",
        "operationId": "add_message",
        "requestBody": {
          "required": true,
          "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MessagePostRequest"}}}
        },
        "responses": {
          "200": {"description": "Successful Response",
                  "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MessageResponse"}}}},
          "422": {"description": "Validation Error"}
        }
      }
    },
    "/v1/messages/{service_key}/{user_key}": {
      "get": {
        "tags": ["message 조회"],
        "summary": "List Messages",
        "parameters": [
          {"name": "service_key", "in": "path", "required": true, "schema": {"type": "string"}, "description": "서비스 키"},
          {"name": "user_key", "in": "path", "required": true, "schema": {"type": "string"}},
          {"name": "last_session_only", "in": "query", "required": false, "schema": {"type": "boolean", "default": false}}
        ],
        "responses": {"200": {"description": "OK"}}
      }
    }
  },
  "components": {
    "schemas": {
      "MessagePostRequest": {
        "type": "object",
        "required": ["service_key", "original_message"],
        "properties": {
          "service_key": {"type": "string", "description": "서비스 키"},
          "original_message": {"type": "string"},
          "custom": {"type": "object", "additionalProperties": true},
          "children": {"type": "array", "items": {"$ref": "#/components/schemas/MessagePostRequest"}}
        }
      },
      "MessageResponse": {
        "type": "object",
        "properties": {
          "seq": {"type": "integer"},
          "request": {"$ref": "#/components/schemas/MessagePostRequest"}
        }
      }
    }
  }
}
```

`test/test_openapi_document_service.py`:
```python
import json
from pathlib import Path

import pytest

from src.service.openapi_document_service import (
    OpenApiSource,
    build_documents,
    render_endpoint,
    render_schema,
    resolve_ref,
)

SPEC = json.loads((Path(__file__).parent / "fixtures" / "openapi_sample.json").read_text(encoding="utf-8"))
SOURCE = OpenApiSource(name="message-api", spec_url="https://x/openapi.json", docs_url="https://x/docs")


def test_resolve_ref():
    schema = resolve_ref(SPEC, "#/components/schemas/MessageResponse")
    assert schema["properties"]["seq"]["type"] == "integer"


def test_render_endpoint_contains_method_path_and_inlined_request_schema():
    op = SPEC["paths"]["/v1/messages/message"]["post"]
    text = render_endpoint(SPEC, SOURCE, "/v1/messages/message", "post", op)
    assert text.startswith("## POST /v1/messages/message — Add Message")
    assert "서비스: Message Management API (message-api)" in text
    assert "태그: message 등록" in text
    assert "메시지를 등록한다." in text
    assert "service_key" in text and "(필수)" in text  # 요청 스키마가 인라인 됨
    assert "### Responses" in text and "200" in text and "MessageResponse" in text


def test_render_endpoint_parameters_table():
    op = SPEC["paths"]["/v1/messages/{service_key}/{user_key}"]["get"]
    text = render_endpoint(SPEC, SOURCE, "/v1/messages/{service_key}/{user_key}", "get", op)
    assert "| service_key | path | string | 예 | 서비스 키 |" in text
    assert "| last_session_only | query | boolean | 아니오 |" in text


def test_circular_ref_is_cut_by_name():
    text = render_schema(SPEC, "MessagePostRequest", SPEC["components"]["schemas"]["MessagePostRequest"])
    assert text.startswith("## Schema MessagePostRequest")
    # children → MessagePostRequest 순환: 이름만 표기되고 무한 재귀하지 않는다
    assert "array<MessagePostRequest>" in text


def test_build_documents_metadata_and_counts():
    docs = build_documents(SPEC, SOURCE)
    ids = {d.metadata["doc_id"] for d in docs}
    assert ids == {
        "message-api:POST:/v1/messages/message",
        "message-api:GET:/v1/messages/{service_key}/{user_key}",
        "message-api:schema:MessagePostRequest",
        "message-api:schema:MessageResponse",
    }
    post = next(d for d in docs if d.metadata["doc_id"] == "message-api:POST:/v1/messages/message")
    assert post.metadata["source"] == "openapi"
    assert post.metadata["method"] == "POST"
    assert post.metadata["path"] == "/v1/messages/message"
    assert post.metadata["tags"] == "message 등록"
    assert post.metadata["url"] == "https://x/docs"
    assert post.metadata["title"] == "POST /v1/messages/message"
    schema_doc = next(d for d in docs if d.metadata["doc_id"] == "message-api:schema:MessageResponse")
    assert schema_doc.metadata["title"] == "Schema MessageResponse"
    assert schema_doc.metadata["method"] == "" and schema_doc.metadata["path"] == ""


def test_broken_ref_skips_only_that_item():
    spec = json.loads(json.dumps(SPEC))
    spec["paths"]["/broken"] = {"get": {"summary": "b", "responses": {
        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Nope"}}}}}}}
    docs = build_documents(spec, SOURCE)
    assert not any(d.metadata["doc_id"].endswith(":/broken") for d in docs)
    assert len(docs) == 4
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_openapi_document_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/service/openapi_document_service.py`:
```python
"""OpenAPI 3.x 스펙을 endpoint 단위·schema 단위 Markdown Document 로 렌더링한다."""
from dataclasses import dataclass

from langchain_core.documents import Document

from src.library.global_logger import GlobalLogger

logger = GlobalLogger.get_logger(__name__)

SOURCE_OPENAPI = "openapi"
_MAX_DEPTH = 3
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


@dataclass(frozen=True)
class OpenApiSource:
    name: str
    spec_url: str
    docs_url: str


class OpenApiRefError(Exception):
    pass


def resolve_ref(spec: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise OpenApiRefError(f"외부 $ref 는 지원하지 않습니다: {ref}")
    node = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise OpenApiRefError(f"$ref 대상을 찾을 수 없습니다: {ref}")
        node = node[part]
    return node


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _type_label(spec: dict, schema: dict, seen: frozenset) -> str:
    """스키마의 한 줄 타입 표기. $ref 는 이름, 배열은 array<...>."""
    if "$ref" in schema:
        return _ref_name(schema["$ref"])
    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf")
        return " | ".join(_type_label(spec, o, seen) for o in options)
    if schema.get("type") == "array":
        return f"array<{_type_label(spec, schema.get('items', {}), seen)}>"
    return schema.get("type", "object" if "properties" in schema else "any")


def _schema_lines(spec: dict, schema: dict, depth: int, seen: frozenset, indent: str = "") -> list[str]:
    """object 스키마의 필드를 '- name (type, 필수): desc' 줄로 펼친다. 깊이 제한·순환은 이름만."""
    if "$ref" in schema:
        name = _ref_name(schema["$ref"])
        if name in seen or depth > _MAX_DEPTH:
            return [f"{indent}- ({name})"]
        return _schema_lines(spec, resolve_ref(spec, schema["$ref"]), depth, seen | {name}, indent)
    lines = []
    required = set(schema.get("required", []))
    for field, sub in (schema.get("properties") or {}).items():
        label = _type_label(spec, sub, seen)
        req = " (필수)" if field in required else ""
        desc = f": {sub.get('description')}" if sub.get("description") else ""
        lines.append(f"{indent}- {field} ({label}){req}{desc}")
        # 중첩 object / object 배열은 한 단계 더 펼친다
        nested = sub.get("items", sub) if sub.get("type") == "array" else sub
        if depth < _MAX_DEPTH and ("$ref" in nested or nested.get("properties")):
            name = _ref_name(nested["$ref"]) if "$ref" in nested else None
            if name and name in seen:
                continue
            lines.extend(_schema_lines(spec, nested, depth + 1, seen | ({name} if name else set()), indent + "  "))
    return lines


def _content_schema(content: dict | None) -> dict | None:
    if not content:
        return None
    for media in ("application/json", *content.keys()):
        if media in content and "schema" in content[media]:
            return content[media]["schema"]
    return None


def render_endpoint(spec: dict, source: OpenApiSource, path: str, method: str, operation: dict) -> str:
    method_u = method.upper()
    title = spec.get("info", {}).get("title", source.name)
    lines = [f"## {method_u} {path} — {operation.get('summary', '')}".rstrip(" —"),
             f"서비스: {title} ({source.name})"]
    if operation.get("tags"):
        lines.append(f"태그: {', '.join(operation['tags'])}")
    if operation.get("description"):
        lines += ["", operation["description"].strip()]

    params = operation.get("parameters", [])
    if params:
        lines += ["", "### Parameters", "| name | in | type | required | description |", "|---|---|---|---|---|"]
        for p in params:
            p = resolve_ref(spec, p["$ref"]) if "$ref" in p else p
            ptype = _type_label(spec, p.get("schema", {}), frozenset())
            lines.append(f"| {p['name']} | {p.get('in', '')} | {ptype} | {'예' if p.get('required') else '아니오'} | {p.get('description', '')} |")

    body_schema = _content_schema((operation.get("requestBody") or {}).get("content"))
    if body_schema is not None:
        lines += ["", f"### Request Body ({_type_label(spec, body_schema, frozenset())})"]
        lines += _schema_lines(spec, body_schema, 1, frozenset())

    responses = operation.get("responses") or {}
    if responses:
        lines += ["", "### Responses"]
        for status, resp in responses.items():
            resp = resolve_ref(spec, resp["$ref"]) if "$ref" in resp else resp
            schema = _content_schema(resp.get("content"))
            label = f" → {_type_label(spec, schema, frozenset())}" if schema is not None else ""
            lines.append(f"- {status}: {resp.get('description', '')}{label}")
            if schema is not None and str(status).startswith("2"):
                lines += _schema_lines(spec, schema, 1, frozenset(), indent="  ")
    return "\n".join(lines)


def render_schema(spec: dict, name: str, schema: dict) -> str:
    lines = [f"## Schema {name}"]
    if schema.get("description"):
        lines += ["", schema["description"].strip()]
    lines += ["", f"타입: {_type_label(spec, schema, frozenset({name}))}", ""]
    lines += _schema_lines(spec, schema, 1, frozenset({name}))
    return "\n".join(lines)


def build_documents(spec: dict, source: OpenApiSource) -> list[Document]:
    docs: list[Document] = []
    for path, item in (spec.get("paths") or {}).items():
        for method in _HTTP_METHODS:
            operation = item.get(method)
            if not operation:
                continue
            try:
                text = render_endpoint(spec, source, path, method, operation)
            except OpenApiRefError as e:
                logger.warning("endpoint 렌더링 건너뜀 %s %s: %s", method.upper(), path, e)
                continue
            docs.append(Document(page_content=text, metadata={
                "source": SOURCE_OPENAPI,
                "doc_id": f"{source.name}:{method.upper()}:{path}",
                "service": source.name,
                "method": method.upper(),
                "path": path,
                "tags": ", ".join(operation.get("tags", [])),
                "url": source.docs_url,
                "title": f"{method.upper()} {path}",
            }))
    for name, schema in ((spec.get("components") or {}).get("schemas") or {}).items():
        try:
            text = render_schema(spec, name, schema)
        except OpenApiRefError as e:
            logger.warning("schema 렌더링 건너뜀 %s: %s", name, e)
            continue
        docs.append(Document(page_content=text, metadata={
            "source": SOURCE_OPENAPI,
            "doc_id": f"{source.name}:schema:{name}",
            "service": source.name,
            "method": "",
            "path": "",
            "tags": "",
            "url": source.docs_url,
            "title": f"Schema {name}",
        }))
    return docs
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_openapi_document_service.py -v`
Expected: 6 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/service/openapi_document_service.py test/fixtures/openapi_sample.json test/test_openapi_document_service.py
git commit -m "$(cat <<'EOF'
OpenAPI 스펙 → endpoint/schema Document 렌더링 서비스 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: OpenAPI 소스 목록 로딩·스펙 다운로드 저장소

**Files:**
- Create: `src/repository/openapi_repository.py`
- Test: `test/test_openapi_repository.py`

**Interfaces:**
- Consumes: `OpenApiSource` (Task 4), `Profile().get_config("openapi")` (Task 1)
- Produces:
  - `class OpenApiFetchError(Exception)`
  - `load_sources(path: str) -> list[OpenApiSource]`
  - `OpenApiRepository(session=None, sleep=time.sleep)`
  - `.fetch_spec(url: str) -> dict` — JSON 또는 YAML 응답 파싱, 429/5xx 3회 재시도
  - `OpenApiRepository.sources_from_profile() -> list[OpenApiSource]`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_openapi_repository.py`:
```python
import json

import pytest

from src.repository.openapi_repository import OpenApiFetchError, OpenApiRepository, load_sources


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self._responses.pop(0)


def test_load_sources(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("sources:\n  - name: a\n    spec_url: https://a/openapi.json\n    docs_url: https://a/docs\n", encoding="utf-8")
    sources = load_sources(str(f))
    assert len(sources) == 1
    assert sources[0].name == "a" and sources[0].docs_url == "https://a/docs"


def test_fetch_spec_json():
    session = FakeSession([FakeResponse(200, json.dumps({"openapi": "3.1.0", "paths": {}}))])
    spec = OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert spec["openapi"] == "3.1.0"


def test_fetch_spec_yaml():
    session = FakeSession([FakeResponse(200, "openapi: 3.1.0\npaths: {}\n")])
    spec = OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.yaml")
    assert spec["openapi"] == "3.1.0"


def test_fetch_spec_retries_then_fails():
    session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
    with pytest.raises(OpenApiFetchError):
        OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 3


def test_fetch_spec_404_no_retry():
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(OpenApiFetchError):
        OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 1


def test_sources_from_profile_reads_two_services():
    names = {s.name for s in OpenApiRepository.sources_from_profile()}
    assert names == {"general-chatbot-api", "message-api"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_openapi_repository.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/repository/openapi_repository.py`:
```python
"""openapi_sources.yaml 로딩과 OpenAPI 스펙(JSON/YAML) 다운로드."""
import json
import time

import requests
import yaml

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger
from src.service.openapi_document_service import OpenApiSource

logger = GlobalLogger.get_logger(__name__)

_MAX_ATTEMPTS = 3
_TIMEOUT_SEC = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenApiFetchError(Exception):
    pass


def load_sources(path: str) -> list[OpenApiSource]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [OpenApiSource(name=s["name"], spec_url=s["spec_url"], docs_url=s.get("docs_url", ""))
            for s in data.get("sources", [])]


class OpenApiRepository:
    def __init__(self, session=None, sleep=time.sleep):
        self._session = session or requests.Session()
        self._sleep = sleep

    @staticmethod
    def sources_from_profile() -> list[OpenApiSource]:
        return load_sources(Profile().get_config("openapi")["sources-file"])

    def fetch_spec(self, url: str) -> dict:
        last_status = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(url, timeout=_TIMEOUT_SEC)
            except requests.RequestException as e:
                logger.warning("OpenAPI 요청 실패(%s/%s) %s: %s", attempt, _MAX_ATTEMPTS, url, e)
                last_status = str(e)
            else:
                if response.status_code == 200:
                    return self._parse(response.text, url)
                last_status = response.status_code
                if response.status_code not in _RETRY_STATUS:
                    break
                logger.warning("OpenAPI 응답 %s (%s/%s) %s", response.status_code, attempt, _MAX_ATTEMPTS, url)
            if attempt < _MAX_ATTEMPTS:
                self._sleep(2 ** (attempt - 1))
        raise OpenApiFetchError(f"OpenAPI 스펙 다운로드 실패: {url} (마지막 상태: {last_status})")

    @staticmethod
    def _parse(text: str, url: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise OpenApiFetchError(f"OpenAPI 스펙 파싱 실패: {url}: {e}") from e
        if not isinstance(data, dict):
            raise OpenApiFetchError(f"OpenAPI 스펙 형식이 올바르지 않습니다: {url}")
        return data
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_openapi_repository.py -v`
Expected: 6 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/repository/openapi_repository.py test/test_openapi_repository.py
git commit -m "$(cat <<'EOF'
OpenAPI 소스 목록 로딩 및 스펙 다운로드 저장소 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Markdown 헤딩 기반 청킹

**Files:**
- Create: `src/service/chunk_service.py`
- Test: `test/test_chunk_service.py`

**Interfaces:**
- Consumes: `Document`(Task 2/4 형식; metadata `source`, `doc_id`, `title`, `breadcrumb`(confluence만))
- Produces:
  - `split_documents(docs: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]` — 각 청크 metadata = 원본 metadata + `chunk_id`(`"{doc_id}#{n}"`) + `chunk_index:int` + `section`(헤딩 경로 문자열). 본문이 비어 있는 문서는 청크 0개.

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_chunk_service.py`:
```python
from langchain_core.documents import Document

from src.service.chunk_service import split_documents


def _confluence_doc(content, doc_id="10"):
    return Document(page_content=content, metadata={
        "source": "confluence", "doc_id": doc_id, "title": "리프", "breadcrumb": "루트 > 리프",
        "url": "https://x/10", "version": 1, "last_modified": "",
    })


def _openapi_doc(content, doc_id="svc:GET:/a"):
    return Document(page_content=content, metadata={
        "source": "openapi", "doc_id": doc_id, "title": "GET /a", "service": "svc", "method": "GET",
        "path": "/a", "tags": "", "url": "https://x/docs",
    })


def test_confluence_split_by_headings_with_prefix():
    md = "# 인증\n\n개요 문장.\n\n## 요청\n\n요청 설명.\n\n## 응답\n\n응답 설명."
    chunks = split_documents([_confluence_doc(md)], chunk_size=1000, chunk_overlap=100)
    assert len(chunks) == 3
    assert chunks[1].page_content.startswith("[루트 > 리프 > 인증 > 요청]")
    assert "요청 설명." in chunks[1].page_content
    assert chunks[1].metadata["chunk_id"] == "10#1"
    assert chunks[1].metadata["chunk_index"] == 1
    assert chunks[1].metadata["section"] == "인증 > 요청"
    assert chunks[1].metadata["doc_id"] == "10"


def test_long_section_is_split_further_with_same_prefix():
    md = "# 제목\n\n" + ("가나다라마바사 " * 400)  # 3200자 이상
    chunks = split_documents([_confluence_doc(md)], chunk_size=1000, chunk_overlap=100)
    assert len(chunks) >= 3
    assert all(c.page_content.startswith("[루트 > 리프 > 제목]") for c in chunks)
    assert all(len(c.page_content) <= 1000 + len("[루트 > 리프 > 제목]\n") for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_document_without_headings_is_single_chunk():
    chunks = split_documents([_confluence_doc("헤딩 없는 짧은 본문")], 1000, 100)
    assert len(chunks) == 1
    assert chunks[0].page_content == "[루트 > 리프]\n헤딩 없는 짧은 본문"


def test_empty_document_yields_no_chunk():
    assert split_documents([_confluence_doc("")], 1000, 100) == []


def test_openapi_doc_is_single_chunk_when_short():
    text = "## GET /a — 목록\n서비스: svc\n\n### Responses\n- 200: OK"
    chunks = split_documents([_openapi_doc(text)], 1000, 100)
    assert len(chunks) == 1
    assert chunks[0].page_content == text
    assert chunks[0].metadata["chunk_id"] == "svc:GET:/a#0"


def test_openapi_doc_split_only_when_over_three_times_chunk_size():
    header = "## GET /a — 목록"
    text = header + "\n" + ("- field (string)\n" * 300)  # 4500자 이상
    chunks = split_documents([_openapi_doc(text)], 1000, 100)
    assert len(chunks) >= 2
    assert all(c.page_content.startswith(header) for c in chunks)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_chunk_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/service/chunk_service.py`:
```python
"""Markdown Document 를 검색 단위 청크로 나눈다."""
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
_OPENAPI_SPLIT_FACTOR = 3


def _make_chunk(doc: Document, index: int, content: str, section: str) -> Document:
    metadata = dict(doc.metadata)
    metadata.update({
        "chunk_id": f"{doc.metadata['doc_id']}#{index}",
        "chunk_index": index,
        "section": section,
    })
    return Document(page_content=content, metadata=metadata)


def _split_confluence(doc: Document, chunk_size: int, chunk_overlap: int) -> list[Document]:
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADERS, strip_headers=False)
    sections = header_splitter.split_text(doc.page_content)
    breadcrumb = doc.metadata.get("breadcrumb") or doc.metadata.get("title", "")
    chunks: list[Document] = []
    for section in sections:
        headings = [section.metadata[key] for _, key in _HEADERS if key in section.metadata]
        section_path = " > ".join(headings)
        prefix = f"[{' > '.join(filter(None, [breadcrumb, section_path]))}]\n"
        # 접두어 길이를 제외한 만큼만 본문에 허용해 청크 총길이가 chunk_size 를 넘지 않게 한다
        body_limit = max(chunk_size - len(prefix), chunk_size // 2)
        body = section.page_content.strip()
        if not body:
            continue
        if len(body) <= body_limit:
            pieces = [body]
        else:
            pieces = RecursiveCharacterTextSplitter(chunk_size=body_limit, chunk_overlap=chunk_overlap).split_text(body)
        for piece in pieces:
            chunks.append(_make_chunk(doc, len(chunks), prefix + piece, section_path))
    return chunks


def _split_openapi(doc: Document, chunk_size: int, chunk_overlap: int) -> list[Document]:
    text = doc.page_content.strip()
    limit = chunk_size * _OPENAPI_SPLIT_FACTOR
    if len(text) <= limit:
        return [_make_chunk(doc, 0, text, "")]
    header, _, rest = text.partition("\n")
    pieces = RecursiveCharacterTextSplitter(chunk_size=limit - len(header) - 1, chunk_overlap=chunk_overlap).split_text(rest)
    return [_make_chunk(doc, i, f"{header}\n{piece}", "") for i, piece in enumerate(pieces)]


def split_documents(docs: list[Document], chunk_size: int, chunk_overlap: int) -> list[Document]:
    chunks: list[Document] = []
    for doc in docs:
        if not doc.page_content.strip():
            continue
        if doc.metadata.get("source") == "openapi":
            chunks.extend(_split_openapi(doc, chunk_size, chunk_overlap))
        else:
            chunks.extend(_split_confluence(doc, chunk_size, chunk_overlap))
    return chunks
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_chunk_service.py -v`
Expected: 6 PASSED. (`[검증]` `MarkdownHeaderTextSplitter(strip_headers=False)`는 섹션 내 줄을 `"  \n"`(공백 2개 + 개행)으로 잇는다 — 예: `'## 요청  \n요청 설명.'`. 테스트는 부분 문자열만 확인하므로 영향 없다.)

- [ ] **Step 5: 커밋**

```bash
git add src/service/chunk_service.py test/test_chunk_service.py
git commit -m "$(cat <<'EOF'
Markdown 헤딩 기반 청킹 서비스 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: LLM 팩토리와 Chroma 벡터 저장소

**Files:**
- Create: `src/service/llm_factory.py`
- Create: `src/repository/vector_store_repository.py`
- Test: `test/test_vector_store_repository.py`

**Interfaces:**
- Consumes: `Profile().get_config("ollama"|"chroma"|"retrieval")` (Task 1), 청크 `Document`(Task 6; metadata `chunk_id` 필수)
- Produces:
  - `llm_factory.create_embeddings() -> OllamaEmbeddings`
  - `llm_factory.create_chat_model() -> ChatOllama` (`temperature`, `num_ctx`, `reasoning=False`, `client_kwargs={"timeout": llm-timeout}`)
  - `llm_factory.ping_ollama() -> bool` — `GET {base-url}/api/tags` 200 여부
  - `VectorStoreRepository(persist_dir: str, collection_name: str, embeddings, batch_size: int = 32)`
  - `VectorStoreRepository.from_profile(embeddings=None) -> VectorStoreRepository` (embeddings 미지정 시 `create_embeddings()`)
  - `.upsert(chunks: list[Document]) -> None` — id는 `metadata["chunk_id"]`, `batch_size`씩 나눠 저장
  - `.delete(chunk_ids: list[str]) -> None`
  - `.get_all() -> list[Document]` — 전체 청크(metadata 포함)
  - `.count() -> int`
  - `.reset() -> None` — 컬렉션 삭제 후 재생성
  - `.as_retriever(k: int, source: str | None = None)` — `source`가 있으면 `filter={"source": source}`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_vector_store_repository.py`:
```python
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.repository.vector_store_repository import VectorStoreRepository


def _chunk(chunk_id, text, source="confluence"):
    return Document(page_content=text, metadata={
        "chunk_id": chunk_id, "chunk_index": int(chunk_id.split("#")[1]), "doc_id": chunk_id.split("#")[0],
        "source": source, "title": "t", "url": "https://x", "section": "",
    })


def _repo(tmp_path, batch_size=2):
    return VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16), batch_size=batch_size)


def test_upsert_get_all_and_count(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "인증 서버"), _chunk("1#1", "토큰 발급"), _chunk("2#0", "메시지 API", "openapi")])
    assert repo.count() == 3
    docs = repo.get_all()
    assert {d.metadata["chunk_id"] for d in docs} == {"1#0", "1#1", "2#0"}
    assert next(d for d in docs if d.metadata["chunk_id"] == "1#1").page_content == "토큰 발급"


def test_upsert_same_id_overwrites(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "v1")])
    repo.upsert([_chunk("1#0", "v2")])
    assert repo.count() == 1
    assert repo.get_all()[0].page_content == "v2"


def test_delete(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "a"), _chunk("1#1", "b")])
    repo.delete(["1#0"])
    repo.delete([])  # 빈 목록은 무시
    assert [d.metadata["chunk_id"] for d in repo.get_all()] == ["1#1"]


def test_reset(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "a")])
    repo.reset()
    assert repo.count() == 0
    repo.upsert([_chunk("3#0", "c")])
    assert repo.count() == 1


def test_persistence_across_instances(tmp_path):
    _repo(tmp_path).upsert([_chunk("1#0", "a")])
    assert _repo(tmp_path).count() == 1


def test_retriever_source_filter(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "인증 서버 설명"), _chunk("2#0", "GET /v1/messages", "openapi")])
    docs = repo.as_retriever(k=5, source="openapi").invoke("메시지")
    assert [d.metadata["chunk_id"] for d in docs] == ["2#0"]
    assert len(repo.as_retriever(k=5).invoke("메시지")) == 2
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_vector_store_repository.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/service/llm_factory.py`:
```python
"""LLM / 임베딩 객체 생성 단일 지점. 사내 서버 이전 시 이 파일만 교체한다."""
import requests
from langchain_ollama import ChatOllama, OllamaEmbeddings

from src.config.profile import Profile


def _ollama_config() -> dict:
    return Profile().get_config("ollama")


def create_embeddings() -> OllamaEmbeddings:
    config = _ollama_config()
    return OllamaEmbeddings(model=config["embedding-model"], base_url=config["base-url"])


def create_chat_model() -> ChatOllama:
    config = _ollama_config()
    return ChatOllama(
        model=config["llm-model"],
        base_url=config["base-url"],
        temperature=float(config.get("temperature", 0)),
        num_ctx=int(config.get("num-ctx", 16384)),
        reasoning=False,  # qwen3 thinking 모드 비활성화
        client_kwargs={"timeout": float(config.get("llm-timeout", 120))},
    )


def ping_ollama() -> bool:
    try:
        return requests.get(f"{_ollama_config()['base-url']}/api/tags", timeout=3).status_code == 200
    except requests.RequestException:
        return False
```

`src/repository/vector_store_repository.py`:
```python
"""Chroma(로컬 persist) 접근. 인제스트와 서빙이 공유하는 유일한 저장소."""
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.config.profile import Profile
from src.service import llm_factory


class VectorStoreRepository:
    def __init__(self, persist_dir: str, collection_name: str, embeddings, batch_size: int = 32):
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._embeddings = embeddings
        self._batch_size = batch_size
        self._store = self._open()

    def _open(self) -> Chroma:
        return Chroma(
            collection_name=self._collection_name,
            embedding_function=self._embeddings,
            persist_directory=self._persist_dir,
            collection_metadata={"hnsw:space": "cosine"},
        )

    @classmethod
    def from_profile(cls, embeddings=None) -> "VectorStoreRepository":
        chroma = Profile().get_config("chroma")
        retrieval = Profile().get_config("retrieval")
        return cls(
            chroma["persist-dir"],
            chroma["collection"],
            embeddings or llm_factory.create_embeddings(),
            batch_size=int(retrieval.get("embed-batch-size", 32)),
        )

    def upsert(self, chunks: list[Document]) -> None:
        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start:start + self._batch_size]
            ids = [c.metadata["chunk_id"] for c in batch]
            # Chroma 는 None 메타데이터를 거부한다
            cleaned = [Document(page_content=c.page_content,
                                metadata={k: v for k, v in c.metadata.items() if v is not None}) for c in batch]
            self._store.add_documents(cleaned, ids=ids)

    def delete(self, chunk_ids: list[str]) -> None:
        if chunk_ids:
            self._store.delete(ids=list(chunk_ids))

    def get_all(self) -> list[Document]:
        data = self._store.get(include=["documents", "metadatas"])
        return [Document(page_content=text, metadata=meta or {})
                for text, meta in zip(data["documents"], data["metadatas"])]

    def count(self) -> int:
        return self._store._collection.count()

    def reset(self) -> None:
        self._store.delete_collection()
        self._store = self._open()

    def as_retriever(self, k: int, source: str | None = None):
        search_kwargs: dict = {"k": k}
        if source:
            search_kwargs["filter"] = {"source": source}
        return self._store.as_retriever(search_kwargs=search_kwargs)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_vector_store_repository.py -v`
Expected: 6 PASSED. (`[검증]` langchain-chroma 1.1.0에서 `_collection.count()`, `get(include=[...])`, `delete(ids=)`, `delete_collection()`, `as_retriever(search_kwargs={"filter": ...})` 동작 확인함.)

- [ ] **Step 5: 커밋**

```bash
git add src/service/llm_factory.py src/repository/vector_store_repository.py test/test_vector_store_repository.py
git commit -m "$(cat <<'EOF'
LLM 팩토리와 Chroma 벡터 저장소 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: manifest 증분 갱신, 인제스트 서비스, CLI

**Files:**
- Create: `src/service/manifest.py`
- Create: `src/service/ingest_service.py`
- Create: `ingest.py`
- Test: `test/test_manifest.py`, `test/test_ingest_service.py`

**Interfaces:**
- Consumes: `VectorStoreRepository`(Task 7), `split_documents`(Task 6), `ConfluenceRepository`(Task 3) + `confluence_document_service.build_documents`(Task 2), `OpenApiRepository`/`load_sources`(Task 5) + `openapi_document_service.build_documents`(Task 4)
- Produces:
  - `Manifest(path: str)` — `.entries: dict[str, dict]`, `.load()`, `.save()`, `.get(doc_id)`, `.set(doc_id, fingerprint: str, chunk_ids: list[str], source: str)`, `.remove(doc_id)`, `.doc_ids_for_source(source) -> set[str]`, `.clear()`
  - `@dataclass IngestDiff(added: list[str], changed: list[str], removed: list[str], unchanged: list[str])`
  - `compute_diff(manifest: Manifest, source: str, fingerprints: dict[str, str], removable: Callable[[str], bool] = lambda _: True) -> IngestDiff`
  - `@dataclass IngestSummary(source: str, added: int, changed: int, removed: int, chunk_count: int, failed_sources: list[str])`
  - `IngestService(vector_store, manifest, chunk_size: int, chunk_overlap: int)`
    - `.ingest_documents(source: str, docs: list[Document], fingerprints: dict[str, str], removable=lambda _: True) -> IngestSummary`
    - `.ingest_confluence(repo: ConfluenceRepository, base_url: str) -> IngestSummary`
    - `.ingest_openapi(repo: OpenApiRepository, sources: list[OpenApiSource]) -> IngestSummary`
    - `.reset_all()`
  - `confluence_fingerprint(doc) -> str` (= `str(version)`), `openapi_fingerprint(doc) -> str` (= sha256(page_content))

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_manifest.py`:
```python
from src.service.manifest import Manifest, compute_diff


def test_manifest_roundtrip(tmp_path):
    path = str(tmp_path / "manifest.json")
    m = Manifest(path)
    m.set("1", "v3", ["1#0", "1#1"], "confluence")
    m.save()
    m2 = Manifest(path)
    assert m2.get("1") == {"fingerprint": "v3", "chunk_ids": ["1#0", "1#1"], "source": "confluence"}
    assert m2.doc_ids_for_source("confluence") == {"1"}
    assert m2.doc_ids_for_source("openapi") == set()


def test_missing_file_is_empty(tmp_path):
    assert Manifest(str(tmp_path / "none.json")).entries == {}


def test_compute_diff(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    m.set("keep", "1", ["keep#0"], "confluence")
    m.set("change", "1", ["change#0"], "confluence")
    m.set("gone", "1", ["gone#0"], "confluence")
    m.set("other", "1", ["other#0"], "openapi")  # 다른 소스는 영향 없음
    diff = compute_diff(m, "confluence", {"keep": "1", "change": "2", "new": "1"})
    assert diff.unchanged == ["keep"]
    assert diff.changed == ["change"]
    assert diff.added == ["new"]
    assert diff.removed == ["gone"]


def test_compute_diff_respects_removable_scope(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    m.set("svcA:GET:/a", "1", ["svcA:GET:/a#0"], "openapi")
    m.set("svcB:GET:/b", "1", ["svcB:GET:/b#0"], "openapi")
    # svcB 는 이번에 수집 실패 → 삭제 대상에서 제외
    diff = compute_diff(m, "openapi", {}, removable=lambda doc_id: doc_id.startswith("svcA:"))
    assert diff.removed == ["svcA:GET:/a"]
```

`test/test_ingest_service.py`:
```python
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.repository.vector_store_repository import VectorStoreRepository
from src.service.ingest_service import IngestService, confluence_fingerprint, openapi_fingerprint
from src.service.manifest import Manifest


def _doc(doc_id, content, version=1):
    return Document(page_content=content, metadata={
        "source": "confluence", "doc_id": doc_id, "title": f"t{doc_id}", "breadcrumb": f"t{doc_id}",
        "url": "https://x", "version": version, "last_modified": "",
    })


def _service(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    manifest = Manifest(str(tmp_path / "manifest.json"))
    return IngestService(store, manifest, chunk_size=1000, chunk_overlap=100), store, manifest


def _fps(docs):
    return {d.metadata["doc_id"]: confluence_fingerprint(d) for d in docs}


def test_first_ingest_adds_everything(tmp_path):
    svc, store, manifest = _service(tmp_path)
    docs = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n내용\n\n## B2\n\n내용2")]
    summary = svc.ingest_documents("confluence", docs, _fps(docs))
    assert (summary.added, summary.changed, summary.removed) == (2, 0, 0)
    assert store.count() == 3
    assert manifest.get("2")["chunk_ids"] == ["2#0", "2#1"]
    assert Manifest(str(tmp_path / "manifest.json")).get("1") is not None  # 저장됨


def test_incremental_update_changes_and_removes(tmp_path):
    svc, store, manifest = _service(tmp_path)
    first = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n내용\n\n## B2\n\n내용2")]
    svc.ingest_documents("confluence", first, _fps(first))
    second = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n바뀐 내용", version=2), _doc("3", "# C\n\n새 문서")]
    summary = svc.ingest_documents("confluence", second, _fps(second))
    assert (summary.added, summary.changed, summary.removed) == (1, 1, 0)
    assert manifest.get("2")["chunk_ids"] == ["2#0"]  # 청크 2개 → 1개로 갱신, 옛 2#1 삭제
    ids = {d.metadata["chunk_id"] for d in store.get_all()}
    assert ids == {"1#0", "2#0", "3#0"}
    third = [_doc("1", "# A\n\n내용")]
    summary = svc.ingest_documents("confluence", third, _fps(third))
    assert summary.removed == 2
    assert {d.metadata["chunk_id"] for d in store.get_all()} == {"1#0"}
    assert manifest.get("3") is None


def test_openapi_fingerprint_is_content_hash():
    a = Document(page_content="x", metadata={})
    b = Document(page_content="x", metadata={})
    c = Document(page_content="y", metadata={})
    assert openapi_fingerprint(a) == openapi_fingerprint(b) != openapi_fingerprint(c)


def test_reset_all_clears_store_and_manifest(tmp_path):
    svc, store, manifest = _service(tmp_path)
    docs = [_doc("1", "# A\n\n내용")]
    svc.ingest_documents("confluence", docs, _fps(docs))
    svc.reset_all()
    assert store.count() == 0 and manifest.entries == {}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_manifest.py test/test_ingest_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/service/manifest.py`:
```python
"""doc_id → fingerprint/chunk_ids 를 기록해 증분 인제스트를 가능하게 하는 매니페스트."""
# 클래스 안의 set() 메서드가 내장 set 을 가리므로 어노테이션은 지연 평가한다
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable


class Manifest:
    def __init__(self, path: str):
        self._path = path
        self.entries: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                self.entries = json.load(f)
        else:
            self.entries = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    def get(self, doc_id: str) -> dict | None:
        return self.entries.get(doc_id)

    def set(self, doc_id: str, fingerprint: str, chunk_ids: list[str], source: str) -> None:
        self.entries[doc_id] = {"fingerprint": fingerprint, "chunk_ids": list(chunk_ids), "source": source}

    def remove(self, doc_id: str) -> None:
        self.entries.pop(doc_id, None)

    def doc_ids_for_source(self, source: str) -> set[str]:
        return {doc_id for doc_id, e in self.entries.items() if e.get("source") == source}

    def clear(self) -> None:
        self.entries = {}


@dataclass
class IngestDiff:
    added: list[str]
    changed: list[str]
    removed: list[str]
    unchanged: list[str]


def compute_diff(manifest: Manifest, source: str, fingerprints: dict[str, str],
                 removable: Callable[[str], bool] = lambda _: True) -> IngestDiff:
    added, changed, unchanged = [], [], []
    for doc_id, fp in fingerprints.items():
        entry = manifest.get(doc_id)
        if entry is None:
            added.append(doc_id)
        elif entry["fingerprint"] != fp:
            changed.append(doc_id)
        else:
            unchanged.append(doc_id)
    removed = sorted(doc_id for doc_id in manifest.doc_ids_for_source(source)
                     if doc_id not in fingerprints and removable(doc_id))
    return IngestDiff(added=added, changed=changed, removed=removed, unchanged=unchanged)
```

`src/service/ingest_service.py`:
```python
"""소스별 수집 → Document → 청킹 → 증분 인덱싱 오케스트레이션."""
import hashlib
from dataclasses import dataclass, field

from langchain_core.documents import Document

from src.library.global_logger import GlobalLogger
from src.repository.confluence_repository import ConfluenceRepository
from src.repository.openapi_repository import OpenApiFetchError, OpenApiRepository
from src.repository.vector_store_repository import VectorStoreRepository
from src.service import confluence_document_service, openapi_document_service
from src.service.chunk_service import split_documents
from src.service.manifest import Manifest, compute_diff
from src.service.openapi_document_service import OpenApiSource

logger = GlobalLogger.get_logger(__name__)


@dataclass
class IngestSummary:
    source: str
    added: int = 0
    changed: int = 0
    removed: int = 0
    chunk_count: int = 0
    failed_sources: list[str] = field(default_factory=list)


def confluence_fingerprint(doc: Document) -> str:
    return str(doc.metadata.get("version", ""))


def openapi_fingerprint(doc: Document) -> str:
    return hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()


class IngestService:
    def __init__(self, vector_store: VectorStoreRepository, manifest: Manifest, chunk_size: int, chunk_overlap: int):
        self._store = vector_store
        self._manifest = manifest
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def ingest_documents(self, source: str, docs: list[Document], fingerprints: dict[str, str],
                         removable=lambda _: True) -> IngestSummary:
        diff = compute_diff(self._manifest, source, fingerprints, removable)
        by_id = {d.metadata["doc_id"]: d for d in docs}
        summary = IngestSummary(source=source, added=len(diff.added), changed=len(diff.changed), removed=len(diff.removed))

        for doc_id in diff.removed:
            self._store.delete(self._manifest.get(doc_id)["chunk_ids"])
            self._manifest.remove(doc_id)

        for doc_id in diff.changed + diff.added:
            doc = by_id[doc_id]
            previous = self._manifest.get(doc_id)
            if previous:
                self._store.delete(previous["chunk_ids"])
            chunks = split_documents([doc], self._chunk_size, self._chunk_overlap)
            self._store.upsert(chunks)
            # 저장 성공 후에만 manifest 갱신 → 실패 시 다음 실행에서 재시도된다
            self._manifest.set(doc_id, fingerprints[doc_id], [c.metadata["chunk_id"] for c in chunks], source)
            summary.chunk_count += len(chunks)
            self._manifest.save()

        self._manifest.save()
        logger.info("[%s] 추가 %s, 갱신 %s, 삭제 %s, 변경 없음 %s, 청크 %s",
                    source, summary.added, summary.changed, summary.removed, len(diff.unchanged), summary.chunk_count)
        return summary

    def ingest_confluence(self, repo: ConfluenceRepository, base_url: str) -> IngestSummary:
        pages = repo.fetch_pages()
        docs = confluence_document_service.build_documents(pages, base_url)
        fingerprints = {d.metadata["doc_id"]: confluence_fingerprint(d) for d in docs}
        return self.ingest_documents("confluence", docs, fingerprints)

    def ingest_openapi(self, repo: OpenApiRepository, sources: list[OpenApiSource]) -> IngestSummary:
        docs: list[Document] = []
        succeeded: list[str] = []
        failed: list[str] = []
        for source in sources:
            try:
                spec = repo.fetch_spec(source.spec_url)
            except OpenApiFetchError as e:
                logger.error("OpenAPI 소스 실패 %s: %s", source.name, e)
                failed.append(source.name)
                continue
            docs.extend(openapi_document_service.build_documents(spec, source))
            succeeded.append(source.name)
        fingerprints = {d.metadata["doc_id"]: openapi_fingerprint(d) for d in docs}
        # 수집에 성공한 서비스의 문서만 삭제 대상으로 본다
        summary = self.ingest_documents(
            "openapi", docs, fingerprints,
            removable=lambda doc_id: any(doc_id.startswith(f"{name}:") for name in succeeded),
        )
        summary.failed_sources = failed
        return summary

    def reset_all(self) -> None:
        self._store.reset()
        self._manifest.clear()
        self._manifest.save()
```

`ingest.py`:
```python
"""인제스트 CLI.

python ingest.py --active-profile=local --source all|confluence|openapi [--full]
"""
import argparse
import sys

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger
from src.repository.confluence_repository import ConfluenceAuthError, ConfluenceFetchError, ConfluenceRepository
from src.repository.openapi_repository import OpenApiRepository
from src.repository.vector_store_repository import VectorStoreRepository
from src.service.ingest_service import IngestService, IngestSummary
from src.service.manifest import Manifest

logger = GlobalLogger.get_logger("ingest")


def _print_summary(summaries: list[IngestSummary]) -> None:
    print("\n=== 인제스트 결과 ===")
    for s in summaries:
        line = f"[{s.source}] 추가 {s.added} / 갱신 {s.changed} / 삭제 {s.removed} / 청크 {s.chunk_count}"
        if s.failed_sources:
            line += f" / 실패 소스: {', '.join(s.failed_sources)}"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--active-profile", default="local")
    parser.add_argument("--source", choices=["all", "confluence", "openapi"], default="all")
    parser.add_argument("--full", action="store_true", help="컬렉션과 manifest 를 초기화하고 전체 재구축")
    args = parser.parse_args()

    retrieval = Profile().get_config("retrieval")
    store = VectorStoreRepository.from_profile()
    manifest = Manifest(Profile().get_config("chroma")["manifest-path"])
    service = IngestService(store, manifest, int(retrieval["chunk-size"]), int(retrieval["chunk-overlap"]))

    if args.full:
        logger.info("--full: 컬렉션 및 manifest 초기화")
        service.reset_all()

    summaries: list[IngestSummary] = []
    exit_code = 0
    if args.source in ("all", "confluence"):
        try:
            repo = ConfluenceRepository.from_profile()
            summaries.append(service.ingest_confluence(repo, Profile().get_config("confluence")["base-url"]))
        except ConfluenceAuthError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 1
        except ConfluenceFetchError as e:
            logger.error("Confluence 수집 실패: %s", e)
            summaries.append(IngestSummary(source="confluence", failed_sources=["confluence"]))
            exit_code = 1
    if args.source in ("all", "openapi"):
        summary = service.ingest_openapi(OpenApiRepository(), OpenApiRepository.sources_from_profile())
        summaries.append(summary)
        if summary.failed_sources:
            exit_code = 1

    _print_summary(summaries)
    print(f"컬렉션 청크 수: {store.count()}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_manifest.py test/test_ingest_service.py -v`
Expected: 8 PASSED

- [ ] **Step 5: CLI 동작 확인(Ollama·토큰 준비된 경우)**

사전 조건: `ollama serve` 실행 중, `ollama pull bge-m3` 완료, `export CONFLUENCE_API_TOKEN=...`, `resources/config_local.ini`의 `[confluence] email` 입력(커밋하지 않음).

Run: `python ingest.py --active-profile=local --source openapi`
Expected: `[openapi] 추가 N / 갱신 0 / 삭제 0 / 청크 N` (N ≈ 199 = 152 endpoints + 47 schemas), 종료코드 0. 같은 명령 재실행 시 `추가 0 / 갱신 0`.

Run: `python ingest.py --active-profile=local --source confluence`
Expected: `[confluence] 추가 200+ ...`. 토큰이 없으면 `오류: Confluence 인증 실패(401)...` 와 종료코드 1.

준비가 안 됐으면 이 Step은 건너뛰고 README(Task 13)에 절차를 남긴다.

- [ ] **Step 6: 커밋**

```bash
git add src/service/manifest.py src/service/ingest_service.py ingest.py test/test_manifest.py test/test_ingest_service.py
git commit -m "$(cat <<'EOF'
manifest 기반 증분 인제스트 서비스와 CLI 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 하이브리드 검색 서비스 (BM25 + 벡터)

**Files:**
- Create: `src/service/retriever_service.py`
- Test: `test/test_retriever_service.py`

**Interfaces:**
- Consumes: `VectorStoreRepository.get_all()/as_retriever()/count()`(Task 7), `Profile().get_config("retrieval")`
- Produces:
  - `tokenize(text: str) -> list[str]` — BM25 전처리 함수
  - `RetrieverService(vector_store, bm25_k: int, vector_k: int, bm25_weight: float, vector_weight: float, top_k: int)`
  - `RetrieverService.from_profile(vector_store) -> RetrieverService`
  - `.reload() -> int` — Chroma 전체 청크 로드 → 소스별 BM25 인덱스 구성, 청크 수 반환
  - `.chunk_count: int`
  - `.search(query: str, source: str = "all", top_k: int | None = None) -> list[Document]` — `chunk_id` 기준 중복 제거된 상위 `top_k`. 인덱스가 비어 있으면 `[]`.

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_retriever_service.py`:
```python
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.repository.vector_store_repository import VectorStoreRepository
from src.service.retriever_service import RetrieverService, tokenize


def _chunk(chunk_id, text, source="confluence"):
    return Document(page_content=text, metadata={
        "chunk_id": chunk_id, "chunk_index": 0, "doc_id": chunk_id.split("#")[0], "source": source,
        "title": chunk_id, "url": "https://x", "section": "",
    })


def _service(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    store.upsert([
        _chunk("c1#0", "[가이드 > 인증] 인증 서버는 토큰을 발급한다."),
        _chunk("c2#0", "[가이드 > 배포] 배포는 docker-compose 로 한다."),
        _chunk("o1#0", "## POST /v1/messages/message — Add Message\n메시지를 등록한다.", "openapi"),
        _chunk("o2#0", "## GET /v1/topics — List Topics\n주제 목록.", "openapi"),
    ])
    svc = RetrieverService(store, bm25_k=4, vector_k=4, bm25_weight=0.5, vector_weight=0.5, top_k=3)
    svc.reload()
    return svc, store


def test_tokenize_keeps_paths_and_adds_korean_bigrams():
    tokens = tokenize("GET /v1/messages/{service_key} 메시지 조회")
    assert "get" in tokens
    assert "/v1/messages/{service_key}" in tokens
    assert "messages" in tokens          # 경로 조각
    assert "메시지" in tokens and "메시" in tokens and "시지" in tokens
    assert "조회" in tokens


def test_reload_counts_chunks(tmp_path):
    svc, _ = _service(tmp_path)
    assert svc.chunk_count == 4


def test_exact_path_query_hits_openapi_chunk(tmp_path):
    svc, _ = _service(tmp_path)
    results = svc.search("/v1/messages/message 호출 방법")
    # 가짜 임베딩(해시 기반)의 벡터 점수는 의미가 없으므로 BM25 가 끌어올린 정확 매칭이 상위 k 안에 드는지만 본다
    assert "o1#0" in [r.metadata["chunk_id"] for r in results]
    assert len(results) <= 3
    assert len({r.metadata["chunk_id"] for r in results}) == len(results)  # 중복 없음


def test_source_filter(tmp_path):
    svc, _ = _service(tmp_path)
    results = svc.search("토큰 발급", source="openapi")
    assert results and all(r.metadata["source"] == "openapi" for r in results)
    results = svc.search("메시지 등록", source="confluence")
    assert results and all(r.metadata["source"] == "confluence" for r in results)


def test_top_k_override(tmp_path):
    svc, _ = _service(tmp_path)
    assert len(svc.search("인증", top_k=1)) == 1


def test_empty_store_returns_nothing(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "empty"), "test_col", DeterministicFakeEmbedding(size=16))
    svc = RetrieverService(store, 4, 4, 0.5, 0.5, 3)
    assert svc.reload() == 0
    assert svc.search("아무거나") == []


def test_reload_picks_up_new_chunks(tmp_path):
    svc, store = _service(tmp_path)
    store.upsert([_chunk("c3#0", "[가이드 > 모니터링] 그라파나 대시보드 주소.")])
    assert svc.chunk_count == 4
    svc.reload()
    assert svc.chunk_count == 5
    # RRF 는 두 목록(BM25·벡터)에 모두 등장한 문서를 우선하므로, 가짜 임베딩 환경에서는 전체(k=5)를 조회해 포함 여부만 본다
    assert "c3#0" in [r.metadata["chunk_id"] for r in svc.search("그라파나 대시보드", top_k=5)]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_retriever_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/service/retriever_service.py`:
```python
"""BM25(인메모리) + Chroma 벡터 검색을 RRF 로 결합하는 하이브리드 리트리버."""
import re

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger
from src.repository.vector_store_repository import VectorStoreRepository

logger = GlobalLogger.get_logger(__name__)

SOURCE_ALL = "all"
_TOKEN_RE = re.compile(r"[a-z0-9_{}./\-]+|[가-힣]+")


def tokenize(text: str) -> list[str]:
    """소문자화 → 영숫자/경로 토큰과 한글 토큰 분리. 한글은 2-gram 을, 경로는 조각을 추가한다."""
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        tokens.append(token)
        if "/" in token:
            tokens.extend(seg for seg in token.strip("/").split("/") if seg)
        elif "가" <= token[0] <= "힣" and len(token) > 2:
            tokens.extend(token[i:i + 2] for i in range(len(token) - 1))
    return tokens


class RetrieverService:
    def __init__(self, vector_store: VectorStoreRepository, bm25_k: int, vector_k: int,
                 bm25_weight: float, vector_weight: float, top_k: int):
        self._store = vector_store
        self._bm25_k = bm25_k
        self._vector_k = vector_k
        self._weights = [bm25_weight, vector_weight]
        self._top_k = top_k
        self._bm25: dict[str, BM25Retriever] = {}
        self.chunk_count = 0

    @classmethod
    def from_profile(cls, vector_store: VectorStoreRepository) -> "RetrieverService":
        c = Profile().get_config("retrieval")
        return cls(vector_store, int(c["bm25-k"]), int(c["vector-k"]),
                   float(c["bm25-weight"]), float(c["vector-weight"]), int(c["top-k"]))

    def reload(self) -> int:
        chunks = self._store.get_all()
        self.chunk_count = len(chunks)
        self._bm25 = {}
        groups: dict[str, list[Document]] = {SOURCE_ALL: chunks}
        for chunk in chunks:
            groups.setdefault(chunk.metadata.get("source", ""), []).append(chunk)
        for source, docs in groups.items():
            if docs:
                self._bm25[source] = BM25Retriever.from_documents(docs, preprocess_func=tokenize, k=self._bm25_k)
        logger.info("검색 인덱스 로드: 청크 %s개, 소스 %s", self.chunk_count, sorted(k for k in groups if k != SOURCE_ALL))
        return self.chunk_count

    def search(self, query: str, source: str = SOURCE_ALL, top_k: int | None = None) -> list[Document]:
        k = top_k or self._top_k
        bm25 = self._bm25.get(source)
        if bm25 is None:
            return []
        vector = self._store.as_retriever(k=self._vector_k, source=None if source == SOURCE_ALL else source)
        ensemble = EnsembleRetriever(retrievers=[bm25, vector], weights=self._weights)
        results: list[Document] = []
        seen: set[str] = set()
        for doc in ensemble.invoke(query):
            chunk_id = doc.metadata.get("chunk_id")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            results.append(doc)
            if len(results) >= k:
                break
        return results
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_retriever_service.py -v`
Expected: 7 PASSED. (`[검증]` 계획 작성 시 동일 데이터로 `EnsembleRetriever` 0.5/0.5 실행 결과 `o1#0`이 1위, 0.4/0.6에서는 3위였다 — 가짜 임베딩 환경에서 순위는 가중치에 민감하므로 테스트는 포함 여부만 확인한다.)

- [ ] **Step 5: 커밋**

```bash
git add src/service/retriever_service.py test/test_retriever_service.py
git commit -m "$(cat <<'EOF'
BM25 + 벡터 하이브리드 검색 서비스 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: RAG 답변 생성 서비스 (프롬프트·인용·스트리밍)

**Files:**
- Create: `src/service/rag_service.py`
- Test: `test/test_rag_service.py`

**Interfaces:**
- Consumes: `RetrieverService.search(query, source, top_k)`(Task 9), `llm_factory.create_chat_model()`(Task 7)
- Produces:
  - `NOT_FOUND_ANSWER = "관련 내용을 문서에서 찾지 못했습니다."`
  - `build_context(chunks: list[Document]) -> tuple[str, list[dict]]` — `(컨텍스트 문자열, sources)`; `sources[i] = {"index": i+1, "title", "url", "source", "snippet"}`
  - `RagService(retriever, chat_model)`
  - `RagService.from_profile(retriever) -> RagService`
  - `.ask(question: str, source: str = "all", top_k: int | None = None) -> dict` — `{"answer": str, "sources": list[dict]}`
  - `async .ask_stream(question, source="all", top_k=None) -> AsyncIterator[dict]` — `{"event": "token", "data": str}` 반복 → `{"event": "sources", "data": list[dict]}` → `{"event": "done", "data": ""}`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_rag_service.py`:
```python
import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.service.rag_service import NOT_FOUND_ANSWER, RagService, build_context


def _chunk(chunk_id, text, source="confluence", title="제목", url="https://x/1"):
    return Document(page_content=text, metadata={
        "chunk_id": chunk_id, "doc_id": chunk_id.split("#")[0], "source": source, "title": title, "url": url,
    })


class StubRetriever:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def search(self, query, source="all", top_k=None):
        self.calls.append((query, source, top_k))
        return self._chunks


class ExplodingModel:
    def invoke(self, *_):
        raise AssertionError("검색 결과가 없으면 LLM 을 호출하지 않아야 한다")


def test_build_context_numbering_and_sources():
    chunks = [_chunk("1#0", "[루트 > 인증]\n토큰은 헤더로 전달한다."),
              _chunk("s:GET:/a#0", "## GET /a — 목록\n설명", "openapi", "GET /a", "https://x/docs")]
    context, sources = build_context(chunks)
    assert context.startswith("[1] 제목 | https://x/1\n")
    assert "[2] GET /a | https://x/docs\n## GET /a — 목록" in context
    assert sources == [
        {"index": 1, "title": "제목", "url": "https://x/1", "source": "confluence", "snippet": "토큰은 헤더로 전달한다."},
        {"index": 2, "title": "GET /a", "url": "https://x/docs", "source": "openapi", "snippet": "## GET /a — 목록\n설명"},
    ]


def test_snippet_is_truncated_to_200_chars():
    _, sources = build_context([_chunk("1#0", "가" * 500)])
    assert len(sources[0]["snippet"]) == 200


def test_ask_returns_answer_with_sources():
    retriever = StubRetriever([_chunk("1#0", "토큰은 헤더로 전달한다.")])
    service = RagService(retriever, FakeListChatModel(responses=["토큰은 헤더로 전달합니다 [1]"]))
    result = service.ask("토큰 어디에 넣어?", source="confluence", top_k=2)
    assert result["answer"] == "토큰은 헤더로 전달합니다 [1]"
    assert result["sources"][0]["index"] == 1
    assert retriever.calls == [("토큰 어디에 넣어?", "confluence", 2)]


def test_ask_without_results_skips_llm():
    service = RagService(StubRetriever([]), ExplodingModel())
    assert service.ask("아무거나") == {"answer": NOT_FOUND_ANSWER, "sources": []}


@pytest.mark.asyncio
async def test_ask_stream_emits_tokens_then_sources_then_done():
    retriever = StubRetriever([_chunk("1#0", "본문")])
    service = RagService(retriever, FakeListChatModel(responses=["답변"]))
    events = [e async for e in service.ask_stream("질문")]
    assert "".join(e["data"] for e in events if e["event"] == "token") == "답변"
    assert events[-2]["event"] == "sources" and events[-2]["data"][0]["index"] == 1
    assert events[-1] == {"event": "done", "data": ""}


@pytest.mark.asyncio
async def test_ask_stream_without_results():
    service = RagService(StubRetriever([]), ExplodingModel())
    events = [e async for e in service.ask_stream("질문")]
    assert events == [{"event": "token", "data": NOT_FOUND_ANSWER},
                      {"event": "sources", "data": []},
                      {"event": "done", "data": ""}]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_rag_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/service/rag_service.py`:
```python
"""검색 결과를 근거로 LLM 답변을 생성한다. 단일 질의(멀티턴 없음)."""
from typing import AsyncIterator

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from src.service import llm_factory

NOT_FOUND_ANSWER = "관련 내용을 문서에서 찾지 못했습니다."
_SNIPPET_LEN = 200

SYSTEM_PROMPT = """당신은 팀 내부 문서(Confluence)와 API 명세(OpenAPI)를 근거로 답하는 어시스턴트입니다.

규칙:
1. 아래 제공된 문서 내용만 근거로 답합니다. 문서에 없는 내용은 추측하지 않습니다.
2. 근거로 사용한 문서는 문장 끝에 [1], [2] 형식으로 번호를 인용합니다.
3. 문서에서 답을 찾을 수 없으면 정확히 "관련 내용을 문서에서 찾지 못했습니다."라고만 답합니다.
4. API 관련 질문에는 HTTP 메서드, 경로, 필수 파라미터/필드를 명시합니다.
5. 한국어로 간결하게 답합니다."""

_USER_TEMPLATE = """다음은 검색된 문서입니다.

{context}

---
질문: {question}"""


def _strip_prefix(text: str) -> str:
    """청킹 시 붙인 '[breadcrumb > section]' 첫 줄은 스니펫에서 제외한다."""
    first, sep, rest = text.partition("\n")
    return rest if first.startswith("[") and first.endswith("]") and sep else text


def build_context(chunks: list[Document]) -> tuple[str, list[dict]]:
    blocks, sources = [], []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        blocks.append(f"[{i}] {meta.get('title', '')} | {meta.get('url', '')}\n{chunk.page_content}")
        sources.append({
            "index": i,
            "title": meta.get("title", ""),
            "url": meta.get("url", ""),
            "source": meta.get("source", ""),
            "snippet": _strip_prefix(chunk.page_content).strip()[:_SNIPPET_LEN],
        })
    return "\n\n".join(blocks), sources


class RagService:
    def __init__(self, retriever, chat_model):
        self._retriever = retriever
        self._model = chat_model

    @classmethod
    def from_profile(cls, retriever) -> "RagService":
        return cls(retriever, llm_factory.create_chat_model())

    def _messages(self, question: str, context: str) -> list:
        return [SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=_USER_TEMPLATE.format(context=context, question=question))]

    def ask(self, question: str, source: str = "all", top_k: int | None = None) -> dict:
        chunks = self._retriever.search(question, source, top_k)
        if not chunks:
            return {"answer": NOT_FOUND_ANSWER, "sources": []}
        context, sources = build_context(chunks)
        response = self._model.invoke(self._messages(question, context))
        return {"answer": response.content, "sources": sources}

    async def ask_stream(self, question: str, source: str = "all", top_k: int | None = None) -> AsyncIterator[dict]:
        chunks = self._retriever.search(question, source, top_k)
        if not chunks:
            yield {"event": "token", "data": NOT_FOUND_ANSWER}
            yield {"event": "sources", "data": []}
            yield {"event": "done", "data": ""}
            return
        context, sources = build_context(chunks)
        async for piece in self._model.astream(self._messages(question, context)):
            if piece.content:
                yield {"event": "token", "data": piece.content}
        yield {"event": "sources", "data": sources}
        yield {"event": "done", "data": ""}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_rag_service.py -v`
Expected: 6 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/service/rag_service.py test/test_rag_service.py
git commit -m "$(cat <<'EOF'
RAG 답변 생성 서비스 추가 (근거 인용 프롬프트, SSE용 스트리밍)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: FastAPI 서버 (DTO, 컨트롤러, main.py)

**Files:**
- Create: `src/dto/__init__.py`, `src/dto/ask_dto.py`
- Create: `src/controller/__init__.py`, `src/controller/ask_controller.py`
- Create: `main.py`
- Test: `test/test_ask_controller.py`

**Interfaces:**
- Consumes: `RetrieverService`(Task 9), `RagService`(Task 10), `VectorStoreRepository.from_profile()`(Task 7), `llm_factory.ping_ollama()`(Task 7), `Profile`(Task 1)
- Produces:
  - DTO: `AskRequest(question: str, source: Literal["all","confluence","openapi"]="all", top_k: int|None=None)`, `SourceRef(index,title,url,source,snippet)`, `AskResponse(answer: str, sources: list[SourceRef])`, `ReloadResponse(chunk_count: int)`, `HealthResponse(status: str, ollama: bool, chunk_count: int)`
  - `ask_controller.RagContext(retriever, rag_service)`; 모듈 변수 `ask_controller.context: RagContext | None`; `ask_controller.init_context() -> RagContext`(프로파일로 생성 + `reload()`); `ask_controller.get_context() -> RagContext`
  - `ask_controller.router: APIRouter` — `POST /{api_root}/ask`, `POST /{api_root}/ask/stream`, `POST /{api_root}/reload`, `GET /{health_check_endpoint}`
  - SSE 포맷: `event: <name>\ndata: <JSON 문자열>\n\n` (token 의 data 는 JSON 인코딩된 문자열, sources 는 JSON 배열)
  - `main.app: FastAPI`

- [ ] **Step 1: 실패하는 테스트 작성**

`test/test_ask_controller.py`:
```python
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.controller import ask_controller
from src.service.rag_service import RagService


def _chunk(chunk_id, text, source="confluence"):
    return Document(page_content=text, metadata={
        "chunk_id": chunk_id, "doc_id": chunk_id.split("#")[0], "source": source, "title": "제목", "url": "https://x/1",
    })


class StubRetriever:
    def __init__(self, chunks):
        self._chunks = chunks
        self.chunk_count = len(chunks)
        self.reload_calls = 0

    def search(self, query, source="all", top_k=None):
        return self._chunks

    def reload(self):
        self.reload_calls += 1
        self.chunk_count = 42
        return self.chunk_count


class ConnectErrorModel:
    def invoke(self, *_):
        raise httpx.ConnectError("connection refused")


class TimeoutModel:
    def invoke(self, *_):
        raise httpx.ReadTimeout("timed out")


@pytest.fixture
def client(monkeypatch):
    import main  # noqa: F401 — 앱 생성 (startup 에서 init_context 를 호출하지 않도록 아래에서 context 를 먼저 세팅)
    retriever = StubRetriever([_chunk("1#0", "토큰은 헤더로 전달한다.")])
    ask_controller.context = ask_controller.RagContext(retriever, RagService(retriever, FakeListChatModel(responses=["헤더로 전달 [1]"])))
    monkeypatch.setattr(ask_controller.llm_factory, "ping_ollama", lambda: True)
    with TestClient(main.app) as c:
        yield c, retriever


def test_ask(client):
    c, _ = client
    res = c.post("/v1/ask", json={"question": "토큰 어디에?", "source": "confluence"})
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "헤더로 전달 [1]"
    assert body["sources"][0] == {"index": 1, "title": "제목", "url": "https://x/1", "source": "confluence",
                                  "snippet": "토큰은 헤더로 전달한다."}


def test_ask_validation(client):
    c, _ = client
    assert c.post("/v1/ask", json={"question": ""}).status_code == 422
    assert c.post("/v1/ask", json={"question": "q", "source": "jira"}).status_code == 422
    assert c.post("/v1/ask", json={"question": "q", "top_k": 0}).status_code == 422


def test_ask_stream_sse(client):
    c, _ = client
    with c.stream("POST", "/v1/ask/stream", json={"question": "q"}) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        raw = "".join(res.iter_text())
    events = [blk.split("\n", 1) for blk in raw.strip().split("\n\n")]
    parsed = [(e[0].removeprefix("event: "), json.loads(e[1].removeprefix("data: "))) for e in events]
    assert "".join(d for n, d in parsed if n == "token") == "헤더로 전달 [1]"
    assert parsed[-2][0] == "sources" and parsed[-2][1][0]["index"] == 1
    assert parsed[-1] == ("done", "")


def test_reload(client):
    c, retriever = client
    res = c.post("/v1/reload")
    assert res.status_code == 200 and res.json() == {"chunk_count": 42}
    assert retriever.reload_calls == 1


def test_check_ok_and_degraded(client, monkeypatch):
    c, retriever = client
    assert c.get("/check").json() == {"status": "ok", "ollama": True, "chunk_count": 1}
    monkeypatch.setattr(ask_controller.llm_factory, "ping_ollama", lambda: False)
    assert c.get("/check").json()["status"] == "degraded"


def test_ollama_down_returns_503(client):
    c, retriever = client
    ask_controller.context = ask_controller.RagContext(retriever, RagService(retriever, ConnectErrorModel()))
    res = c.post("/v1/ask", json={"question": "q"})
    assert res.status_code == 503
    assert "Ollama" in res.json()["detail"]


def test_llm_timeout_returns_504(client):
    c, retriever = client
    ask_controller.context = ask_controller.RagContext(retriever, RagService(retriever, TimeoutModel()))
    assert c.post("/v1/ask", json={"question": "q"}).status_code == 504


def test_root_serves_ui(client):
    c, _ = client
    res = c.get("/")
    assert res.status_code == 200 and "text/html" in res.headers["content-type"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest --active-profile=local test/test_ask_controller.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.controller'`

- [ ] **Step 3: 구현**

`src/dto/__init__.py`, `src/controller/__init__.py`: 빈 파일.

`src/dto/ask_dto.py`:
```python
from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceFilter = Literal["all", "confluence", "openapi"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="질문")
    source: SourceFilter = Field(default="all", description="검색 대상 소스")
    top_k: Optional[int] = Field(default=None, ge=1, le=20, description="검색 청크 수(미지정 시 설정값)")


class SourceRef(BaseModel):
    index: int
    title: str
    url: str
    source: str
    snippet: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceRef]


class ReloadResponse(BaseModel):
    chunk_count: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama: bool
    chunk_count: int
```

`src/controller/ask_controller.py`:
```python
"""질의/재로드/헬스체크 엔드포인트."""
import json
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.config.profile import Profile
from src.dto.ask_dto import AskRequest, AskResponse, HealthResponse, ReloadResponse
from src.library.global_logger import GlobalLogger
from src.repository.vector_store_repository import VectorStoreRepository
from src.service import llm_factory
from src.service.rag_service import RagService
from src.service.retriever_service import RetrieverService

logger = GlobalLogger.get_logger(__name__)
router = APIRouter()

__api_root = Profile().api_root
__health_endpoint = Profile().get_common_config()["health_check_endpoint"]

_OLLAMA_DOWN_DETAIL = "Ollama 에 연결할 수 없습니다. `ollama serve` 실행 여부와 [ollama] base-url 설정을 확인하세요."
_LLM_TIMEOUT_DETAIL = "LLM 응답 시간이 초과되었습니다. [ollama] llm-timeout 을 늘리거나 더 작은 모델을 사용하세요."


@dataclass
class RagContext:
    retriever: RetrieverService
    rag_service: RagService


context: RagContext | None = None


def init_context() -> RagContext:
    global context
    retriever = RetrieverService.from_profile(VectorStoreRepository.from_profile())
    retriever.reload()
    context = RagContext(retriever, RagService.from_profile(retriever))
    return context


def get_context() -> RagContext:
    return context or init_context()


def _translate_llm_error(e: Exception) -> HTTPException:
    if isinstance(e, httpx.TimeoutException):
        return HTTPException(status_code=504, detail=_LLM_TIMEOUT_DETAIL)
    return HTTPException(status_code=503, detail=_OLLAMA_DOWN_DETAIL)


@router.post(f"/{__api_root}/ask", response_model=AskResponse, tags=["질의"])
async def ask(request: AskRequest):
    try:
        return get_context().rag_service.ask(request.question, request.source, request.top_k)
    except (httpx.HTTPError, ConnectionError) as e:
        logger.error("LLM 호출 실패: %s", e)
        raise _translate_llm_error(e)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(f"/{__api_root}/ask/stream", tags=["질의"])
async def ask_stream(request: AskRequest):
    rag = get_context().rag_service

    async def generate():
        try:
            async for ev in rag.ask_stream(request.question, request.source, request.top_k):
                yield _sse(ev["event"], ev["data"])
        except (httpx.HTTPError, ConnectionError) as e:
            logger.error("LLM 스트리밍 실패: %s", e)
            yield _sse("error", _translate_llm_error(e).detail)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post(f"/{__api_root}/reload", response_model=ReloadResponse, tags=["관리"])
async def reload():
    return ReloadResponse(chunk_count=get_context().retriever.reload())


@router.get(f"/{__health_endpoint}", response_model=HealthResponse, tags=["health check"])
async def health_check():
    ollama_ok = llm_factory.ping_ollama()
    chunk_count = get_context().retriever.chunk_count
    status = "ok" if ollama_ok and chunk_count > 0 else "degraded"
    return HealthResponse(status=status, ollama=ollama_ok, chunk_count=chunk_count)
```

`main.py`:
```python
"""KUDOS RAG API 진입점.

python main.py --active-profile=local
"""
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import global_variable
from src.config.profile import Profile
from src.controller import ask_controller

__fastapi_config = Profile().get_config("fastapi")
__swagger_config = Profile().get_config("swagger")
__common_config = Profile().get_common_config()
__STATIC_DIR = f"{global_variable.PROJECT_RESOURCE_DIR}/static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    # 기동 시 검색 인덱스 로드. 테스트에서 context 를 미리 주입한 경우 재생성하지 않는다
    if ask_controller.context is None:
        ask_controller.init_context()
    yield


app = FastAPI(
    title=__swagger_config["title"],
    summary=__swagger_config.get("summary", ""),
    version=__common_config["version"],
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=__STATIC_DIR), name="static")
app.include_router(ask_controller.router)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(f"{__STATIC_DIR}/index.html", media_type="text/html")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=__fastapi_config["host"],
        port=int(__fastapi_config["port"]),
        reload=__fastapi_config.get("reload", "False").lower() == "true",
    )
```

`resources/static/index.html`은 Task 12에서 작성하지만 `test_root_serves_ui`가 필요로 하므로 이 Task에서는 임시로 아래 한 줄 파일을 만든다:
```html
<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>KUDOS RAG</title></head><body>KUDOS RAG</body></html>
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest --active-profile=local test/test_ask_controller.py -v`
Expected: 8 PASSED. (`[검증]` FastAPI 0.141에서 `@app.on_event`는 deprecated 경고를 내므로 `lifespan`을 사용한다. 계획 작성 시 이 코드로 드라이런하여 8개 통과 확인함.)

- [ ] **Step 5: 서버 기동 확인(Ollama 준비된 경우)**

Run: `python main.py --active-profile=local` → 다른 터미널에서
```bash
curl -s http://127.0.0.1:5010/check
curl -s -X POST http://127.0.0.1:5010/v1/ask -H 'Content-Type: application/json' \
  -d '{"question":"메시지 등록 API 호출 방법 알려줘","source":"openapi"}'
```
Expected: `/check` → `{"status":"ok","ollama":true,"chunk_count":N}`; `/v1/ask` → `POST /v1/messages/message` 를 언급하는 answer 와 sources 배열. Swagger UI는 `http://127.0.0.1:5010/docs`.

- [ ] **Step 6: 커밋**

```bash
git add src/dto/ src/controller/ main.py resources/static/index.html test/test_ask_controller.py
git commit -m "$(cat <<'EOF'
FastAPI 서버 추가: /v1/ask, /v1/ask/stream(SSE), /v1/reload, /check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: 최소 웹 채팅 UI

**Files:**
- Modify: `resources/static/index.html` (Task 11의 임시 파일 교체)

**Interfaces:**
- Consumes: `POST /v1/ask/stream` SSE(`token`/`sources`/`done`/`error` 이벤트, data 는 JSON), `GET /check`
- Produces: 없음(정적 파일). 자동 테스트 없음 — 수동 확인 Step 으로 검증.

- [ ] **Step 1: index.html 작성**

`resources/static/index.html`:
```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KUDOS RAG</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --text:#1f2328; --muted:#656d76; --accent:#0969da; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif; background:var(--bg); color:var(--text); }
  header { padding:14px 20px; background:var(--card); border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:center; }
  header h1 { font-size:16px; margin:0; }
  #health { font-size:12px; color:var(--muted); }
  main { max-width: 900px; margin: 0 auto; padding: 16px; }
  #log { display:flex; flex-direction:column; gap:12px; min-height: 50vh; }
  .msg { padding:12px 14px; border-radius:10px; background:var(--card); border:1px solid var(--line); white-space:pre-wrap; line-height:1.55; }
  .msg.q { background:#e7f0ff; border-color:#c9dcf7; align-self:flex-end; max-width:80%; }
  .sources { display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap:8px; margin-top:8px; }
  .src { font-size:12px; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:#fafbfc; }
  .src a { color:var(--accent); text-decoration:none; font-weight:600; }
  .src .tag { display:inline-block; padding:1px 6px; border-radius:6px; font-size:11px; margin-left:4px; background:#ddf4ff; color:#0550ae; }
  .src .tag.openapi { background:#dafbe1; color:#116329; }
  .src .snip { color:var(--muted); margin-top:4px; max-height: 60px; overflow:hidden; }
  form { position:sticky; bottom:0; margin-top:16px; padding:12px 0; background:var(--bg); display:flex; gap:8px; }
  select, input, button { font: inherit; padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:var(--card); }
  input { flex:1; }
  button { background:var(--accent); color:#fff; border-color:var(--accent); cursor:pointer; }
  button:disabled { opacity:.6; cursor:default; }
  .err { color:#cf222e; }
</style>
</head>
<body>
<header>
  <h1>KUDOS RAG</h1>
  <span id="health">상태 확인 중…</span>
</header>
<main>
  <div id="log"></div>
  <form id="form">
    <select id="source" title="검색 대상">
      <option value="all">전체</option>
      <option value="confluence">Confluence</option>
      <option value="openapi">OpenAPI</option>
    </select>
    <input id="question" placeholder="예: 메시지 등록 API 호출 방법 알려줘" autocomplete="off" required>
    <button id="send" type="submit">질문</button>
  </form>
</main>
<script>
const log = document.getElementById('log');
const form = document.getElementById('form');
const input = document.getElementById('question');
const sourceSel = document.getElementById('source');
const sendBtn = document.getElementById('send');

async function refreshHealth() {
  try {
    const r = await fetch('/check');
    const h = await r.json();
    document.getElementById('health').textContent =
      `상태: ${h.status} · Ollama ${h.ollama ? '연결됨' : '끊김'} · 청크 ${h.chunk_count}개`;
  } catch (e) {
    document.getElementById('health').textContent = '상태 확인 실패';
  }
}
refreshHealth();

function addMessage(cls, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.textContent = text;
  log.appendChild(el);
  el.scrollIntoView({ block: 'end' });
  return el;
}

function renderSources(container, sources) {
  if (!sources.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'sources';
  for (const s of sources) {
    const card = document.createElement('div');
    card.className = 'src';
    const a = document.createElement('a');
    a.href = s.url; a.target = '_blank'; a.rel = 'noopener';
    a.textContent = `[${s.index}] ${s.title}`;
    const tag = document.createElement('span');
    tag.className = 'tag ' + s.source; tag.textContent = s.source;
    const snip = document.createElement('div');
    snip.className = 'snip'; snip.textContent = s.snippet;
    card.append(a, tag, snip);
    wrap.appendChild(card);
  }
  container.appendChild(wrap);
}

// POST 기반 SSE: EventSource 는 GET 만 지원하므로 fetch 스트림을 직접 파싱한다
async function ask(question, source) {
  const answerEl = addMessage('a', '');
  const res = await fetch('/v1/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, source }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail || res.statusText;
    answerEl.classList.add('err'); answerEl.textContent = `오류 ${res.status}: ${detail}`;
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
      const evLine = block.split('\n').find(l => l.startsWith('event: '));
      const dataLine = block.split('\n').find(l => l.startsWith('data: '));
      if (!evLine || !dataLine) continue;
      const event = evLine.slice(7);
      const data = JSON.parse(dataLine.slice(6));
      if (event === 'token') { answerEl.textContent += data; answerEl.scrollIntoView({ block: 'end' }); }
      else if (event === 'sources') renderSources(answerEl, data);
      else if (event === 'error') { answerEl.classList.add('err'); answerEl.textContent = data; }
    }
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  addMessage('q', q);
  input.value = '';
  sendBtn.disabled = true;
  try { await ask(q, sourceSel.value); }
  catch (err) { addMessage('a err', '요청 실패: ' + err.message); }
  finally { sendBtn.disabled = false; input.focus(); }
});
</script>
</body>
</html>
```

- [ ] **Step 2: 컨트롤러 테스트로 회귀 확인**

Run: `pytest --active-profile=local test/test_ask_controller.py -v`
Expected: 8 PASSED (`test_root_serves_ui` 포함)

- [ ] **Step 3: 수동 확인(Ollama 준비된 경우)**

`python main.py --active-profile=local` → 브라우저 `http://127.0.0.1:5010/`
- 헤더에 `상태: ok · Ollama 연결됨 · 청크 N개` 표시
- "메시지 등록 API 호출 방법 알려줘" 입력(소스: OpenAPI) → 답변이 토큰 단위로 표시되고 완료 후 소스 카드가 붙는다. 카드 제목 클릭 시 Swagger 페이지가 새 탭으로 열린다.
- Ollama 를 종료하고 질문 → 빨간 오류 메시지(`Ollama 에 연결할 수 없습니다…`)

- [ ] **Step 4: 커밋**

```bash
git add resources/static/index.html
git commit -m "$(cat <<'EOF'
최소 웹 채팅 UI 추가 (SSE 스트리밍, 소스 카드)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: 검색 품질 평가 스크립트, 통합 테스트, README

**Files:**
- Create: `eval/__init__.py`, `eval/questions.yaml`, `eval/run_eval.py`
- Create: `test/test_integration_ask.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `RetrieverService`(Task 9), `VectorStoreRepository.from_profile()`(Task 7), `IngestService`(Task 8), `main.app`(Task 11)
- Produces: `python -m eval.run_eval --active-profile=local [--k 6]` → 질문별 hit 여부와 `hit@k` 비율 출력, 80% 미만이면 종료코드 1

- [ ] **Step 1: 평가 질문 세트 작성**

`eval/__init__.py`: 빈 파일.

`eval/questions.yaml` — `expected_doc_ids`는 Confluence 페이지 id 또는 OpenAPI doc_id(`{service}:{METHOD}:{path}`). 아래 OpenAPI 항목은 실제 스펙 기준으로 바로 사용 가능하고, Confluence 항목은 인제스트 후 `data/manifest.json`에서 페이지 id를 찾아 채운다(최소 10개 목표):
```yaml
# 검색 품질 평가 세트. expected_doc_ids 중 하나라도 상위 k 청크에 포함되면 hit.
questions:
  - question: 메시지 등록 API 호출 방법 알려줘
    source: openapi
    expected_doc_ids: ["message-api:POST:/v1/messages/message"]
  - question: MessagePostRequest 필드에 뭐가 있어?
    source: openapi
    expected_doc_ids: ["message-api:schema:MessagePostRequest"]
  - question: 헬스체크 엔드포인트가 뭐야
    source: openapi
    expected_doc_ids: ["message-api:GET:/check", "general-chatbot-api:GET:/check"]
  # --- 아래는 인제스트 후 Confluence 페이지 id 로 채운다 ---
  # - question: 회원 인증(IAM) 서비스 정책 문서 어디 있어
  #   source: confluence
  #   expected_doc_ids: ["<page_id>"]
  # - question: 계열사별 company_setting 마이그레이션 절차
  #   source: confluence
  #   expected_doc_ids: ["<page_id>"]
```

- [ ] **Step 2: 평가 스크립트 작성**

`eval/run_eval.py`:
```python
"""검색 품질 평가: eval/questions.yaml 의 질문마다 상위 k 청크에 기대 문서가 포함되는지 확인한다.

python -m eval.run_eval --active-profile=local [--k 6] [--file eval/questions.yaml]
(Ollama 임베딩이 필요하다)
"""
import argparse
import sys

import yaml

from src.repository.vector_store_repository import VectorStoreRepository
from src.service.retriever_service import RetrieverService

_PASS_RATE = 0.8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-profile", default="local")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--file", default="eval/questions.yaml")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as f:
        questions = (yaml.safe_load(f) or {}).get("questions", [])
    if not questions:
        print("평가 질문이 없습니다.")
        return 1

    retriever = RetrieverService.from_profile(VectorStoreRepository.from_profile())
    retriever.reload()

    hits = 0
    for q in questions:
        results = retriever.search(q["question"], q.get("source", "all"), top_k=args.k)
        found = [d.metadata["doc_id"] for d in results]
        hit = any(doc_id in found for doc_id in q["expected_doc_ids"])
        hits += hit
        print(f"{'O' if hit else 'X'} {q['question']}")
        if not hit:
            print(f"    기대: {q['expected_doc_ids']}")
            print(f"    실제: {found}")

    rate = hits / len(questions)
    print(f"\nhit@{args.k} = {hits}/{len(questions)} = {rate:.0%} (기준 {_PASS_RATE:.0%})")
    return 0 if rate >= _PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 통합 테스트 작성(Ollama 필요, 기본 실행 제외)**

`test/test_integration_ask.py`:
```python
"""Ollama(bge-m3, qwen3:14b)가 떠 있을 때만 실행: pytest --active-profile=local -m integration test/test_integration_ask.py"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from src.controller import ask_controller
from src.repository.vector_store_repository import VectorStoreRepository
from src.service import llm_factory
from src.service.ingest_service import IngestService, openapi_fingerprint
from src.service.manifest import Manifest
from src.service.openapi_document_service import OpenApiSource, build_documents
from src.service.rag_service import RagService
from src.service.retriever_service import RetrieverService

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path):
    if not llm_factory.ping_ollama():
        pytest.skip("Ollama 미기동")
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_it", llm_factory.create_embeddings())
    spec = json.loads((Path(__file__).parent / "fixtures" / "openapi_sample.json").read_text(encoding="utf-8"))
    docs = build_documents(spec, OpenApiSource("message-api", "https://x/openapi.json", "https://x/docs"))
    IngestService(store, Manifest(str(tmp_path / "m.json")), 1000, 150).ingest_documents(
        "openapi", docs, {d.metadata["doc_id"]: openapi_fingerprint(d) for d in docs})
    retriever = RetrieverService.from_profile(store)
    retriever.reload()
    ask_controller.context = ask_controller.RagContext(retriever, RagService.from_profile(retriever))
    import main
    with TestClient(main.app) as c:
        yield c


def test_end_to_end_ask(client):
    res = client.post("/v1/ask", json={"question": "메시지 등록 API 는 어떤 메서드와 경로로 호출해?", "source": "openapi"})
    assert res.status_code == 200
    body = res.json()
    assert "/v1/messages/message" in body["answer"]
    assert any(s["title"] == "POST /v1/messages/message" for s in body["sources"])
```

- [ ] **Step 4: README 작성**

`README.md`:
```markdown
# KUDOS RAG (PoC)

팀 Confluence `KUDOS` 스페이스와 팀 FastAPI 서비스의 OpenAPI 스펙을 근거로 답하는 로컬 RAG.
LLM/임베딩은 로컬 Ollama 만 사용한다(사내 문서를 외부 API 로 보내지 않는다).

설계: `docs/superpowers/specs/2026-09-17-kudos-rag-design.md`

## 사전 준비

1. Ollama
   ```bash
   brew install ollama
   ollama serve            # 별도 터미널
   ollama pull qwen3:14b
   ollama pull bge-m3
   ```
2. Atlassian API 토큰: https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급
   ```bash
   export CONFLUENCE_API_TOKEN=...   # 커밋 금지
   ```
   `resources/config_local.ini` 의 `[confluence] email` 에 Atlassian 계정 이메일 입력.

## 개발 환경

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pip-tools
pip-compile --output-file=requirements.txt requirements.in   # requirements.in 변경 시
pip install -r requirements.txt
```

## 인제스트

```bash
python ingest.py --active-profile=local --source all        # confluence + openapi 증분
python ingest.py --active-profile=local --source openapi    # 특정 소스만
python ingest.py --active-profile=local --full              # 전체 재구축
```
결과는 `data/chroma`(벡터), `data/manifest.json`(증분 기준)에 저장된다.
OpenAPI 대상은 `resources/openapi_sources.yaml` 에 추가한다.

## 서버

```bash
python main.py --active-profile=local
```
- UI: http://127.0.0.1:5010/
- Swagger: http://127.0.0.1:5010/docs
- `POST /v1/ask` `{"question": "...", "source": "all|confluence|openapi", "top_k": 6}`
- `POST /v1/ask/stream` (SSE), `POST /v1/reload` (재인제스트 후 인덱스 재로드), `GET /check`

## 테스트

```bash
pytest --active-profile=local                                  # 단위 테스트 (Ollama 불필요)
pytest --active-profile=local -m integration                   # 통합 테스트 (Ollama 필요)
python -m eval.run_eval --active-profile=local --k 6           # 검색 품질 hit@6 (기준 80%)
```

## 튜닝 포인트 (`resources/config_local.ini` `[retrieval]`)

`chunk-size`, `chunk-overlap`, `top-k`, `bm25-weight`/`vector-weight`. 변경 후 청킹 관련 값은 `--full` 재인제스트가 필요하다.
```

- [ ] **Step 5: 전체 단위 테스트 실행**

Run: `pytest --active-profile=local -v`
Expected: 모든 단위 테스트 PASSED, integration 은 deselected.

- [ ] **Step 6: 평가·통합 테스트 실행(Ollama·인제스트 완료된 경우)**

Run: `python -m eval.run_eval --active-profile=local --k 6`
Expected: 질문별 O/X 와 `hit@6 = …`. 80% 미만이면 `[retrieval]` 가중치·청크 크기를 조정해 재실행한다(청크 크기 변경 시 `python ingest.py --full`).

Run: `pytest --active-profile=local -m integration test/test_integration_ask.py -v`
Expected: 1 PASSED (또는 Ollama 미기동 시 SKIPPED)

- [ ] **Step 7: 커밋**

```bash
git add eval/ test/test_integration_ask.py README.md
git commit -m "$(cat <<'EOF'
검색 품질 평가 스크립트, 통합 테스트, README 추가

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
)"
```

---

## 완료 기준

- `pytest --active-profile=local` 전체 통과(Ollama 없이).
- `python ingest.py --active-profile=local --source all` 이 KUDOS 페이지와 두 OpenAPI 스펙을 인제스트하고, 재실행 시 `추가 0 / 갱신 0`.
- `python main.py` 기동 후 UI 에서 질문 → 스트리밍 답변 + 출처 카드 표시.
- `python -m eval.run_eval` hit@6 ≥ 80% (spec §8).
