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
