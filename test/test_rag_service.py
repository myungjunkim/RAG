import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from src.config.profile import Profile
from src.service import llm_factory
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


@pytest.mark.integration
def test_ask_against_real_llm_has_no_think_block():
    llm_model = Profile().get_config("ollama")["llm-model"]
    if not (llm_factory.ping_ollama() and llm_factory.has_model(llm_model)):
        pytest.skip(f"Ollama 미기동 또는 모델 미설치: {llm_model}")
    # qwen3:14b 설치 + Ollama 기동 필요. reasoning=False 가 실제로 적용되는지 확인한다.
    retriever = StubRetriever([_chunk("1#0", "[가이드 > 인증]\n토큰은 Authorization 헤더에 Bearer 로 넣는다.")])
    result = RagService.from_profile(retriever).ask("토큰은 어디에 넣나?")
    assert result["answer"].strip()
    assert "<think>" not in result["answer"]
    assert len(result["sources"]) == 1


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

class _Piece:
    def __init__(self, content):
        self.content = content


class StreamingModel:
    """astream 이 지정한 조각들을 흘리는 가짜 모델(빈 조각 포함 가능)."""

    def __init__(self, pieces):
        self._pieces = pieces
        self.astream_calls = 0

    async def astream(self, messages):
        self.astream_calls += 1
        self.messages = messages
        for piece in self._pieces:
            yield _Piece(piece)


class ExplodingStreamModel:
    def invoke(self, *_):
        raise AssertionError("검색 결과가 없으면 LLM 을 호출하지 않아야 한다")

    async def astream(self, *_):
        raise AssertionError("검색 결과가 없으면 astream 도 호출하지 않아야 한다")
        yield  # pragma: no cover - 제너레이터로 만들기 위한 구문


def test_strip_prefix_boundaries():
    from src.service.rag_service import _strip_prefix

    assert _strip_prefix("[루트 > 인증]\n본문") == "본문"
    assert _strip_prefix("[루트 > 인증\n본문") == "[루트 > 인증\n본문"   # 닫는 ] 없음 → 유지
    assert _strip_prefix("[루트 > 인증]") == "[루트 > 인증]"             # 개행 없음 → 유지
    assert _strip_prefix("## GET /a — 목록\n설명") == "## GET /a — 목록\n설명"  # openapi 헤더 유지
    assert _strip_prefix("") == ""
    assert _strip_prefix("본문\n[각주]") == "본문\n[각주]"


def test_sources_use_empty_string_for_missing_metadata():
    chunks = [Document(page_content="본문", metadata={"chunk_id": "1#0"})]
    _, sources = build_context(chunks)
    assert sources == [{"index": 1, "title": "", "url": "", "source": "", "snippet": "본문"}]
    assert all(isinstance(v, str) for k, v in sources[0].items() if k != "index")


def test_snippet_strips_prefix_then_truncates_and_trims():
    chunk = _chunk("1#0", "[루트 > 인증]\n   " + "가" * 300)
    _, sources = build_context([chunk])
    assert len(sources[0]["snippet"]) == 200
    assert sources[0]["snippet"].startswith("가")  # 접두어 제거 + strip


def test_context_blocks_are_separated_by_blank_line():
    context, _ = build_context([_chunk("1#0", "첫 본문"), _chunk("2#0", "둘째 본문", title="T2", url="U2")])
    assert context == "[1] 제목 | https://x/1\n첫 본문\n\n[2] T2 | U2\n둘째 본문"


def test_build_context_with_no_chunks():
    assert build_context([]) == ("", [])


def test_ask_passes_source_and_top_k_to_retriever():
    retriever = StubRetriever([_chunk("1#0", "본문")])
    service = RagService(retriever, FakeListChatModel(responses=["답"]))
    service.ask("질문", source="openapi", top_k=3)
    assert retriever.calls == [("질문", "openapi", 3)]


def test_ask_uses_default_source_and_top_k():
    retriever = StubRetriever([_chunk("1#0", "본문")])
    RagService(retriever, FakeListChatModel(responses=["답"])).ask("질문")
    assert retriever.calls == [("질문", "all", None)]


def test_prompt_contains_system_rules_and_context():
    from src.service.rag_service import SYSTEM_PROMPT

    class _Capturing:
        def invoke(self, messages):
            self.messages = messages
            return _Piece("답변")

    model = _Capturing()
    RagService(StubRetriever([_chunk("1#0", "토큰은 헤더로")]), model).ask("어디에 넣나?")
    system, human = model.messages
    assert system.content == SYSTEM_PROMPT
    assert "[1] 제목 | https://x/1" in human.content
    assert "질문: 어디에 넣나?" in human.content
    assert "관련 내용을 문서에서 찾지 못했습니다." in SYSTEM_PROMPT  # 규칙 3


@pytest.mark.asyncio
async def test_ask_stream_skips_empty_content_pieces():
    model = StreamingModel(["답", "", "변", ""])
    events = [e async for e in RagService(StubRetriever([_chunk("1#0", "본문")]), model).ask_stream("질문")]
    tokens = [e["data"] for e in events if e["event"] == "token"]
    assert tokens == ["답", "변"]  # 빈 조각은 방출하지 않는다
    assert [e["event"] for e in events] == ["token", "token", "sources", "done"]


@pytest.mark.asyncio
async def test_ask_stream_without_results_does_not_call_astream():
    service = RagService(StubRetriever([]), ExplodingStreamModel())
    events = [e async for e in service.ask_stream("질문")]
    assert events == [{"event": "token", "data": NOT_FOUND_ANSWER},
                      {"event": "sources", "data": []},
                      {"event": "done", "data": ""}]


@pytest.mark.asyncio
async def test_ask_stream_sources_match_ask_sources():
    chunks = [_chunk("1#0", "[루트]\n본문")]
    stream_events = [e async for e in RagService(StubRetriever(chunks), StreamingModel(["답"])).ask_stream("질문")]
    sync_result = RagService(StubRetriever(chunks), FakeListChatModel(responses=["답"])).ask("질문")
    sources_event = next(e for e in stream_events if e["event"] == "sources")
    assert sources_event["data"] == sync_result["sources"]


@pytest.mark.asyncio
async def test_ask_stream_passes_source_and_top_k():
    retriever = StubRetriever([_chunk("1#0", "본문")])
    service = RagService(retriever, StreamingModel(["답"]))
    [e async for e in service.ask_stream("질문", source="confluence", top_k=2)]
    assert retriever.calls == [("질문", "confluence", 2)]
