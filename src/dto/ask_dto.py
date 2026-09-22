from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceFilter = Literal["all", "confluence", "openapi"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="질문")
    source: SourceFilter = Field(default="all", description="검색 대상 소스")
    top_k: Optional[int] = Field(default=None, ge=1, le=20, description="검색 청크 수(미지정 시 설정값)")


class SourceRef(BaseModel):
    index: int
    title: str
    url: str
    source: str
    snippet: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceRef]


class ReloadResponse(BaseModel):
    chunk_count: int


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama: bool
    chunk_count: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="검색어")
    source: SourceFilter = Field(default="all", description="검색 대상 소스")
    top_k: Optional[int] = Field(default=None, ge=1, le=20, description="검색 청크 수(미지정 시 설정값)")


class SearchChunk(BaseModel):
    chunk_id: str
    title: str
    url: str
    source: str
    content: str
    metadata: dict


class SearchResponse(BaseModel):
    chunks: list[SearchChunk]
