"""ingest.py CLI 동작 고정 (리뷰 2 조치 B).

실제 Ollama·Chroma·Confluence 없이 main() 을 호출하기 위해 진입점이 참조하는 이름을 monkeypatch 한다.
"""
import json
import os

import pytest
from langchain_core.documents import Document

import ingest
from src.config.profile import Profile
from src.repository.confluence_repository import ConfluenceAuthError
from src.repository.openapi_repository import OpenApiFetchError
from src.service.openapi_document_service import OpenApiSource


class FakeEmbeddings:
    """embed_query 가 성공하거나(기본) 지정한 예외를 낸다."""

    def __init__(self, error=None):
        self._error = error
        self.calls = []

    def embed_query(self, text):
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return [0.0] * 16


class FakeStore:
    def __init__(self):
        self.upserted = []
        self.deleted = []
        self.reset_calls = 0

    def upsert(self, chunks):
        self.upserted.extend(chunks)

    def delete(self, chunk_ids):
        self.deleted.append(list(chunk_ids))

    def reset(self):
        self.reset_calls += 1
        self.upserted.clear()

    def count(self):
        return len(self.upserted)


def _spec(path="/a"):
    return {"openapi": "3.1.0", "info": {"title": "T"},
            "paths": {path: {"get": {"summary": "s", "responses": {"200": {"description": "OK"}}}}}}


class FakeOpenApiRepository:
    """클래스 자체를 ingest.OpenApiRepository 자리에 끼워 넣는다."""

    specs: dict = {}
    sources: list = []

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def sources_from_profile(cls):
        return list(cls.sources)

    def fetch_spec(self, url):
        if url in self.specs:
            return self.specs[url]
        raise OpenApiFetchError(f"다운로드 실패: {url}")


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """main() 이 실제 외부 자원에 닿지 않도록 고정하고, 조작 대상을 돌려준다."""
    manifest_path = str(tmp_path / "manifest.json")
    original_get_config = Profile.get_config

    def fake_get_config(self, section):
        if section == "chroma":
            return {"persist-dir": str(tmp_path / "chroma"), "collection": "test_col",
                    "manifest-path": manifest_path}
        if section == "retrieval":
            return {"chunk-size": "1000", "chunk-overlap": "100", "embed-batch-size": "32"}
        return original_get_config(self, section)

    monkeypatch.setattr(Profile, "get_config", fake_get_config)

    store = FakeStore()
    embeddings = FakeEmbeddings()
    monkeypatch.setattr(ingest.VectorStoreRepository, "from_profile",
                        classmethod(lambda cls, *a, **k: store))
    monkeypatch.setattr(ingest.llm_factory, "create_embeddings", lambda: embeddings)

    FakeOpenApiRepository.specs = {}
    FakeOpenApiRepository.sources = []
    monkeypatch.setattr(ingest, "OpenApiRepository", FakeOpenApiRepository)

    class _Namespace:
        pass

    ns = _Namespace()
    ns.store = store
    ns.embeddings = embeddings
    ns.manifest_path = manifest_path
    ns.openapi = FakeOpenApiRepository
    ns.monkeypatch = monkeypatch
    return ns


def _run(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["ingest.py", "--active-profile=local", *args])
    return ingest.main()


def test_help_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ingest.py", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        ingest.main()
    assert excinfo.value.code == 0
    assert "--source" in capsys.readouterr().out


def test_embedding_failure_exits_one_without_touching_store(cli, capsys):
    """리뷰 2 A-1: 임베딩 사전 점검 실패 시 reset_all 전에 종료한다."""
    cli.monkeypatch.setattr(ingest.llm_factory, "create_embeddings",
                            lambda: FakeEmbeddings(error=RuntimeError('model "bge-m3" not found')))

    code = _run(cli.monkeypatch, "--source", "openapi", "--full")

    assert code == 1
    err = capsys.readouterr().err
    assert "임베딩 모델을 사용할 수 없습니다" in err
    assert "bge-m3" in err
    assert cli.store.reset_calls == 0  # --full 이어도 컬렉션을 비우지 않는다
    assert not os.path.exists(cli.manifest_path)


def test_embedding_failure_keeps_existing_manifest(cli, capsys):
    existing = {"1": {"fingerprint": "v1", "chunk_ids": ["1#0"], "source": "confluence"}}
    with open(cli.manifest_path, "w", encoding="utf-8") as f:
        json.dump(existing, f)
    cli.monkeypatch.setattr(ingest.llm_factory, "create_embeddings",
                            lambda: FakeEmbeddings(error=ConnectionError("연결 거부")))

    code = _run(cli.monkeypatch, "--source", "openapi", "--full")

    assert code == 1
    assert json.load(open(cli.manifest_path, encoding="utf-8")) == existing
    assert cli.store.reset_calls == 0


def test_embedding_check_runs_before_store_creation(cli):
    """가용성 확인은 embed_query 1회 호출로 한다."""
    cli.openapi.sources = []
    code = _run(cli.monkeypatch, "--source", "openapi")
    assert code == 0
    assert len(cli.embeddings.calls) == 1


def test_full_resets_then_ingests(cli, capsys):
    source = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    cli.openapi.sources = [source]
    cli.openapi.specs = {source.spec_url: _spec("/a")}

    code = _run(cli.monkeypatch, "--source", "openapi", "--full")

    assert code == 0
    assert cli.store.reset_calls == 1
    assert [c.metadata["doc_id"] for c in cli.store.upserted] == ["svcA:GET:/a"]
    out = capsys.readouterr().out
    assert "[openapi] 추가 1" in out
    assert json.load(open(cli.manifest_path, encoding="utf-8"))["svcA:GET:/a"]["source"] == "openapi"


def test_openapi_partial_failure_exits_one_and_prints_summary(cli, capsys):
    ok = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    bad = OpenApiSource("svcB", "https://b/openapi.json", "https://b/docs")
    cli.openapi.sources = [ok, bad]
    cli.openapi.specs = {ok.spec_url: _spec("/a")}

    code = _run(cli.monkeypatch, "--source", "openapi")

    assert code == 1
    out = capsys.readouterr().out
    assert "실패 소스: svcB" in out
    assert [c.metadata["doc_id"] for c in cli.store.upserted] == ["svcA:GET:/a"]


def test_openapi_success_exits_zero(cli, capsys):
    source = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    cli.openapi.sources = [source]
    cli.openapi.specs = {source.spec_url: _spec("/a")}

    assert _run(cli.monkeypatch, "--source", "openapi") == 0
    assert "컬렉션 청크 수: 1" in capsys.readouterr().out


def test_second_run_reports_no_change(cli, capsys):
    source = OpenApiSource("svcA", "https://a/openapi.json", "https://a/docs")
    cli.openapi.sources = [source]
    cli.openapi.specs = {source.spec_url: _spec("/a")}

    _run(cli.monkeypatch, "--source", "openapi")
    capsys.readouterr()
    code = _run(cli.monkeypatch, "--source", "openapi")

    assert code == 0
    assert "[openapi] 추가 0 / 갱신 0 / 삭제 0" in capsys.readouterr().out


def test_confluence_auth_error_exits_one(cli, capsys):
    class _Repo:
        @classmethod
        def from_profile(cls):
            raise ConfluenceAuthError("Confluence 인증 실패(401). CONFLUENCE_API_TOKEN 환경변수를 확인하세요.")

    cli.monkeypatch.setattr(ingest, "ConfluenceRepository", _Repo)

    code = _run(cli.monkeypatch, "--source", "confluence")

    assert code == 1
    assert "인증 실패(401)" in capsys.readouterr().err


def test_invalid_source_choice_exits_two(cli):
    cli.monkeypatch.setattr("sys.argv", ["ingest.py", "--source", "invalid"])
    with pytest.raises(SystemExit) as excinfo:
        ingest.main()
    assert excinfo.value.code == 2
