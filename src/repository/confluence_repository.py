"""Confluence Cloud REST API v2 호출. 인증·페이지네이션·재시도를 담당한다."""
import os
import time

import requests

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger

logger = GlobalLogger.get_logger(__name__)

_PAGE_LIMIT = 250
_MAX_ATTEMPTS = 3
_TIMEOUT_SEC = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ConfluenceAuthError(Exception):
    pass


class ConfluenceFetchError(Exception):
    pass


class ConfluenceRepository:
    def __init__(self, base_url: str, space_key: str, email: str, api_token: str, session=None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        # _links.next 는 "/wiki/api/v2/..." 형태의 사이트 루트 기준 경로
        self._site_root = self.base_url[: -len("/wiki")] if self.base_url.endswith("/wiki") else self.base_url
        self.space_key = space_key
        self.email = email
        self.api_token = api_token
        self._sleep = sleep
        self._session = session or requests.Session()
        self._session.auth = (email, api_token)

    @classmethod
    def from_profile(cls) -> "ConfluenceRepository":
        config = Profile().get_config("confluence")
        token = os.environ.get("CONFLUENCE_API_TOKEN") or config.get("api-token", "")
        return cls(config["base-url"], config["space-key"], config.get("email", ""), token)

    def _get(self, url: str, params: dict | None = None) -> dict:
        last_status = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(url, params=params, timeout=_TIMEOUT_SEC)
            except requests.RequestException as e:
                logger.warning("Confluence 요청 실패(%s/%s) %s: %s", attempt, _MAX_ATTEMPTS, url, e)
                last_status = str(e)
            else:
                if response.status_code in (401, 403):
                    raise ConfluenceAuthError(
                        f"Confluence 인증 실패({response.status_code}). "
                        "CONFLUENCE_API_TOKEN 환경변수와 [confluence] email 설정을 확인하세요."
                    )
                if response.status_code == 200:
                    return response.json()
                last_status = response.status_code
                if response.status_code not in _RETRY_STATUS:
                    break
                logger.warning("Confluence 응답 %s (%s/%s) %s", response.status_code, attempt, _MAX_ATTEMPTS, url)
            if attempt < _MAX_ATTEMPTS:
                self._sleep(2 ** (attempt - 1))
        raise ConfluenceFetchError(f"Confluence 요청 실패: {url} (마지막 상태: {last_status})")

    def fetch_space_id(self) -> str:
        data = self._get(f"{self.base_url}/api/v2/spaces", params={"keys": self.space_key})
        results = data.get("results", [])
        if not results:
            raise ConfluenceFetchError(f"스페이스를 찾을 수 없습니다: {self.space_key}")
        return str(results[0]["id"])

    def fetch_pages(self) -> list[dict]:
        space_id = self.fetch_space_id()
        url = f"{self.base_url}/api/v2/spaces/{space_id}/pages"
        params: dict | None = {"status": "current", "body-format": "storage", "limit": _PAGE_LIMIT}
        pages: list[dict] = []
        while url:
            data = self._get(url, params=params)
            pages.extend(data.get("results", []))
            next_link = (data.get("_links") or {}).get("next")
            url = f"{self._site_root}{next_link}" if next_link else None
            params = None  # next 링크에 쿼리가 포함돼 있다
        logger.info("Confluence 페이지 %s건 수집 (space=%s)", len(pages), self.space_key)
        return pages
