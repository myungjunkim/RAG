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
                # title 등 파라미터 값이 본문 텍스트로 새지 않도록 제거한다
                for param in macro.find_all("ac:parameter", recursive=False):
                    param.decompose()
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
