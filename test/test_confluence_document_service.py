from pathlib import Path

from src.service.confluence_document_service import (
    SOURCE_CONFLUENCE,
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


def test_empty_html_returns_empty_string():
    assert convert_storage_to_markdown("") == ""
    assert convert_storage_to_markdown("   \n  ") == ""


def test_code_macro_without_language_uses_bare_fence():
    md = convert_storage_to_markdown(
        '<ac:structured-macro ac:name="code">'
        "<ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body></ac:structured-macro>"
    )
    assert md == "```\nx = 1\n```"


def test_body_only_macro_keeps_inner_text():
    md = convert_storage_to_markdown(
        '<ac:structured-macro ac:name="expand"><ac:rich-text-body><p>숨김 본문</p>'
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert md == "숨김 본문"


def test_body_only_macro_without_body_is_removed():
    md = convert_storage_to_markdown('<p>앞</p><ac:structured-macro ac:name="info"/><p>뒤</p>')
    assert "앞" in md and "뒤" in md
    assert "info" not in md


def test_unknown_macro_is_removed_entirely():
    md = convert_storage_to_markdown(
        '<p>앞</p><ac:structured-macro ac:name="jira">'
        '<ac:parameter ac:name="key">ABC-1</ac:parameter></ac:structured-macro><p>뒤</p>'
    )
    assert "ABC-1" not in md
    assert "앞" in md and "뒤" in md


def test_link_body_and_ri_page_title_fallbacks():
    with_body = convert_storage_to_markdown(
        '<p><ac:link><ri:page ri:content-title="대상 제목"/><ac:link-body>표시 문구</ac:link-body></ac:link></p>'
    )
    assert with_body == "표시 문구"

    only_ri_page = convert_storage_to_markdown('<p><ac:link><ri:page ri:content-title="대상 제목"/></ac:link></p>')
    assert only_ri_page == "대상 제목"


def test_image_and_attachment_are_removed():
    md = convert_storage_to_markdown(
        '<p>전<ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>후</p>'
    )
    assert "diagram.png" not in md
    assert "전" in md and "후" in md


def test_consecutive_blank_lines_are_collapsed():
    md = convert_storage_to_markdown("<p>a</p>" + "<br/>" * 10 + "<p>b</p>")
    # 빈 줄은 최대 2개 → 개행 문자는 최대 3개 연속
    assert "\n\n\n\n" not in md
    assert md.startswith("a") and md.endswith("b")


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


def test_build_breadcrumbs_with_missing_parent_uses_own_title():
    """부모가 목록에 없으면(권한 등) 자기 제목만 남는다."""
    crumbs = build_breadcrumbs([_page("3", "고아", "99")])
    assert crumbs["3"] == "고아"


def test_build_breadcrumbs_with_empty_pages():
    assert build_breadcrumbs([]) == {}


def test_build_breadcrumbs_does_not_recurse_on_cycle():
    """순환 부모(1→2→1, 자기참조)에서도 예외·무한 재귀 없이 반환한다.

    리드 결정(task-02 문서)에 따라 반환 문자열의 특정 값은 검증하지 않는다.
    """
    mutual = build_breadcrumbs([_page("1", "A", "2"), _page("2", "B", "1")])
    assert set(mutual) == {"1", "2"}
    assert all(isinstance(v, str) and v for v in mutual.values())

    self_ref = build_breadcrumbs([_page("1", "A", "1")])
    assert self_ref == {"1": "A"}


def test_build_documents_metadata_has_no_none_for_sparse_page():
    """version·_links·body 가 없는 페이지도 Chroma 제약(None 금지)을 만족한다."""
    docs = build_documents([{"id": 7, "title": "제목만"}], base_url="https://ihunet.atlassian.net/wiki")
    meta = docs[0].metadata
    assert meta == {
        "source": SOURCE_CONFLUENCE,
        "doc_id": "7",
        "title": "제목만",
        "url": "https://ihunet.atlassian.net/wiki",
        "breadcrumb": "제목만",
        "version": 0,
        "last_modified": "",
    }
    assert all(isinstance(value, (str, int, float, bool)) for value in meta.values())
    assert docs[0].page_content == ""


def test_build_documents_preserves_page_order_and_count():
    pages = [_page("1", "루트"), _page("2", "중간", "1"), _page("3", "리프", "2")]
    docs = build_documents(pages, base_url="https://x")
    assert [d.metadata["doc_id"] for d in docs] == ["1", "2", "3"]
    assert docs[2].metadata["breadcrumb"] == "루트 > 중간 > 리프"


def test_build_documents_with_empty_pages():
    assert build_documents([], base_url="https://x") == []


# --- 리뷰 1 조치 A 검증: body-only 매크로의 ac:parameter 텍스트 누출 ---

def test_body_only_macro_drops_title_parameter_but_keeps_body():
    md = convert_storage_to_markdown(
        '<ac:structured-macro ac:name="info">'
        '<ac:parameter ac:name="title">주의 제목</ac:parameter>'
        "<ac:rich-text-body><p>본문 내용</p></ac:rich-text-body></ac:structured-macro>"
    )
    assert md == "본문 내용"
    assert "주의 제목" not in md


def test_expand_macro_drops_title_parameter_but_keeps_body():
    md = convert_storage_to_markdown(
        '<ac:structured-macro ac:name="expand">'
        '<ac:parameter ac:name="title">더보기</ac:parameter>'
        "<ac:rich-text-body><p>숨긴 본문</p></ac:rich-text-body></ac:structured-macro>"
    )
    assert md == "숨긴 본문"
    assert "더보기" not in md


def test_body_only_macro_drops_all_direct_parameters():
    md = convert_storage_to_markdown(
        '<ac:structured-macro ac:name="panel">'
        '<ac:parameter ac:name="title">패널 제목</ac:parameter>'
        '<ac:parameter ac:name="bgColor">#FFFFFF</ac:parameter>'
        "<ac:rich-text-body><p>패널 본문</p></ac:rich-text-body></ac:structured-macro>"
    )
    assert md == "패널 본문"
    assert "패널 제목" not in md and "#FFFFFF" not in md


def test_nested_code_macro_keeps_language_inside_body_only_macro():
    """body-only 매크로의 직속 파라미터만 제거하고, 내부 code 매크로의 language 는 살아 있어야 한다."""
    md = convert_storage_to_markdown(
        '<ac:structured-macro ac:name="info">'
        '<ac:parameter ac:name="title">안내</ac:parameter>'
        "<ac:rich-text-body><p>설명</p>"
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body></ac:structured-macro>"
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert "안내" not in md
    assert "설명" in md
    assert "```python\nx = 1\n```" in md
