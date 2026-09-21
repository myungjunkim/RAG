"""openapi_sources.yaml 로딩과 OpenAPI 스펙(JSON/YAML) 다운로드."""
import json
import time

import requests
import yaml

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger
from src.service.openapi_document_service import OpenApiSource

logger = GlobalLogger.get_logger(__name__)

_MAX_ATTEMPTS = 3
_TIMEOUT_SEC = 30
_RETRY_STATUS = {429, 500, 502, 503, 504}


class OpenApiFetchError(Exception):
    pass


def load_sources(path: str) -> list[OpenApiSource]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [OpenApiSource(name=s["name"], spec_url=s["spec_url"], docs_url=s.get("docs_url", ""))
            for s in data.get("sources") or []]


class OpenApiRepository:
    def __init__(self, session=None, sleep=time.sleep):
        self._session = session or requests.Session()
        self._sleep = sleep

    @staticmethod
    def sources_from_profile() -> list[OpenApiSource]:
        return load_sources(Profile().get_config("openapi")["sources-file"])

    def fetch_spec(self, url: str) -> dict:
        last_status = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(url, timeout=_TIMEOUT_SEC)
            except requests.RequestException as e:
                logger.warning("OpenAPI 요청 실패(%s/%s) %s: %s", attempt, _MAX_ATTEMPTS, url, e)
                last_status = str(e)
            else:
                if response.status_code == 200:
                    return self._parse(response.text, url)
                last_status = response.status_code
                if response.status_code not in _RETRY_STATUS:
                    break
                logger.warning("OpenAPI 응답 %s (%s/%s) %s", response.status_code, attempt, _MAX_ATTEMPTS, url)
            if attempt < _MAX_ATTEMPTS:
                self._sleep(2 ** (attempt - 1))
        raise OpenApiFetchError(f"OpenAPI 스펙 다운로드 실패: {url} (마지막 상태: {last_status})")

    @staticmethod
    def _parse(text: str, url: str) -> dict:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as e:
                raise OpenApiFetchError(f"OpenAPI 스펙 파싱 실패: {url}: {e}") from e
        if not isinstance(data, dict):
            raise OpenApiFetchError(f"OpenAPI 스펙 형식이 올바르지 않습니다: {url}")
        return data
