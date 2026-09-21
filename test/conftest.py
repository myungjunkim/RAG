import logging

import pytest

_FILE_HANDLER_NAME = "kudos-rag-file"
_HANDLER_PREFIX = "kudos-rag-"


def pytest_addoption(parser):
    parser.addoption("--active-profile", action="store", default="local")


def _remove_kudos_handlers():
    root = logging.getLogger()
    for handler in [h for h in root.handlers if (h.name or "").startswith(_HANDLER_PREFIX)]:
        root.removeHandler(handler)
        handler.close()


@pytest.fixture(scope="session")
def test_log_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("logs")


@pytest.fixture(scope="session", autouse=True)
def _detach_import_time_log_handlers():
    """수집 단계 import 로 프로젝트 logs/ 에 붙은 핸들러를 뗀다.

    Profile 설정값 자체는 건드리지 않는다(설정 검증 테스트가 실제 값을 확인해야 하므로).
    """
    _remove_kudos_handlers()
    yield
    _remove_kudos_handlers()


@pytest.fixture(autouse=True)
def isolate_test_logs(test_log_dir, _detach_import_time_log_handlers):
    """테스트 로그가 프로젝트 logs/app.log 에 쌓이지 않게 tmp 로 향하는 핸들러를 유지한다.

    GlobalLogger 는 root 에 `kudos-rag-file` 이름의 핸들러가 있으면 재부착하지 않으므로,
    같은 이름으로 tmp 파일 핸들러를 걸어 두면 어떤 모듈이 get_logger 를 불러도 tmp 로만 기록된다.
    """
    root = logging.getLogger()
    if not any((h.name or "") == _FILE_HANDLER_NAME for h in root.handlers):
        handler = logging.FileHandler(f"{test_log_dir}/app.log", encoding="utf-8")
        handler.name = _FILE_HANDLER_NAME
        root.addHandler(handler)
    yield
