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


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

def test_three_level_heading_path_in_section():
    md = "# 인증\n\n개요\n\n## 요청\n\n설명\n\n### 헤더\n\n헤더 설명"
    chunks = split_documents([_confluence_doc(md)], 1000, 100)
    assert [c.metadata["section"] for c in chunks] == ["인증", "인증 > 요청", "인증 > 요청 > 헤더"]
    assert chunks[2].page_content.startswith("[루트 > 리프 > 인증 > 요청 > 헤더]")


def test_headings_are_kept_in_chunk_body():
    """strip_headers=False 이므로 헤딩 줄이 본문에 남아야 한다."""
    chunks = split_documents([_confluence_doc("# 인증\n\n개요")], 1000, 100)
    assert "# 인증" in chunks[0].page_content


def test_fenced_code_block_hash_does_not_split_section():
    """Task 2 가 만든 펜스 코드블록 안의 '#' 은 헤딩으로 취급되지 않는다."""
    md = "# 인증 서버\n\n설명\n\n## 요청 예시\n\n```python\n# 주석 헤딩처럼 보임\nx = 1\n## 이중 주석\n```\n\n뒤 문장"
    chunks = split_documents([_confluence_doc(md)], 1000, 100)
    assert [c.metadata["section"] for c in chunks] == ["인증 서버", "인증 서버 > 요청 예시"]
    code_chunk = chunks[1].page_content
    assert "```python\n# 주석 헤딩처럼 보임\nx = 1\n## 이중 주석\n```" in code_chunk
    assert "뒤 문장" in code_chunk


def test_chunk_index_restarts_per_document():
    chunks = split_documents(
        [_confluence_doc("# A\n\n본문", doc_id="1"), _confluence_doc("# B\n\n본문", doc_id="2")], 1000, 100)
    assert [(c.metadata["doc_id"], c.metadata["chunk_index"]) for c in chunks] == [("1", 0), ("2", 0)]
    assert [c.metadata["chunk_id"] for c in chunks] == ["1#0", "2#0"]


def test_original_metadata_is_preserved_in_every_chunk():
    md = "# 제목\n\n" + ("가나다라마바사 " * 400)
    chunks = split_documents([_confluence_doc(md)], 1000, 100)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk.metadata["source"] == "confluence"
        assert chunk.metadata["doc_id"] == "10"
        assert chunk.metadata["title"] == "리프"
        assert chunk.metadata["breadcrumb"] == "루트 > 리프"
        assert chunk.metadata["url"] == "https://x/10"
        assert chunk.metadata["version"] == 1
        assert chunk.metadata["chunk_id"] == f"10#{chunk.metadata['chunk_index']}"
        assert all(isinstance(v, (str, int)) for v in chunk.metadata.values())


def test_openapi_metadata_is_preserved():
    chunks = split_documents([_openapi_doc("## GET /a — 목록\n서비스: svc")], 1000, 100)
    meta = chunks[0].metadata
    assert meta["service"] == "svc" and meta["method"] == "GET" and meta["path"] == "/a"
    assert meta["tags"] == "" and meta["url"] == "https://x/docs"
    assert meta["section"] == "" and meta["chunk_index"] == 0
    assert all(isinstance(v, (str, int)) for v in meta.values())


def test_breadcrumb_falls_back_to_title():
    doc = _confluence_doc("본문")
    del doc.metadata["breadcrumb"]
    assert split_documents([doc], 1000, 100)[0].page_content == "[리프]\n본문"


def test_empty_breadcrumb_value_falls_back_to_title():
    doc = _confluence_doc("본문")
    doc.metadata["breadcrumb"] = ""
    assert split_documents([doc], 1000, 100)[0].page_content == "[리프]\n본문"


def test_whitespace_only_documents_yield_no_chunk():
    assert split_documents([_confluence_doc("   \n\n")], 1000, 100) == []
    assert split_documents([_confluence_doc("\t \n")], 1000, 100) == []
    assert split_documents([_openapi_doc("  \n ")], 1000, 100) == []
    assert split_documents([], 1000, 100) == []


def test_long_section_respects_length_limit():
    md = "# 제목\n\n" + ("가나다라마바사 " * 400)
    chunks = split_documents([_confluence_doc(md)], 1000, 100)
    prefix = "[루트 > 리프 > 제목]\n"
    assert all(len(c.page_content) <= 1000 + len(prefix) for c in chunks)
    assert all(c.page_content.startswith(prefix) for c in chunks)


def test_text_without_separators_is_still_split_within_limit():
    """공백 없는 긴 문자열도 분할되고 상한을 넘지 않는다."""
    chunks = split_documents([_confluence_doc("# 제목\n\n" + "가" * 3000)], 1000, 100)
    prefix = "[루트 > 리프 > 제목]\n"
    assert len(chunks) >= 3
    assert all(len(c.page_content) <= 1000 + len(prefix) for c in chunks)


def test_very_long_prefix_does_not_raise_and_keeps_half_size_floor():
    """접두어가 chunk_size 의 절반을 넘어도 본문 하한(chunk_size//2)으로 동작한다."""
    doc = _confluence_doc("# 제목\n\n" + ("가나다 " * 200))
    doc.metadata["breadcrumb"] = "루" * 300
    chunks = split_documents([doc], 100, 10)
    assert chunks
    bodies = [c.page_content.split("\n", 1)[1] for c in chunks]
    assert all(len(b) <= 100 // 2 for b in bodies)


def test_openapi_short_document_keeps_original_text():
    text = "## GET /a — 목록\n서비스: svc\n\n### Responses\n- 200: OK"
    chunks = split_documents([_openapi_doc(text)], 1000, 100)
    assert len(chunks) == 1
    assert chunks[0].page_content == text
    assert chunks[0].metadata["section"] == ""


def test_openapi_document_at_exactly_three_times_chunk_size_is_single_chunk():
    header = "## GET /a — 목록"
    text = header + "\n" + "x" * (300 - len(header) - 1)  # 정확히 3 * chunk_size(100)
    chunks = split_documents([_openapi_doc(text)], 100, 10)
    assert len(chunks) == 1
    assert chunks[0].page_content == text


def test_openapi_long_document_reattaches_header_to_every_piece():
    header = "## GET /a — 목록"
    text = header + "\n" + ("- field (string)\n" * 300)
    chunks = split_documents([_openapi_doc(text)], 1000, 100)
    assert len(chunks) >= 2
    assert all(c.page_content.startswith(header + "\n") for c in chunks)
    assert all(c.metadata["section"] == "" for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert [c.metadata["chunk_id"] for c in chunks] == [f"svc:GET:/a#{i}" for i in range(len(chunks))]


def test_document_without_source_metadata_is_treated_as_confluence():
    doc = Document(page_content="# 제목\n\n본문", metadata={"doc_id": "7", "title": "제목만"})
    chunks = split_documents([doc], 1000, 100)
    assert chunks[0].page_content.startswith("[제목만 > 제목]")
    assert chunks[0].metadata["chunk_id"] == "7#0"
