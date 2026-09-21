"""BM25(인메모리) + Chroma 벡터 검색을 RRF 로 결합하는 하이브리드 리트리버."""
import re

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger
from src.repository.vector_store_repository import VectorStoreRepository

logger = GlobalLogger.get_logger(__name__)

SOURCE_ALL = "all"
_TOKEN_RE = re.compile(r"[a-z0-9_{}./\-]+|[가-힣]+")


def tokenize(text: str) -> list[str]:
    """소문자화 → 영숫자/경로 토큰과 한글 토큰 분리. 한글은 2-gram 을, 경로는 조각을 추가한다."""
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        tokens.append(token)
        if "/" in token:
            tokens.extend(seg for seg in token.strip("/").split("/") if seg)
        elif "가" <= token[0] <= "힣" and len(token) > 2:
            tokens.extend(token[i:i + 2] for i in range(len(token) - 1))
    return tokens


class RetrieverService:
    def __init__(self, vector_store: VectorStoreRepository, bm25_k: int, vector_k: int,
                 bm25_weight: float, vector_weight: float, top_k: int):
        self._store = vector_store
        self._bm25_k = bm25_k
        self._vector_k = vector_k
        self._weights = [bm25_weight, vector_weight]
        self._top_k = top_k
        self._bm25: dict[str, BM25Retriever] = {}
        self.chunk_count = 0

    @classmethod
    def from_profile(cls, vector_store: VectorStoreRepository) -> "RetrieverService":
        c = Profile().get_config("retrieval")
        return cls(vector_store, int(c["bm25-k"]), int(c["vector-k"]),
                   float(c["bm25-weight"]), float(c["vector-weight"]), int(c["top-k"]))

    def reload(self) -> int:
        self._store.reopen()
        chunks = self._store.get_all()
        groups: dict[str, list[Document]] = {SOURCE_ALL: chunks}
        for chunk in chunks:
            groups.setdefault(chunk.metadata.get("source", ""), []).append(chunk)
        # 검색 요청과 동시에 실행될 수 있으므로 완성된 인덱스를 한 번에 교체한다
        new_index = {source: BM25Retriever.from_documents(docs, preprocess_func=tokenize, k=self._bm25_k)
                     for source, docs in groups.items() if docs}
        self._bm25 = new_index
        self.chunk_count = len(chunks)
        logger.info("검색 인덱스 로드: 청크 %s개, 소스 %s", self.chunk_count, sorted(k for k in groups if k != SOURCE_ALL))
        return self.chunk_count

    def search(self, query: str, source: str = SOURCE_ALL, top_k: int | None = None) -> list[Document]:
        k = top_k or self._top_k
        bm25 = self._bm25.get(source)
        if bm25 is None:
            return []
        vector = self._store.as_retriever(k=self._vector_k, source=None if source == SOURCE_ALL else source)
        ensemble = EnsembleRetriever(retrievers=[bm25, vector], weights=self._weights)
        results: list[Document] = []
        seen: set[str] = set()
        for doc in ensemble.invoke(query):
            chunk_id = doc.metadata.get("chunk_id")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            results.append(doc)
            if len(results) >= k:
                break
        return results
