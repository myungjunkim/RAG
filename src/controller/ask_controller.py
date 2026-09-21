"""질의/재로드/헬스체크 엔드포인트."""
import json
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.config.profile import Profile
from src.dto.ask_dto import AskRequest, AskResponse, HealthResponse, ReloadResponse
from src.library.global_logger import GlobalLogger
from src.repository.vector_store_repository import VectorStoreRepository
from src.service import llm_factory
from src.service.rag_service import RagService
from src.service.retriever_service import RetrieverService

logger = GlobalLogger.get_logger(__name__)
router = APIRouter()

__api_root = Profile().api_root
__health_endpoint = Profile().get_common_config()["health_check_endpoint"]

_OLLAMA_DOWN_DETAIL = "Ollama 에 연결할 수 없습니다. `ollama serve` 실행 여부와 [ollama] base-url 설정을 확인하세요."
_LLM_TIMEOUT_DETAIL = "LLM 응답 시간이 초과되었습니다. [ollama] llm-timeout 을 늘리거나 더 작은 모델을 사용하세요."


@dataclass
class RagContext:
    retriever: RetrieverService
    rag_service: RagService


context: RagContext | None = None


def init_context() -> RagContext:
    global context
    retriever = RetrieverService.from_profile(VectorStoreRepository.from_profile())
    retriever.reload()
    context = RagContext(retriever, RagService.from_profile(retriever))
    return context


def get_context() -> RagContext:
    return context or init_context()


def _translate_llm_error(e: Exception) -> HTTPException:
    if isinstance(e, httpx.TimeoutException):
        return HTTPException(status_code=504, detail=_LLM_TIMEOUT_DETAIL)
    # 모델 미설치(ResponseError 404) 등 원인을 구분할 수 있도록 메시지를 덧붙인다
    return HTTPException(status_code=503, detail=f"{_OLLAMA_DOWN_DETAIL} ({e})")


@router.post(f"/{__api_root}/ask", response_model=AskResponse, tags=["질의"])
def ask(request: AskRequest):                 # async 제거 — 동기 LLM 호출을 스레드풀에서 실행
    try:
        return get_context().rag_service.ask(request.question, request.source, request.top_k)
    except llm_factory.LLM_ERRORS as e:
        logger.error("LLM 호출 실패: %s", e)
        raise _translate_llm_error(e)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(f"/{__api_root}/ask/stream", tags=["질의"])
async def ask_stream(request: AskRequest):
    rag = get_context().rag_service

    async def generate():
        try:
            async for ev in rag.ask_stream(request.question, request.source, request.top_k):
                yield _sse(ev["event"], ev["data"])
        except llm_factory.LLM_ERRORS as e:
            logger.error("LLM 스트리밍 실패: %s", e)
            yield _sse("error", _translate_llm_error(e).detail)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post(f"/{__api_root}/reload", response_model=ReloadResponse, tags=["관리"])
def reload():                                 # async 제거
    return ReloadResponse(chunk_count=get_context().retriever.reload())


@router.get(f"/{__health_endpoint}", response_model=HealthResponse, tags=["health check"])
def health_check():                           # async 제거 — ping_ollama 최대 3초 블로킹
    ollama_ok = llm_factory.ping_ollama()
    chunk_count = get_context().retriever.chunk_count
    status = "ok" if ollama_ok and chunk_count > 0 else "degraded"
    return HealthResponse(status=status, ollama=ollama_ok, chunk_count=chunk_count)
