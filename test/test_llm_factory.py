import pytest
import requests

from src.config.profile import Profile
from src.service import llm_factory

_EMBEDDING_MODEL = Profile().get_config("ollama")["embedding-model"]


def _require(model: str | None = None):
    """Ollama 기동(+필요 시 모델 설치) 조건을 만족하지 않으면 건너뛴다."""
    if not llm_factory.ping_ollama():
        pytest.skip("Ollama 미기동")
    if model and not llm_factory.has_model(model):
        pytest.skip(f"Ollama 모델 미설치: {model} (`ollama pull {model}`)")


def test_create_embeddings_uses_ini_values():
    embeddings = llm_factory.create_embeddings()
    assert embeddings.model == "bge-m3"
    assert embeddings.base_url == "http://127.0.0.1:11434"


def test_create_chat_model_uses_ini_values():
    chat = llm_factory.create_chat_model()
    assert chat.model == "qwen3:14b"
    assert chat.base_url == "http://127.0.0.1:11434"
    assert chat.temperature == 0
    assert chat.num_ctx == 16384
    assert chat.reasoning is False
    assert chat.client_kwargs == {"timeout": 120.0}


def test_ping_ollama_true_on_200(monkeypatch):
    class _Response:
        status_code = 200

    captured = {}

    def _fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(requests, "get", _fake_get)
    assert llm_factory.ping_ollama() is True
    assert captured["url"] == "http://127.0.0.1:11434/api/tags"
    assert captured["timeout"] == 3


def test_ping_ollama_false_on_non_200(monkeypatch):
    class _Response:
        status_code = 500

    monkeypatch.setattr(requests, "get", lambda url, timeout=None: _Response())
    assert llm_factory.ping_ollama() is False


def test_ping_ollama_false_on_exception(monkeypatch):
    def _raise(url, timeout=None):
        raise requests.ConnectionError("연결할 수 없습니다")

    monkeypatch.setattr(requests, "get", _raise)
    assert llm_factory.ping_ollama() is False


# --- has_model 단위 검증 (리뷰 4 조치 B-3) ---

class _TagsResponse:
    def __init__(self, status_code, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("JSON 이 아님")
        return self._payload


def _fake_tags(monkeypatch, response):
    captured = {}

    def _get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(requests, "get", _get)
    return captured


def test_has_model_true_when_listed(monkeypatch):
    captured = _fake_tags(monkeypatch, _TagsResponse(200, {"models": [{"name": "bge-m3:latest"}, {"name": "qwen3:14b"}]}))
    assert llm_factory.has_model("qwen3:14b") is True
    assert captured["url"] == "http://127.0.0.1:11434/api/tags"
    assert captured["timeout"] == 3


def test_has_model_matches_bare_name_against_latest_tag(monkeypatch):
    """`bge-m3` 로 물어도 설치 목록의 `bge-m3:latest` 와 매칭된다."""
    _fake_tags(monkeypatch, _TagsResponse(200, {"models": [{"name": "bge-m3:latest"}]}))
    assert llm_factory.has_model("bge-m3") is True


def test_has_model_false_when_not_listed(monkeypatch):
    _fake_tags(monkeypatch, _TagsResponse(200, {"models": [{"name": "other:latest"}]}))
    assert llm_factory.has_model("bge-m3") is False


def test_has_model_false_on_empty_model_list(monkeypatch):
    """현재 검증 환경(모델 0개)과 같은 상태."""
    _fake_tags(monkeypatch, _TagsResponse(200, {"models": []}))
    assert llm_factory.has_model("bge-m3") is False


def test_has_model_false_on_non_200(monkeypatch):
    _fake_tags(monkeypatch, _TagsResponse(500))
    assert llm_factory.has_model("bge-m3") is False


def test_has_model_false_on_request_exception(monkeypatch):
    _fake_tags(monkeypatch, requests.ConnectionError("연결할 수 없습니다"))
    assert llm_factory.has_model("bge-m3") is False


def test_has_model_false_on_invalid_json(monkeypatch):
    _fake_tags(monkeypatch, _TagsResponse(200, raises=True))
    assert llm_factory.has_model("bge-m3") is False


@pytest.mark.integration
def test_ping_ollama_against_real_server():
    _require()
    assert llm_factory.ping_ollama() is True


@pytest.mark.integration
def test_embed_query_returns_1024_dimension_vector():
    _require(_EMBEDDING_MODEL)
    vector = llm_factory.create_embeddings().embed_query("테스트")
    assert len(vector) == 1024


@pytest.mark.integration
def test_embed_query_handles_3000_character_text():
    _require(_EMBEDDING_MODEL)
    # Task 6 openapi 청크 최대 길이(3 x chunk_size) 대응
    vector = llm_factory.create_embeddings().embed_query("가나다라마" * 600)
    assert len(vector) == 1024
