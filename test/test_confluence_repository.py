import pytest
import requests

from src.repository.confluence_repository import (
    ConfluenceAuthError,
    ConfluenceFetchError,
    ConfluenceRepository,
)

BASE = "https://ihunet.atlassian.net/wiki"


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    """호출 순서대로 미리 정해둔 응답을 돌려주는 세션."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.auth = None

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


def _repo(session):
    return ConfluenceRepository(BASE, "KUDOS", "me@hunet.co.kr", "token", session=session, sleep=lambda s: None)


def test_fetch_space_id():
    session = FakeSession([FakeResponse(200, {"results": [{"id": "622596", "key": "KUDOS"}]})])
    assert _repo(session).fetch_space_id() == "622596"
    url, params = session.calls[0]
    assert url == f"{BASE}/api/v2/spaces"
    assert params["keys"] == "KUDOS"


def test_fetch_pages_follows_cursor():
    session = FakeSession([
        FakeResponse(200, {"results": [{"id": "622596"}]}),
        FakeResponse(200, {"results": [{"id": "1", "title": "a"}],
                           "_links": {"next": "/wiki/api/v2/spaces/622596/pages?cursor=abc&limit=250"}}),
        FakeResponse(200, {"results": [{"id": "2", "title": "b"}], "_links": {}}),
    ])
    pages = _repo(session).fetch_pages()
    assert [p["id"] for p in pages] == ["1", "2"]
    first_url, first_params = session.calls[1]
    assert first_url == f"{BASE}/api/v2/spaces/622596/pages"
    assert first_params == {"status": "current", "body-format": "storage", "limit": 250}
    # next 링크는 사이트 루트 기준 절대 경로이므로 그대로 이어 붙인다
    assert session.calls[2][0] == "https://ihunet.atlassian.net/wiki/api/v2/spaces/622596/pages?cursor=abc&limit=250"


def test_auth_error_raises_immediately():
    session = FakeSession([FakeResponse(401)])
    with pytest.raises(ConfluenceAuthError):
        _repo(session).fetch_space_id()
    assert len(session.calls) == 1


def test_retries_on_429_then_succeeds():
    session = FakeSession([FakeResponse(429), FakeResponse(503),
                           FakeResponse(200, {"results": [{"id": "9"}]})])
    assert _repo(session).fetch_space_id() == "9"
    assert len(session.calls) == 3


def test_gives_up_after_three_failures():
    session = FakeSession([FakeResponse(500), FakeResponse(500), FakeResponse(500)])
    with pytest.raises(ConfluenceFetchError):
        _repo(session).fetch_space_id()


def test_space_not_found():
    session = FakeSession([FakeResponse(200, {"results": []})])
    with pytest.raises(ConfluenceFetchError):
        _repo(session).fetch_space_id()


def test_from_profile_prefers_env_token(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "env-token")
    repo = ConfluenceRepository.from_profile()
    assert repo.api_token == "env-token"
    assert repo.space_key == "KUDOS"


class RecordingSession(FakeSession):
    """timeout 인자까지 기록하고, 응답 대신 예외를 돌려줄 수 있는 세션."""

    def __init__(self, responses):
        super().__init__(responses)
        self.timeouts = []

    def get(self, url, params=None, timeout=None):
        self.timeouts.append(timeout)
        self.calls.append((url, params))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _repo_with_sleep(session, sleeps, base=BASE):
    return ConfluenceRepository(base, "KUDOS", "me@hunet.co.kr", "token",
                                session=session, sleep=sleeps.append)


def test_403_raises_auth_error_without_retry_or_sleep():
    session = FakeSession([FakeResponse(403)])
    sleeps = []
    with pytest.raises(ConfluenceAuthError):
        _repo_with_sleep(session, sleeps).fetch_space_id()
    assert len(session.calls) == 1
    assert sleeps == []


def test_auth_error_message_guides_token_and_email_settings():
    session = FakeSession([FakeResponse(401)])
    with pytest.raises(ConfluenceAuthError) as excinfo:
        _repo(session).fetch_space_id()
    message = str(excinfo.value)
    assert "CONFLUENCE_API_TOKEN" in message
    assert "email" in message


def test_backoff_delays_are_one_then_two_seconds():
    session = FakeSession([FakeResponse(500), FakeResponse(502), FakeResponse(200, {"results": [{"id": "9"}]})])
    sleeps = []
    assert _repo_with_sleep(session, sleeps).fetch_space_id() == "9"
    assert sleeps == [1, 2]


def test_gives_up_after_three_failures_sleeps_twice():
    session = FakeSession([FakeResponse(503), FakeResponse(504), FakeResponse(429)])
    sleeps = []
    with pytest.raises(ConfluenceFetchError):
        _repo_with_sleep(session, sleeps).fetch_space_id()
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_404_is_not_retried():
    session = FakeSession([FakeResponse(404)])
    sleeps = []
    with pytest.raises(ConfluenceFetchError):
        _repo_with_sleep(session, sleeps).fetch_space_id()
    assert len(session.calls) == 1
    assert sleeps == []


def test_400_is_not_retried():
    session = FakeSession([FakeResponse(400)])
    sleeps = []
    with pytest.raises(ConfluenceFetchError):
        _repo_with_sleep(session, sleeps).fetch_space_id()
    assert len(session.calls) == 1
    assert sleeps == []


def test_request_exception_is_retried_three_times():
    session = RecordingSession([requests.ConnectionError("boom")] * 3)
    sleeps = []
    with pytest.raises(ConfluenceFetchError):
        _repo_with_sleep(session, sleeps).fetch_space_id()
    assert len(session.calls) == 3
    assert sleeps == [1, 2]


def test_request_exception_then_success():
    session = RecordingSession([requests.Timeout("t"), FakeResponse(200, {"results": [{"id": "5"}]})])
    sleeps = []
    assert _repo_with_sleep(session, sleeps).fetch_space_id() == "5"
    assert sleeps == [1]


def test_requests_use_timeout():
    session = RecordingSession([FakeResponse(200, {"results": [{"id": "1"}]})])
    _repo(session).fetch_space_id()
    assert session.timeouts == [30]


def test_base_url_trailing_slash_is_stripped():
    session = FakeSession([FakeResponse(200, {"results": [{"id": "1"}]})])
    repo = ConfluenceRepository(f"{BASE}/", "KUDOS", "e", "t", session=session, sleep=lambda s: None)
    assert repo.base_url == BASE
    repo.fetch_space_id()
    assert session.calls[0][0] == f"{BASE}/api/v2/spaces"


def test_next_link_on_base_url_without_wiki_suffix():
    """base_url 이 '/wiki' 로 끝나지 않으면 site_root 는 base_url 그대로다."""
    session = FakeSession([
        FakeResponse(200, {"results": [{"id": "10"}]}),
        FakeResponse(200, {"results": [{"id": "1"}], "_links": {"next": "/api/v2/spaces/10/pages?cursor=x"}}),
        FakeResponse(200, {"results": [{"id": "2"}]}),
    ])
    repo = ConfluenceRepository("https://example.com", "KUDOS", "e", "t", session=session, sleep=lambda s: None)
    assert [p["id"] for p in repo.fetch_pages()] == ["1", "2"]
    assert session.calls[2][0] == "https://example.com/api/v2/spaces/10/pages?cursor=x"


def test_cursor_request_sends_no_params():
    session = FakeSession([
        FakeResponse(200, {"results": [{"id": "622596"}]}),
        FakeResponse(200, {"results": [{"id": "1"}], "_links": {"next": "/wiki/api/v2/x?cursor=abc"}}),
        FakeResponse(200, {"results": [{"id": "2"}]}),
    ])
    _repo(session).fetch_pages()
    assert session.calls[2][1] is None


def test_fetch_pages_with_empty_space():
    session = FakeSession([
        FakeResponse(200, {"results": [{"id": "622596"}]}),
        FakeResponse(200, {"results": []}),
    ])
    assert _repo(session).fetch_pages() == []


def test_fetch_pages_accumulates_three_pages():
    session = FakeSession([
        FakeResponse(200, {"results": [{"id": "622596"}]}),
        FakeResponse(200, {"results": [{"id": "1"}], "_links": {"next": "/wiki/api/v2/x?cursor=1"}}),
        FakeResponse(200, {"results": [{"id": "2"}], "_links": {"next": "/wiki/api/v2/x?cursor=2"}}),
        FakeResponse(200, {"results": [{"id": "3"}], "_links": None}),
    ])
    assert [p["id"] for p in _repo(session).fetch_pages()] == ["1", "2", "3"]


def test_session_auth_is_set_from_credentials():
    session = FakeSession([])
    ConfluenceRepository(BASE, "KUDOS", "me@hunet.co.kr", "token", session=session, sleep=lambda s: None)
    assert session.auth == ("me@hunet.co.kr", "token")


def test_from_profile_falls_back_to_ini_token_without_env(monkeypatch):
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    repo = ConfluenceRepository.from_profile()
    assert repo.api_token == ""  # 토큰은 env 로만 주입하고 ini 는 빈 값을 유지한다
    assert repo.base_url == "https://ihunet.atlassian.net/wiki"
    assert repo.space_key == "KUDOS"


def test_from_profile_does_not_perform_request(monkeypatch):
    """from_profile 은 세션만 만들고 네트워크 호출을 하지 않는다."""
    def _explode(*args, **kwargs):
        raise AssertionError("from_profile 에서 요청이 발생했다")

    monkeypatch.setattr(requests.Session, "request", _explode)
    monkeypatch.setattr(requests.Session, "get", _explode)
    repo = ConfluenceRepository.from_profile()
    assert isinstance(repo, ConfluenceRepository)


def test_fetch_space_id_coerces_numeric_id_to_str():
    session = FakeSession([FakeResponse(200, {"results": [{"id": 622596}]})])
    space_id = _repo(session).fetch_space_id()
    assert space_id == "622596"
    assert isinstance(space_id, str)
