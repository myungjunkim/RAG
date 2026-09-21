import logging
import os

import pytest

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger

_HANDLER_PREFIX = "kudos-rag-"
_FILE_HANDLER_NAME = "kudos-rag-file"


def _kudos_handlers():
    return [h for h in logging.getLogger().handlers if (h.name or "").startswith(_HANDLER_PREFIX)]


def _remove_kudos_handlers():
    """다른 모듈이 import 시점에 붙여 둔 kudos-rag-* 핸들러를 떼어 최초 부착 경로를 재현한다."""
    root = logging.getLogger()
    for handler in _kudos_handlers():
        root.removeHandler(handler)
        handler.close()


@pytest.fixture
def isolated_root():
    """테스트 전후로 kudos-rag-* 핸들러를 정리한다. 다른 테스트의 로깅에 영향을 주지 않는다."""
    original_level = logging.getLogger().level
    _remove_kudos_handlers()
    yield
    _remove_kudos_handlers()
    logging.getLogger().setLevel(original_level)


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    path = str(tmp_path / "logs")
    common = dict(Profile().get_common_config())
    common["log-file-path"] = path
    monkeypatch.setattr(Profile, "get_common_config", lambda self: common)
    return path


def test_get_logger_writes_message_to_file(isolated_root, log_dir):
    """리드 결정 1: basicConfig 대신 root 에 직접 부착하므로 pytest 안에서도 실제로 기록된다."""
    logger = GlobalLogger.get_logger("x")

    logger.info("hello")

    content = open(f"{log_dir}/app.log", encoding="utf-8").read()
    assert "INFO [x] hello" in content


def test_log_directory_and_file_are_created(isolated_root, log_dir):
    assert not os.path.exists(log_dir)

    GlobalLogger.get_logger("create-test")

    assert os.path.isdir(log_dir)
    assert os.path.isfile(f"{log_dir}/app.log")


def test_handlers_are_attached_only_once(isolated_root, log_dir):
    first = GlobalLogger.get_logger("same")
    second = GlobalLogger.get_logger("same")
    GlobalLogger.get_logger("other")

    assert first is second
    assert len([h for h in _kudos_handlers() if h.name == _FILE_HANDLER_NAME]) == 1
    assert len(_kudos_handlers()) == 2  # stream + file


def test_existing_root_handlers_are_preserved(isolated_root, log_dir):
    """force=True 를 쓰지 않으므로 pytest caplog 등 기존 핸들러가 제거되면 안 된다."""
    root = logging.getLogger()
    sentinel = logging.NullHandler()
    sentinel.name = "sentinel-handler"
    root.addHandler(sentinel)
    try:
        GlobalLogger.get_logger("preserve")
        assert sentinel in root.handlers
    finally:
        root.removeHandler(sentinel)


def test_caplog_still_captures_records(isolated_root, log_dir, caplog):
    """기존 핸들러 보존의 실증: caplog 캡처가 계속 동작한다."""
    logger = GlobalLogger.get_logger("caplog-test")

    with caplog.at_level(logging.INFO, logger="caplog-test"):
        logger.info("캡처되는 메시지")

    assert "캡처되는 메시지" in caplog.text
    assert "INFO [caplog-test] 캡처되는 메시지" in open(f"{log_dir}/app.log", encoding="utf-8").read()


def test_root_level_follows_profile_log_level(isolated_root, log_dir):
    GlobalLogger.get_logger("level-test")

    assert logging.getLogger().level == logging.DEBUG  # config_local.ini 의 log-level=DEBUG


def test_messages_from_multiple_loggers_share_one_file(isolated_root, log_dir):
    GlobalLogger.get_logger("first").info("첫 번째")
    GlobalLogger.get_logger("second").warning("두 번째")

    content = open(f"{log_dir}/app.log", encoding="utf-8").read()
    assert "INFO [first] 첫 번째" in content
    assert "WARNING [second] 두 번째" in content
