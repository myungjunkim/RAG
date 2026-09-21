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


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

def test_empty_collection(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_all() == []
    assert repo.count() == 0


def test_empty_string_metadata_is_stored_and_returned(tmp_path):
    """OpenAPI schema 문서는 method/path/tags 가 빈 문자열이다 (Chroma 허용 여부 확인)."""
    repo = _repo(tmp_path)
    repo.upsert([Document(page_content="schema 본문", metadata={
        "chunk_id": "svc:schema:S#0", "doc_id": "svc:schema:S", "source": "openapi",
        "method": "", "path": "", "tags": "", "section": "", "service": "svc",
    })])
    meta = repo.get_all()[0].metadata
    assert meta["method"] == "" and meta["path"] == "" and meta["tags"] == "" and meta["section"] == ""
    assert meta["service"] == "svc"
    assert repo.count() == 1


def test_none_metadata_values_are_dropped(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([Document(page_content="본문", metadata={
        "chunk_id": "1#0", "source": "confluence", "nullable": None, "keep": "x",
    })])
    meta = repo.get_all()[0].metadata
    assert "nullable" not in meta
    assert meta["keep"] == "x"


def test_upsert_splits_into_batches(tmp_path):
    repo = _repo(tmp_path, batch_size=2)
    repo.upsert([_chunk(f"x#{i}", f"본문 {i}") for i in range(5)])
    assert repo.count() == 5
    assert {d.metadata["chunk_id"] for d in repo.get_all()} == {f"x#{i}" for i in range(5)}


def test_upsert_with_batch_size_one(tmp_path):
    repo = _repo(tmp_path, batch_size=1)
    repo.upsert([_chunk("x#0", "a"), _chunk("x#1", "b")])
    assert repo.count() == 2


def test_upsert_empty_list_is_noop(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([])
    assert repo.count() == 0


def test_retriever_confluence_filter_and_unknown_source(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "인증 서버 설명"), _chunk("2#0", "GET /v1/messages", "openapi")])
    assert [d.metadata["chunk_id"] for d in repo.as_retriever(k=5, source="confluence").invoke("인증")] == ["1#0"]
    assert repo.as_retriever(k=5, source="does-not-exist").invoke("인증") == []


def test_reset_persists_across_instances(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "a")])
    repo.reset()
    assert _repo(tmp_path).count() == 0


def test_delete_missing_id_does_not_raise(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert([_chunk("1#0", "a")])
    repo.delete(["없는-id"])
    assert repo.count() == 1


def test_telemetry_is_disabled(tmp_path):
    """리드 결정 1: 익명 텔레메트리 외부 전송 비활성화."""
    repo = _repo(tmp_path)
    settings = repo._store._client.get_settings()
    assert settings.anonymized_telemetry is False
    assert settings.is_persistent is True
    assert settings.persist_directory == str(tmp_path / "chroma")


def test_from_profile_maps_config_values(tmp_path, monkeypatch):
    """실제 data/ 를 건드리지 않도록 [chroma] 경로를 tmp_path 로 치환해 확인한다."""
    from src.config.profile import Profile
    from src.repository.vector_store_repository import VectorStoreRepository

    original = Profile.get_config
    persist_dir = str(tmp_path / "from_profile")

    def fake_get_config(self, section):
        if section == "chroma":
            return {"persist-dir": persist_dir, "collection": "kudos_rag"}
        if section == "retrieval":
            return {"embed-batch-size": "7"}
        return original(self, section)

    monkeypatch.setattr(Profile, "get_config", fake_get_config)
    repo = VectorStoreRepository.from_profile(embeddings=DeterministicFakeEmbedding(size=16))
    repo.upsert([_chunk("1#0", "a")])
    assert repo.count() == 1
    assert repo._batch_size == 7
    assert repo._collection_name == "kudos_rag"
    assert repo._persist_dir == persist_dir
