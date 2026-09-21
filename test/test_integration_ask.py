"""Ollama(bge-m3, qwen3:14b)가 떠 있을 때만 실행: pytest --active-profile=local -m integration test/test_integration_ask.py"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config.profile import Profile
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
def client(tmp_path, monkeypatch):
    ollama = Profile().get_config("ollama")
    required = [ollama["embedding-model"], ollama["llm-model"]]
    if not llm_factory.ping_ollama():
        pytest.skip("Ollama 미기동")
    missing = [m for m in required if not llm_factory.has_model(m)]
    if missing:
        pytest.skip(f"Ollama 모델 미설치: {', '.join(missing)}")
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_it", llm_factory.create_embeddings())
    spec = json.loads((Path(__file__).parent / "fixtures" / "openapi_sample.json").read_text(encoding="utf-8"))
    docs = build_documents(spec, OpenApiSource("message-api", "https://x/openapi.json", "https://x/docs"))
    IngestService(store, Manifest(str(tmp_path / "m.json")), 1000, 150).ingest_documents(
        "openapi", docs, {d.metadata["doc_id"]: openapi_fingerprint(d) for d in docs})
    retriever = RetrieverService.from_profile(store)
    retriever.reload()
    monkeypatch.setattr(ask_controller, "context",
                        ask_controller.RagContext(retriever, RagService.from_profile(retriever)))
    import main
    with TestClient(main.app) as c:
        yield c


def test_end_to_end_ask(client):
    res = client.post("/v1/ask", json={"question": "메시지 등록 API 는 어떤 메서드와 경로로 호출해?", "source": "openapi"})
    assert res.status_code == 200
    body = res.json()
    assert "/v1/messages/message" in body["answer"]
    assert any(s["title"] == "POST /v1/messages/message" for s in body["sources"])
