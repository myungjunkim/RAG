"""검색 결과를 근거로 LLM 답변을 생성한다. 단일 질의(멀티턴 없음)."""
import asyncio
from typing import AsyncIterator

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from src.service import llm_factory

NOT_FOUND_ANSWER = "관련 내용을 문서에서 찾지 못했습니다."
_SNIPPET_LEN = 200

SYSTEM_PROMPT = """당신은 팀 내부 문서(Confluence)와 API 명세(OpenAPI)를 근거로 답하는 어시스턴트입니다.

규칙:
1. 아래 제공된 문서 내용만 근거로 답합니다. 문서에 없는 내용은 추측하지 않습니다.
2. 근거로 사용한 문서는 문장 끝에 [1], [2] 형식으로 번호를 인용합니다.
3. 문서에서 답을 찾을 수 없으면 정확히 "관련 내용을 문서에서 찾지 못했습니다."라고만 답합니다.
4. API 관련 질문에는 HTTP 메서드, 경로, 필수 파라미터/필드를 명시합니다.
5. 한국어로 간결하게 답합니다."""

_USER_TEMPLATE = """다음은 검색된 문서입니다.

{context}

---
질문: {question}"""


def _strip_prefix(text: str) -> str:
    """청킹 시 붙인 '[breadcrumb > section]' 첫 줄은 스니펫에서 제외한다."""
    first, sep, rest = text.partition("\n")
    return rest if first.startswith("[") and first.endswith("]") and sep else text


def build_context(chunks: list[Document]) -> tuple[str, list[dict]]:
    blocks, sources = [], []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        blocks.append(f"[{i}] {meta.get('title', '')} | {meta.get('url', '')}\n{chunk.page_content}")
        sources.append({
            "index": i,
            "title": meta.get("title", ""),
            "url": meta.get("url", ""),
            "source": meta.get("source", ""),
            "snippet": _strip_prefix(chunk.page_content).strip()[:_SNIPPET_LEN],
        })
    return "\n\n".join(blocks), sources


class RagService:
    def __init__(self, retriever, chat_model):
        self._retriever = retriever
        self._model = chat_model

    @classmethod
    def from_profile(cls, retriever) -> "RagService":
        return cls(retriever, llm_factory.create_chat_model())

    def _messages(self, question: str, context: str) -> list:
        return [SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=_USER_TEMPLATE.format(context=context, question=question))]

    def ask(self, question: str, source: str = "all", top_k: int | None = None) -> dict:
        chunks = self._retriever.search(question, source, top_k)
        if not chunks:
            return {"answer": NOT_FOUND_ANSWER, "sources": []}
        context, sources = build_context(chunks)
        response = self._model.invoke(self._messages(question, context))
        return {"answer": response.content, "sources": sources}

    async def ask_stream(self, question: str, source: str = "all", top_k: int | None = None) -> AsyncIterator[dict]:
        # 검색(임베딩 HTTP 1회)은 동기이므로 이벤트 루프를 막지 않도록 스레드에서 실행
        chunks = await asyncio.to_thread(self._retriever.search, question, source, top_k)
        if not chunks:
            yield {"event": "token", "data": NOT_FOUND_ANSWER}
            yield {"event": "sources", "data": []}
            yield {"event": "done", "data": ""}
            return
        context, sources = build_context(chunks)
        async for piece in self._model.astream(self._messages(question, context)):
            if piece.content:
                yield {"event": "token", "data": piece.content}
        yield {"event": "sources", "data": sources}
        yield {"event": "done", "data": ""}
