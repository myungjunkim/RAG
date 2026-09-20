import logging
import os

from src.config.profile import Profile


class GlobalLogger:
    """프로파일의 log-level / log-file-path 설정을 따르는 로거를 반환한다."""

    __configured = False

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        if not cls.__configured:
            common = Profile().get_common_config()
            log_dir = common["log-file-path"]
            os.makedirs(log_dir, exist_ok=True)
            handlers = [logging.StreamHandler(), logging.FileHandler(f"{log_dir}/app.log", encoding="utf-8")]
            logging.basicConfig(
                level=getattr(logging, common.get("log-level", "INFO").upper(), logging.INFO),
                format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                handlers=handlers,
            )
            cls.__configured = True
        return logging.getLogger(name)
