import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.repository.openapi_repository import OpenApiFetchError
from src.repository.vector_store_repository import VectorStoreRepository
from src.service.ingest_service import IngestService, confluence_fingerprint, openapi_fingerprint
from src.service.manifest import Manifest
from src.service.openapi_document_service import OpenApiSource


def _doc(doc_id, content, version=1):
    return Document(page_content=content, metadata={
        "source": "confluence", "doc_id": doc_id, "title": f"t{doc_id}", "breadcrumb": f"t{doc_id}",
        "url": "https://x", "version": version, "last_modified": "",
    })


def _service(tmp_path):
    store = VectorStoreRepository(str(tmp_path / "chroma"), "test_col", DeterministicFakeEmbedding(size=16))
    manifest = Manifest(str(tmp_path / "manifest.json"))
    return IngestService(store, manifest, chunk_size=1000, chunk_overlap=100), store, manifest


def _fps(docs):
    return {d.metadata["doc_id"]: confluence_fingerprint(d) for d in docs}


def test_first_ingest_adds_everything(tmp_path):
    svc, store, manifest = _service(tmp_path)
    docs = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n내용\n\n## B2\n\n내용2")]
    summary = svc.ingest_documents("confluence", docs, _fps(docs))
    assert (summary.added, summary.changed, summary.removed) == (2, 0, 0)
    assert store.count() == 3
    assert manifest.get("2")["chunk_ids"] == ["2#0", "2#1"]
    assert Manifest(str(tmp_path / "manifest.json")).get("1") is not None  # 저장됨


def test_incremental_update_changes_and_removes(tmp_path):
    svc, store, manifest = _service(tmp_path)
    first = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n내용\n\n## B2\n\n내용2")]
    svc.ingest_documents("confluence", first, _fps(first))
    second = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n바뀐 내용", version=2), _doc("3", "# C\n\n새 문서")]
    summary = svc.ingest_documents("confluence", second, _fps(second))
    assert (summary.added, summary.changed, summary.removed) == (1, 1, 0)
    assert manifest.get("2")["chunk_ids"] == ["2#0"]  # 청크 2개 → 1개로 갱신, 옛 2#1 삭제
    ids = {d.metadata["chunk_id"] for d in store.get_all()}
    assert ids == {"1#0", "2#0", "3#0"}
    third = [_doc("1", "# A\n\n내용")]
    summary = svc.ingest_documents("confluence", third, _fps(third))
    assert summary.removed == 2
    assert {d.metadata["chunk_id"] for d in store.get_all()} == {"1#0"}
    assert manifest.get("3") is None


def test_openapi_fingerprint_is_content_hash():
    a = Document(page_content="x", metadata={})
    b = Document(page_content="x", metadata={})
    c = Document(page_content="y", metadata={})
    assert openapi_fingerprint(a) == openapi_fingerprint(b) != openapi_fingerprint(c)


def test_reset_all_clears_store_and_manifest(tmp_path):
    svc, store, manifest = _service(tmp_path)
    docs = [_doc("1", "# A\n\n내용")]
    svc.ingest_documents("confluence", docs, _fps(docs))
    svc.reset_all()
    assert store.count() == 0 and manifest.entries == {}


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

class _ExplodingStore:
    """두 번째 upsert 에서 실패하는 가짜 store — manifest 저장 시점 확인용."""

    def __init__(self, fail_on_call=2):
        self.calls = 0
        self.deleted = []
        self._fail_on_call = fail_on_call

    def upsert(self, chunks):
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise RuntimeError("upsert 실패")

    def delete(self, chunk_ids):
        self.deleted.append(list(chunk_ids))

    def reset(self):
        pass


def test_manifest_keeps_documents_saved_before_failure(tmp_path):
    """문서 단위로 저장 성공 후 manifest 를 갱신하므로, 중간 실패 시 앞 문서는 남고 뒤 문서는 남지 않는다."""
    manifest_path = str(tmp_path / "manifest.json")
    manifest = Manifest(manifest_path)
    service = IngestService(_ExplodingStore(), manifest, chunk_size=1000, chunk_overlap=100)
    docs = [_doc("1", "# A\n\n내용"), _doc("2", "# B\n\n내용")]

    with pytest.raises(RuntimeError):
        service.ingest_documents("confluence", docs, _fps(docs))

    saved = Manifest(manifest_path)
    assert saved.get("1") is not None
    assert saved.get("2") is None


def test_changed_document_deletes_old_chunks_before_upsert(tmp_path):
    svc, store, manifest = _service(tmp_path)
    first = [_doc("1", "# A\n\n내용\n\n## A2\n\n내용2")]
    svc.ingest_documents("confluence", first, _fps(first))
    assert manifest.get("1")["chunk_ids"] == ["1#0", "1#1"]

    second = [_doc("1", "# A\n\n짧아진 내용", version=2)]
    svc.ingest_documents("confluence", second, _fps(second))

    assert manifest.get("1")["chunk_ids"] == ["1#0"]
    assert {d.metadata["chunk_id"] for d in store.get_all()} == {"1#0"}


def test_unchanged_document_is_not_reindexed(tmp_path):
    svc, store, manifest = _service(tmp_path)
    docs = [_doc("1", "# A\n\n내용")]
    svc.ingest_documents("confluence", docs, _fps(docs))
    summary = svc.ingest_documents("confluence", docs, _fps(docs))
    assert (summary.added, summary.changed, summary.removed, summary.chunk_count) == (0, 0, 0, 0)
    assert store.count() == 1


def test_ingest_documents_with_empty_input(tmp_path):
    svc, store, manifest = _service(tmp_path)
    summary = svc.ingest_documents("confluence", [], {})
    assert (summary.added, summary.changed, summary.removed, summary.chunk_count) == (0, 0, 0, 0)
    assert store.count() == 0


def test_other_source_documents_are_untouched(tmp_path):
    """confluence 인제스트가 openapi 문서를 지우지 않는다."""
    svc, store, manifest = _service(tmp_path)
    openapi_doc = Document(page_content="## GET /a — 목록", metadata={
        "source": "openapi", "doc_id": "svc:GET:/a", "title": "GET /a", "service": "svc",
        "method": "GET", "path": "/a", "tags": "", "url": "https://x/docs",
    })
    svc.ingest_documents("openapi", [openapi_doc], {"svc:GET:/a": openapi_fingerprint(openapi_doc)})
    docs = [_doc("1", "# A\n\n내용")]
    svc.ingest_documents("confluence", docs, _fps(docs))

    svc.ingest_documents("confluence", [], {})  # confluence 전부 삭제
    assert {d.metadata["doc_id"] for d in store.get_all()} == {"svc:GET:/a"}
    assert manifest.get("svc:GET:/a") is not None


def test_reset_all_writes_empty_manifest_file(tmp_path):
    svc, store, manifest = _service(tmp_path)
    docs = [_doc("1", "# A\n\n내용")]
    svc.ingest_documents("confluence", docs, _fps(docs))
    svc.reset_all()
    assert store.count() == 0
    assert Manifest(str(tmp_path / "manifest.json")).entries == {}


def test_confluence_fingerprint_uses_version():
    assert confluence_fingerprint(_doc("1", "x", version=3)) == "3"
    assert confluence_fingerprint(Document(page_content="x", metadata={})) == ""


# --- ingest_openapi: 수집 실패 소스의 기존 문서 보존 ---

class _FakeOpenApiRepo:
    """지정한 spec_url 은 스펙을 주고, 나머지는 OpenApiFetchError 를 낸다."""

    def __init__(self, specs):
        self._specs = specs

    def fetch_spec(self, url):
        if url in self._specs:
            return self._specs[url]
        raise OpenApiFetchError(f"다운로드 실패: {url}")


def _spec_for(path):
    return {"openapi": "3.1.0", "info": {"title": "T"},
            "paths": {path: {"get": {"summary": "s", "responses": {"200": {"description": "OK"}}}}}}


def test_ingest_openapi_preserves_documents_of_failed_source(tmp_path):
    svc, store, manifest = _service(tmp_path)
    a = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    b = OpenApiSource("svcB", "https://b/openapi.json", "https://b/docs")
    both = _FakeOpenApiRepo({a.spec_url: _spec_for("/a"), b.spec_url: _spec_for("/b")})

    first = svc.ingest_openapi(both, [a, b])
    assert first.added == 2 and first.failed_sources == []
    assert {d.metadata["doc_id"] for d in store.get_all()} == {"svcA:GET:/a", "svcB:GET:/b"}

    # svcB 다운로드 실패 → svcB 기존 문서는 남아 있어야 한다
    only_a = _FakeOpenApiRepo({a.spec_url: _spec_for("/a")})
    second = svc.ingest_openapi(only_a, [a, b])

    assert second.failed_sources == ["svcB"]
    assert second.removed == 0
    assert {d.metadata["doc_id"] for d in store.get_all()} == {"svcA:GET:/a", "svcB:GET:/b"}
    assert manifest.get("svcB:GET:/b") is not None


def test_ingest_openapi_removes_document_dropped_by_successful_source(tmp_path):
    svc, store, manifest = _service(tmp_path)
    a = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    svc.ingest_openapi(_FakeOpenApiRepo({a.spec_url: _spec_for("/a")}), [a])

    # 같은 서비스에서 엔드포인트가 /a → /c 로 바뀌면 옛 문서는 삭제된다
    summary = svc.ingest_openapi(_FakeOpenApiRepo({a.spec_url: _spec_for("/c")}), [a])

    assert summary.removed == 1
    assert {d.metadata["doc_id"] for d in store.get_all()} == {"svcA:GET:/c"}


def test_ingest_openapi_all_sources_failed(tmp_path):
    svc, store, manifest = _service(tmp_path)
    a = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    svc.ingest_openapi(_FakeOpenApiRepo({a.spec_url: _spec_for("/a")}), [a])

    summary = svc.ingest_openapi(_FakeOpenApiRepo({}), [a])

    assert summary.failed_sources == ["svcA"]
    assert summary.removed == 0
    assert store.count() == 1  # 전부 실패 시 기존 인덱스 보존
