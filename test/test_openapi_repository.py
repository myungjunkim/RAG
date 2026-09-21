import json

import pytest
import requests

from src.repository.openapi_repository import OpenApiFetchError, OpenApiRepository, load_sources
from src.service.openapi_document_service import OpenApiSource


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self._responses.pop(0)


def test_load_sources(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("sources:\n  - name: a\n    spec_url: https://a/openapi.json\n    docs_url: https://a/docs\n", encoding="utf-8")
    sources = load_sources(str(f))
    assert len(sources) == 1
    assert sources[0].name == "a" and sources[0].docs_url == "https://a/docs"


def test_fetch_spec_json():
    session = FakeSession([FakeResponse(200, json.dumps({"openapi": "3.1.0", "paths": {}}))])
    spec = OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert spec["openapi"] == "3.1.0"


def test_fetch_spec_yaml():
    session = FakeSession([FakeResponse(200, "openapi: 3.1.0\npaths: {}\n")])
    spec = OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.yaml")
    assert spec["openapi"] == "3.1.0"


def test_fetch_spec_retries_then_fails():
    session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
    with pytest.raises(OpenApiFetchError):
        OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 3


def test_fetch_spec_404_no_retry():
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(OpenApiFetchError):
        OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 1


def test_sources_from_profile_reads_two_services():
    names = {s.name for s in OpenApiRepository.sources_from_profile()}
    assert names == {"general-chatbot-api", "message-api"}


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

class RecordingSession(FakeSession):
    """timeout 을 기록하고, 응답 대신 예외를 돌려줄 수 있는 세션."""

    def __init__(self, responses):
        super().__init__(responses)
        self.timeouts = []

    def get(self, url, timeout=None):
        self.timeouts.append(timeout)
        self.calls.append(url)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _repo(session, sleeps):
    return OpenApiRepository(session=session, sleep=sleeps.append)


def test_backoff_delays_are_one_then_two_seconds():
    session = FakeSession([FakeResponse(503), FakeResponse(429), FakeResponse(200, '{"openapi": "3.1.0"}')])
    sleeps = []
    spec = _repo(session, sleeps).fetch_spec("https://a/openapi.json")
    assert spec == {"openapi": "3.1.0"}
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_gives_up_after_three_failures_sleeps_twice():
    session = FakeSession([FakeResponse(500), FakeResponse(502), FakeResponse(504)])
    sleeps = []
    with pytest.raises(OpenApiFetchError):
        _repo(session, sleeps).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_400_is_not_retried():
    session = FakeSession([FakeResponse(400)])
    sleeps = []
    with pytest.raises(OpenApiFetchError):
        _repo(session, sleeps).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 1
    assert sleeps == []


def test_request_exception_is_retried_three_times():
    session = RecordingSession([requests.ConnectionError("boom")] * 3)
    sleeps = []
    with pytest.raises(OpenApiFetchError):
        _repo(session, sleeps).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_request_exception_then_success():
    session = RecordingSession([requests.Timeout("t"), FakeResponse(200, '{"openapi": "3.1.0"}')])
    sleeps = []
    assert _repo(session, sleeps).fetch_spec("https://a/openapi.json") == {"openapi": "3.1.0"}
    assert sleeps == [1]


def test_request_uses_timeout():
    session = RecordingSession([FakeResponse(200, '{"openapi": "3.1.0"}')])
    OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.json")
    assert session.timeouts == [30]


@pytest.mark.parametrize("text", ['[1, 2]', '123', 'null', '"abc"', '- a', ''])
def test_non_dict_payload_raises_without_retry(text):
    """JSON 리스트·스칼라, YAML 리스트, 빈 응답은 dict 가 아니므로 즉시 실패한다."""
    session = FakeSession([FakeResponse(200, text)])
    sleeps = []
    with pytest.raises(OpenApiFetchError):
        _repo(session, sleeps).fetch_spec("https://a/openapi.json")
    assert len(session.calls) == 1
    assert sleeps == []


def test_invalid_yaml_raises_without_retry():
    session = FakeSession([FakeResponse(200, "a: [b")])
    sleeps = []
    with pytest.raises(OpenApiFetchError):
        _repo(session, sleeps).fetch_spec("https://a/openapi.yaml")
    assert len(session.calls) == 1
    assert sleeps == []


def test_yaml_spec_is_parsed_when_json_fails():
    session = FakeSession([FakeResponse(200, "openapi: 3.1.0\npaths:\n  /a:\n    get: {}\n")])
    spec = OpenApiRepository(session=session, sleep=lambda s: None).fetch_spec("https://a/openapi.yaml")
    assert spec["paths"]["/a"] == {"get": {}}


def test_load_sources_without_docs_url(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("sources:\n  - name: a\n    spec_url: https://a/openapi.json\n", encoding="utf-8")
    sources = load_sources(str(f))
    assert sources[0].docs_url == ""
    assert sources[0].spec_url == "https://a/openapi.json"


def test_load_sources_empty_file(tmp_path):
    f = tmp_path / "empty.yaml"
    f.write_text("", encoding="utf-8")
    assert load_sources(str(f)) == []


def test_load_sources_without_sources_key(tmp_path):
    f = tmp_path / "other.yaml"
    f.write_text("other: 1\n", encoding="utf-8")
    assert load_sources(str(f)) == []


def test_load_sources_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sources(str(tmp_path / "nope.yaml"))


def test_sources_from_profile_details():
    sources = OpenApiRepository.sources_from_profile()
    assert len(sources) == 2
    assert all(isinstance(s, OpenApiSource) for s in sources)
    assert all(s.spec_url.startswith("https://") for s in sources)
    assert all(s.docs_url.startswith("https://") for s in sources)


def test_sources_from_profile_does_not_perform_request(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("sources_from_profile 에서 요청이 발생했다")

    monkeypatch.setattr(requests.Session, "request", _explode)
    monkeypatch.setattr(requests.Session, "get", _explode)
    assert len(OpenApiRepository.sources_from_profile()) == 2


def test_load_sources_with_empty_sources_key(tmp_path):
    """`sources:` 키만 있고 항목이 없는 파일(소스 전체 주석 처리 등)도 빈 목록이다. (Task 5 후속 수정 5-F)"""
    f = tmp_path / "null_sources.yaml"
    f.write_text("sources:\n", encoding="utf-8")
    assert load_sources(str(f)) == []


def test_load_sources_with_empty_sources_list(tmp_path):
    f = tmp_path / "empty_list.yaml"
    f.write_text("sources: []\n", encoding="utf-8")
    assert load_sources(str(f)) == []
