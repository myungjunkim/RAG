import argparse

from advanced_python_singleton.singleton import Singleton


class CommandlineArgument(metaclass=Singleton):
    """--active-profile 인자를 한 번만 파싱해 보관한다. pytest/uvicorn 등 다른 인자는 무시한다."""

    def __init__(self):
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--active-profile", dest="active_profile", default="local")
        args, _ = parser.parse_known_args()
        self.__active_profile = args.active_profile

    def get_active_profile(self) -> str:
        return self.__active_profile
