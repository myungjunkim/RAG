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


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

def test_tokenize_lowercases():
    assert tokenize("UPPER Case MiXeD") == ["upper", "case", "mixed"]


def test_tokenize_two_letter_korean_has_no_bigram():
    assert tokenize("조회") == ["조회"]
    assert tokenize("가") == ["가"]


def test_tokenize_korean_bigram_count_is_length_minus_one():
    for word in ["가나다", "가나다라", "인증서버연동"]:
        tokens = tokenize(word)
        assert tokens[0] == word
        assert len(tokens) - 1 == len(word) - 1
        assert tokens[1:] == [word[i:i + 2] for i in range(len(word) - 1)]


def test_tokenize_path_segments_and_trailing_slash():
    assert tokenize("/v1/messages/") == ["/v1/messages/", "v1", "messages"]
    assert "{service_key}" in tokenize("/v1/messages/{service_key}")


def test_tokenize_empty_and_symbols_only():
    assert tokenize("") == []
    assert tokenize("   ") == []
    assert tokenize("!!! @#$ %^&") == []


def test_tokenize_splits_mixed_alphabet_and_korean():
    assert tokenize("API키") == ["api", "키"]


def test_tokenize_keeps_identifier_underscores():
    assert tokenize("company_seq affiliated_company_seq") == ["company_seq", "affiliated_company_seq"]


def test_import_paths_follow_global_constraint():
    """Global Constraint: EnsembleRetriever 는 langchain_classic, BM25Retriever 는 langchain_community."""
    import src.service.retriever_service as module

    assert module.EnsembleRetriever.__module__.startswith("langchain_classic")
    assert module.BM25Retriever.__module__.startswith("langchain_community")


def test_unknown_source_returns_empty(tmp_path):
    svc, _ = _service(tmp_path)
    assert svc.search("인증", source="foo") == []


def test_search_before_reload_returns_empty(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    store.upsert([_chunk("c1#0", "인증 서버")])
    svc = RetrieverService(store, 4, 4, 0.5, 0.5, 3)
    assert svc.search("인증") == []  # reload 전에는 BM25 인덱스가 없다


def test_source_missing_from_collection_returns_empty(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    store.upsert([_chunk("c1#0", "confluence 전용 문서")])
    svc = RetrieverService(store, 4, 4, 0.5, 0.5, 3)
    svc.reload()
    assert svc.search("문서", source="openapi") == []
    assert [r.metadata["chunk_id"] for r in svc.search("문서", source="confluence")] == ["c1#0"]


def test_reload_reflects_deleted_chunks(tmp_path):
    svc, store = _service(tmp_path)
    store.delete(["c1#0"])
    assert svc.reload() == 3
    assert svc.chunk_count == 3
    assert "c1#0" not in [r.metadata["chunk_id"] for r in svc.search("인증 토큰 발급", top_k=10)]


def test_results_are_unique_and_within_k(tmp_path):
    svc, _ = _service(tmp_path)
    for top_k in (1, 2, 3, 10):
        results = svc.search("메시지 인증 배포", top_k=top_k)
        ids = [r.metadata["chunk_id"] for r in results]
        assert len(ids) == len(set(ids))
        assert len(ids) <= top_k


def test_default_top_k_comes_from_constructor(tmp_path):
    svc, _ = _service(tmp_path)  # top_k=3, 컬렉션 4청크
    assert len(svc.search("인증 배포 메시지 주제")) <= 3


def test_from_profile_maps_retrieval_config(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    svc = RetrieverService.from_profile(store)
    assert svc._bm25_k == 10
    assert svc._vector_k == 10
    assert svc._weights == [0.4, 0.6]
    assert svc._top_k == 6


def test_reload_returns_zero_for_empty_collection_and_is_idempotent(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "empty"), "test_col", DeterministicFakeEmbedding(size=16))
    svc = RetrieverService(store, 4, 4, 0.5, 0.5, 3)
    assert svc.reload() == 0
    assert svc.reload() == 0
    assert svc.search("아무거나", source="confluence") == []
