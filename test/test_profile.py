import configparser
import os
import subprocess
import sys

import global_variable
from src.config.argument import CommandlineArgument
from src.config.profile import Profile


def test_active_profile_is_local():
    assert Profile().active_profile == "local"


def test_project_dirs_use_forward_slash():
    assert os.path.isdir(global_variable.PROJECT_ROOT_DIR)
    assert "\\" not in global_variable.PROJECT_ROOT_DIR
    assert global_variable.PROJECT_RESOURCE_DIR == f"{global_variable.PROJECT_ROOT_DIR}/resources"
    assert os.path.isfile(f"{global_variable.PROJECT_RESOURCE_DIR}/config_local.ini")


def test_commandline_argument_matches_profile():
    assert CommandlineArgument().get_active_profile() == Profile().active_profile == "local"


def test_commandline_argument_reflects_given_profile():
    """싱글톤이라 같은 프로세스에서 재파싱할 수 없으므로 별도 프로세스로 확인한다."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.config.argument import CommandlineArgument;"
            "print(CommandlineArgument().get_active_profile())",
            "--active-profile=dev",
            "-q",  # pytest/uvicorn 등 알 수 없는 인자는 무시돼야 한다
        ],
        cwd=global_variable.PROJECT_ROOT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dev"


def test_commandline_argument_defaults_to_local_without_option():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.config.argument import CommandlineArgument;"
            "print(CommandlineArgument().get_active_profile())",
        ],
        cwd=global_variable.PROJECT_ROOT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "local"


def test_project_root_placeholder_is_replaced():
    chroma = Profile().get_config("chroma")
    assert "{project_root}" not in chroma["persist-dir"]
    assert chroma["persist-dir"].startswith(global_variable.PROJECT_ROOT_DIR)


def test_retrieval_config_has_expected_keys():
    retrieval = Profile().get_config("retrieval")
    assert retrieval["top-k"] == "6"
    assert Profile.get_value(retrieval, "missing-key", "fallback") == "fallback"


def test_get_value_returns_existing_value_and_none_default():
    retrieval = Profile().get_config("retrieval")
    assert Profile.get_value(retrieval, "top-k") == "6"
    assert Profile.get_value(retrieval, "missing-key") is None
    assert Profile.get_value({}, "any-key", "fallback") == "fallback"


def test_common_config():
    assert Profile().api_root == "v1"
    assert Profile().get_common_config()["health_check_endpoint"] == "check"


def test_common_config_log_settings_are_resolved():
    common = Profile().get_common_config()
    assert common["log-level"] == "DEBUG"
    assert common["log-file-path"] == f"{global_variable.PROJECT_ROOT_DIR}/logs"


def test_chroma_and_openapi_paths_are_resolved():
    chroma = Profile().get_config("chroma")
    assert chroma["persist-dir"] == f"{global_variable.PROJECT_ROOT_DIR}/data/chroma"
    assert chroma["manifest-path"] == f"{global_variable.PROJECT_ROOT_DIR}/data/manifest.json"
    assert chroma["collection"] == "kudos_rag"
    openapi = Profile().get_config("openapi")
    assert openapi["sources-file"] == f"{global_variable.PROJECT_ROOT_DIR}/resources/openapi_sources.yaml"
    assert os.path.isfile(openapi["sources-file"])


def test_ini_template_has_no_credentials():
    """커밋 대상인 템플릿(config_local.ini.example)에 자격 증명이 들어 있지 않아야 한다.

    개인 설정이 담기는 resources/config_local.ini 는 gitignore 대상이므로,
    '커밋되지 않음' 검증의 대상은 템플릿 쪽이다.
    """
    template = f"{global_variable.PROJECT_RESOURCE_DIR}/config_local.ini.example"
    assert os.path.isfile(template), "커밋되는 설정 템플릿이 없다"

    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    parser.read(template, encoding="utf-8")
    confluence = parser["confluence"]
    assert confluence["email"] == ""
    assert confluence["api-token"] == ""
    assert confluence["base-url"] == "https://ihunet.atlassian.net/wiki"
    assert confluence["space-key"] == "KUDOS"


def test_local_ini_keeps_api_token_empty():
    """로컬 ini 는 email 이 개인 설정으로 채워질 수 있으나, 토큰은 항상 env 로만 넣는다."""
    assert Profile().get_config("confluence")["api-token"] == ""


def test_profile_is_singleton():
    assert Profile() is Profile()
    assert CommandlineArgument() is CommandlineArgument()
