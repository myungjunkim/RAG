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
    # monkeypatch 로 넣어 두면 테스트가 context 를 직접 바꾸더라도 teardown 에서 원래 값으로 복원된다
    monkeypatch.setattr(ask_controller, "context",
                        ask_controller.RagContext(retriever, RagService(retriever, FakeListChatModel(responses=["헤더로 전달 [1]"]))))
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


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

class ResponseErrorModel:
    """모델 미설치 상황(ollama.ResponseError 404)."""

    def invoke(self, *_):
        from ollama import ResponseError

        raise ResponseError('model "qwen3:14b" not found', 404)


class BuggyModel:
    def invoke(self, *_):
        raise ValueError("코드 버그")


class StreamErrorModel:
    def invoke(self, *_):
        raise httpx.ConnectError("connection refused")

    async def astream(self, *_):
        raise httpx.ConnectError("connection refused")
        yield  # pragma: no cover


def _swap_model(monkeypatch, retriever, model):
    """context 를 monkeypatch 로 교체해 테스트 종료 시 자동 복원되게 한다."""
    monkeypatch.setattr(ask_controller, "context",
                        ask_controller.RagContext(retriever, RagService(retriever, model)))


def test_validation_boundaries(client):
    c, _ = client
    assert c.post("/v1/ask", json={"question": "가" * 2000}).status_code == 200
    assert c.post("/v1/ask", json={"question": "가" * 2001}).status_code == 422
    assert c.post("/v1/ask", json={"question": "q", "top_k": 20}).status_code == 200
    assert c.post("/v1/ask", json={"question": "q", "top_k": 21}).status_code == 422
    assert c.post("/v1/ask", json={}).status_code == 422


def test_unknown_field_is_ignored(client):
    """pydantic 기본 동작(extra 무시). extra='forbid' 를 요구하지 않는 현재 인터페이스 기준."""
    c, _ = client
    assert c.post("/v1/ask", json={"question": "q", "unknown_field": 1}).status_code == 200


def test_model_not_found_returns_503_with_cause(client, monkeypatch):
    """리드 결정 1: ollama.ResponseError 도 LLM_ERRORS 로 잡혀 503 + 원인 포함."""
    c, retriever = client
    _swap_model(monkeypatch, retriever, ResponseErrorModel())
    res = c.post("/v1/ask", json={"question": "q"})
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "Ollama" in detail
    assert "not found" in detail  # 모델 미설치 원인이 드러난다


def test_unexpected_error_is_not_masked_as_503(client, monkeypatch):
    """코드 버그가 503 으로 가려지면 안 된다(기각 대안: except Exception 전부 503)."""
    import main

    c, retriever = client
    _swap_model(monkeypatch, retriever, BuggyModel())
    with TestClient(main.app, raise_server_exceptions=False) as strict:
        assert strict.post("/v1/ask", json={"question": "q"}).status_code == 500


def test_stream_error_event_on_llm_failure(client, monkeypatch):
    c, retriever = client
    _swap_model(monkeypatch, retriever, StreamErrorModel())
    with c.stream("POST", "/v1/ask/stream", json={"question": "q"}) as res:
        assert res.status_code == 200  # 첫 바이트 전송 후에는 상태 코드를 바꿀 수 없다
        raw = "".join(res.iter_text())
    assert raw.startswith("event: error\n")
    assert "Ollama" in raw
    assert raw.endswith("\n\n")


def test_stream_headers(client):
    c, _ = client
    with c.stream("POST", "/v1/ask/stream", json={"question": "q"}) as res:
        assert res.headers["cache-control"] == "no-cache"
        assert res.headers["x-accel-buffering"] == "no"
        res.read()


def test_sse_token_data_is_json_encoded_string(client):
    c, _ = client
    with c.stream("POST", "/v1/ask/stream", json={"question": "q"}) as res:
        raw = "".join(res.iter_text())
    first = raw.split("\n\n")[0]
    assert first.startswith("event: token\ndata: \"")  # JSON 문자열로 인코딩


def test_check_degraded_when_collection_empty(client, monkeypatch):
    c, retriever = client
    monkeypatch.setattr(retriever, "chunk_count", 0)
    body = c.get("/check").json()
    assert body == {"status": "degraded", "ollama": True, "chunk_count": 0}


def test_openapi_lists_four_paths_and_hides_root(client):
    c, _ = client
    assert c.get("/docs").status_code == 200
    spec = c.get("/openapi.json").json()
    assert sorted(spec["paths"]) == ["/check", "/v1/ask", "/v1/ask/stream", "/v1/reload"]
    assert "/" not in spec["paths"]  # include_in_schema=False


def test_lifespan_initializes_context_and_calls_reload(monkeypatch, tmp_path):
    """Task 9 비차단 3: 기동 시 reload() 가 호출되지 않으면 search 가 조용히 [] 를 반환한다."""
    import main
    from langchain_core.embeddings import DeterministicFakeEmbedding
    from src.repository.vector_store_repository import VectorStoreRepository
    from src.service.retriever_service import RetrieverService

    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    store.upsert([_chunk("1#0", "인증 서버 설명"), _chunk("2#0", "메시지 API", "openapi")])

    monkeypatch.setattr(ask_controller.VectorStoreRepository, "from_profile",
                        classmethod(lambda cls, *a, **k: store))
    monkeypatch.setattr(ask_controller.RagService, "from_profile",
                        classmethod(lambda cls, retriever: RagService(retriever, FakeListChatModel(responses=["답"]))))
    monkeypatch.setattr(ask_controller.llm_factory, "ping_ollama", lambda: True)  # 이 테스트는 네트워크를 쓰지 않는다
    monkeypatch.setattr(ask_controller, "context", None)

    with TestClient(main.app) as c:
        assert ask_controller.context is not None
        assert isinstance(ask_controller.context.retriever, RetrieverService)
        # reload() 가 호출됐으므로 chunk_count 가 컬렉션과 일치하고 검색이 실제로 동작한다
        assert ask_controller.context.retriever.chunk_count == 2
        assert c.get("/check").json()["chunk_count"] == 2
        assert ask_controller.context.retriever.search("인증", source="confluence")


def test_get_context_reuses_existing_context(client):
    _, retriever = client
    assert ask_controller.get_context() is ask_controller.context
    assert ask_controller.get_context().retriever is retriever


# --- 리뷰 3 조치 B-2: 누락 테스트 3개 ---

class FailingRetriever:
    """search 단계에서 Ollama 임베딩 오류가 나는 리트리버."""

    def __init__(self, error):
        self._error = error
        self.chunk_count = 1

    def search(self, query, source="all", top_k=None):
        raise self._error

    def reload(self):
        return 0


class PartialStreamModel:
    """토큰 일부를 흘린 뒤 실패하는 모델."""

    def invoke(self, *_):
        raise AssertionError("이 테스트는 스트림 경로만 사용한다")

    async def astream(self, *_):
        class _Piece:
            def __init__(self, content):
                self.content = content

        yield _Piece("앞부분")
        yield _Piece(" 이어서")
        raise httpx.ReadError("stream broken")


class BuiltinConnectionErrorModel:
    def invoke(self, *_):
        raise ConnectionError("connection refused")


def _context_with(monkeypatch, retriever, model):
    monkeypatch.setattr(ask_controller, "context",
                        ask_controller.RagContext(retriever, RagService(retriever, model)))


@pytest.mark.parametrize("error", [ConnectionError("refused"), httpx.ConnectError("refused")])
def test_search_failure_returns_503(client, monkeypatch, error):
    """임베딩 호출(검색 단계)에서 나는 Ollama 오류도 503 으로 매핑된다."""
    c, _ = client
    retriever = FailingRetriever(error)
    _context_with(monkeypatch, retriever, FakeListChatModel(responses=["쓰이지 않음"]))
    res = c.post("/v1/ask", json={"question": "q"})
    assert res.status_code == 503
    assert "Ollama" in res.json()["detail"]


def test_search_failure_in_stream_emits_error_event(client, monkeypatch):
    c, _ = client
    from ollama import ResponseError

    retriever = FailingRetriever(ResponseError('model "bge-m3" not found', 404))
    _context_with(monkeypatch, retriever, FakeListChatModel(responses=["쓰이지 않음"]))
    with c.stream("POST", "/v1/ask/stream", json={"question": "q"}) as res:
        assert res.status_code == 200
        raw = "".join(res.iter_text())
    assert raw.startswith("event: error\n")
    assert "not found" in raw


def test_stream_error_after_partial_tokens(client, monkeypatch):
    """토큰을 일부 보낸 뒤 실패하면 마지막 프레임이 error 여야 한다(done 없음)."""
    c, retriever = client
    _context_with(monkeypatch, retriever, PartialStreamModel())
    with c.stream("POST", "/v1/ask/stream", json={"question": "q"}) as res:
        raw = "".join(res.iter_text())
    frames = [f for f in raw.strip().split("\n\n") if f]
    names = [f.split("\n", 1)[0].removeprefix("event: ") for f in frames]
    assert names[:2] == ["token", "token"]
    assert names[-1] == "error"
    assert "done" not in names
    assert "앞부분" in raw and "이어서" in raw


def test_builtin_connection_error_returns_503(client, monkeypatch):
    """ollama 클라이언트가 감싸는 builtin ConnectionError 도 LLM_ERRORS 에 포함된다."""
    c, retriever = client
    _context_with(monkeypatch, retriever, BuiltinConnectionErrorModel())
    res = c.post("/v1/ask", json={"question": "q"})
    assert res.status_code == 503
    assert "Ollama" in res.json()["detail"]
