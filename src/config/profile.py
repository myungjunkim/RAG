import configparser

from advanced_python_singleton.singleton import Singleton

import global_variable
from src.config.argument import CommandlineArgument


class Profile(metaclass=Singleton):
    """resources/config_{profile}.ini 를 읽어 섹션 단위 dict 로 제공한다."""

    __CONFIG_PROFILE_PATH = "{dir}/config_{profile}.ini"
    __CONFIG_SECTION_COMMON = "common"
    __CONFIG_API_ROOT = "api-root"
    __PLACEHOLDER_PROJECT_ROOT = "{project_root}"

    def __init__(self):
        self.active_profile = CommandlineArgument().get_active_profile()
        # 값 안의 '%' 를 보간하지 않도록 interpolation 을 끈다
        self.__config = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
        self.__config.read(
            self.__CONFIG_PROFILE_PATH.format(dir=global_variable.PROJECT_RESOURCE_DIR, profile=self.active_profile),
            encoding="utf-8",
        )
        self.__common_config = self.get_config(self.__CONFIG_SECTION_COMMON)
        self.api_root = self.__common_config[self.__CONFIG_API_ROOT]

    def get_config(self, section: str) -> dict:
        return {
            key: value.replace(self.__PLACEHOLDER_PROJECT_ROOT, global_variable.PROJECT_ROOT_DIR)
            for key, value in self.__config.items(section)
        }

    def get_common_config(self) -> dict:
        return self.__common_config

    @staticmethod
    def get_value(config: dict, key: str, default=None):
        return config[key] if key in config else default
