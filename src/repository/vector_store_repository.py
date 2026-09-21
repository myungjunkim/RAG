"""Chroma(로컬 persist) 접근. 인제스트와 서빙이 공유하는 유일한 저장소."""
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.config.profile import Profile
from src.service import llm_factory


class VectorStoreRepository:
    def __init__(self, persist_dir: str, collection_name: str, embeddings, batch_size: int = 32):
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._embeddings = embeddings
        self._batch_size = batch_size
        self._store = self._open()

    def _open(self) -> Chroma:
        return Chroma(
            collection_name=self._collection_name,
            embedding_function=self._embeddings,
            persist_directory=self._persist_dir,
            collection_metadata={"hnsw:space": "cosine"},
            # 익명 사용 통계 외부 전송을 끈다. persist 설정은 인자와 같은 값을 넣어 어긋나지 않게 한다
            client_settings=Settings(
                anonymized_telemetry=False,
                persist_directory=self._persist_dir,
                is_persistent=True,
            ),
        )

    def reopen(self) -> None:
        """인제스트 프로세스가 컬렉션을 삭제·재생성(--full)한 뒤에도 최신 컬렉션을 가리키도록 다시 연다."""
        self._store = self._open()

    @classmethod
    def from_profile(cls, embeddings=None) -> "VectorStoreRepository":
        chroma = Profile().get_config("chroma")
        retrieval = Profile().get_config("retrieval")
        return cls(
            chroma["persist-dir"],
            chroma["collection"],
            embeddings or llm_factory.create_embeddings(),
            batch_size=int(retrieval.get("embed-batch-size", 32)),
        )

    def upsert(self, chunks: list[Document]) -> None:
        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start:start + self._batch_size]
            ids = [c.metadata["chunk_id"] for c in batch]
            # Chroma 는 None 메타데이터를 거부한다
            cleaned = [Document(page_content=c.page_content,
                                metadata={k: v for k, v in c.metadata.items() if v is not None}) for c in batch]
            self._store.add_documents(cleaned, ids=ids)

    def delete(self, chunk_ids: list[str]) -> None:
        if chunk_ids:
            self._store.delete(ids=list(chunk_ids))

    def get_all(self) -> list[Document]:
        data = self._store.get(include=["documents", "metadatas"])
        return [Document(page_content=text, metadata=meta or {})
                for text, meta in zip(data["documents"], data["metadatas"])]

    def count(self) -> int:
        return self._store._collection.count()

    def reset(self) -> None:
        self._store.delete_collection()
        self._store = self._open()

    def as_retriever(self, k: int, source: str | None = None):
        search_kwargs: dict = {"k": k}
        if source:
            search_kwargs["filter"] = {"source": source}
        return self._store.as_retriever(search_kwargs=search_kwargs)
