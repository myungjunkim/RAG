"""LLM / 임베딩 객체 생성 단일 지점. 사내 서버 이전 시 이 파일만 교체한다."""
import httpx
import requests
from langchain_ollama import ChatOllama, OllamaEmbeddings
from ollama import ResponseError as OllamaResponseError

from src.config.profile import Profile

# LLM/임베딩 호출에서 "Ollama 쪽 문제"로 분류할 예외. 컨트롤러는 이 튜플만 잡는다
LLM_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, ConnectionError, OllamaResponseError)


def _ollama_config() -> dict:
    return Profile().get_config("ollama")


def create_embeddings() -> OllamaEmbeddings:
    config = _ollama_config()
    return OllamaEmbeddings(model=config["embedding-model"], base_url=config["base-url"])


def create_chat_model() -> ChatOllama:
    config = _ollama_config()
    return ChatOllama(
        model=config["llm-model"],
        base_url=config["base-url"],
        temperature=float(config.get("temperature", 0)),
        num_ctx=int(config.get("num-ctx", 16384)),
        reasoning=False,  # qwen3 thinking 모드 비활성화
        client_kwargs={"timeout": float(config.get("llm-timeout", 120))},
    )


def ping_ollama() -> bool:
    try:
        return requests.get(f"{_ollama_config()['base-url']}/api/tags", timeout=3).status_code == 200
    except requests.RequestException:
        return False


def has_model(name: str) -> bool:
    """Ollama 에 모델이 설치되어 있는지 /api/tags 로 확인한다. 태그 없는 이름은 ':latest' 로 본다."""
    try:
        response = requests.get(f"{_ollama_config()['base-url']}/api/tags", timeout=3)
        if response.status_code != 200:
            return False
        installed = {m.get("name", "") for m in response.json().get("models", [])}
    except (requests.RequestException, ValueError):
        return False
    wanted = name if ":" in name else f"{name}:latest"
    return wanted in installed or name in installed
