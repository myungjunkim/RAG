import logging
import os

from src.config.profile import Profile

_STREAM_HANDLER_NAME = "kudos-rag-stream"
_FILE_HANDLER_NAME = "kudos-rag-file"


class GlobalLogger:
    """프로파일의 log-level / log-file-path 설정을 따르는 로거를 반환한다."""

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        root = logging.getLogger()
        # basicConfig 는 root 에 핸들러가 있으면 no-op 이므로 직접 부착하고, 이름으로 중복을 막는다
        if not any(h.name == _FILE_HANDLER_NAME for h in root.handlers):
            common = Profile().get_common_config()
            log_dir = common["log-file-path"]
            os.makedirs(log_dir, exist_ok=True)
            formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
            stream = logging.StreamHandler()
            stream.name = _STREAM_HANDLER_NAME
            stream.setFormatter(formatter)
            file = logging.FileHandler(f"{log_dir}/app.log", encoding="utf-8")
            file.name = _FILE_HANDLER_NAME
            file.setFormatter(formatter)
            root.addHandler(stream)
            root.addHandler(file)
            root.setLevel(getattr(logging, common.get("log-level", "INFO").upper(), logging.INFO))
            # 서드파티 HTTP·Chroma 내부 로그는 노이즈가 커서 WARNING 이상만 남긴다
            for noisy in ("httpx", "httpcore", "urllib3", "chromadb", "watchfiles"):
                logging.getLogger(noisy).setLevel(logging.WARNING)
        return logging.getLogger(name)
