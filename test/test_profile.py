import global_variable
from src.config.profile import Profile


def test_active_profile_is_local():
    assert Profile().active_profile == "local"


def test_project_root_placeholder_is_replaced():
    chroma = Profile().get_config("chroma")
    assert "{project_root}" not in chroma["persist-dir"]
    assert chroma["persist-dir"].startswith(global_variable.PROJECT_ROOT_DIR)


def test_retrieval_config_has_expected_keys():
    retrieval = Profile().get_config("retrieval")
    assert retrieval["top-k"] == "6"
    assert Profile.get_value(retrieval, "missing-key", "fallback") == "fallback"


def test_common_config():
    assert Profile().api_root == "v1"
    assert Profile().get_common_config()["health_check_endpoint"] == "check"
