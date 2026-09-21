"""소스별 수집 → Document → 청킹 → 증분 인덱싱 오케스트레이션."""
import hashlib
from dataclasses import dataclass, field

from langchain_core.documents import Document

from src.library.global_logger import GlobalLogger
from src.repository.confluence_repository import ConfluenceRepository
from src.repository.openapi_repository import OpenApiFetchError, OpenApiRepository
from src.repository.vector_store_repository import VectorStoreRepository
from src.service import confluence_document_service, openapi_document_service
from src.service.chunk_service import split_documents
from src.service.manifest import Manifest, compute_diff
from src.service.openapi_document_service import OpenApiSource

logger = GlobalLogger.get_logger(__name__)


@dataclass
class IngestSummary:
    source: str
    added: int = 0
    changed: int = 0
    removed: int = 0
    chunk_count: int = 0
    failed_sources: list[str] = field(default_factory=list)


def confluence_fingerprint(doc: Document) -> str:
    return str(doc.metadata.get("version", ""))


def openapi_fingerprint(doc: Document) -> str:
    return hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()


class IngestService:
    def __init__(self, vector_store: VectorStoreRepository, manifest: Manifest, chunk_size: int, chunk_overlap: int):
        self._store = vector_store
        self._manifest = manifest
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def ingest_documents(self, source: str, docs: list[Document], fingerprints: dict[str, str],
                         removable=lambda _: True) -> IngestSummary:
        diff = compute_diff(self._manifest, source, fingerprints, removable)
        by_id = {d.metadata["doc_id"]: d for d in docs}
        summary = IngestSummary(source=source, added=len(diff.added), changed=len(diff.changed), removed=len(diff.removed))

        for doc_id in diff.removed:
            self._store.delete(self._manifest.get(doc_id)["chunk_ids"])
            self._manifest.remove(doc_id)

        for doc_id in diff.changed + diff.added:
            doc = by_id[doc_id]
            previous = self._manifest.get(doc_id)
            if previous:
                self._store.delete(previous["chunk_ids"])
            chunks = split_documents([doc], self._chunk_size, self._chunk_overlap)
            self._store.upsert(chunks)
            # 저장 성공 후에만 manifest 갱신 → 실패 시 다음 실행에서 재시도된다
            self._manifest.set(doc_id, fingerprints[doc_id], [c.metadata["chunk_id"] for c in chunks], source)
            summary.chunk_count += len(chunks)
            self._manifest.save()

        self._manifest.save()
        logger.info("[%s] 추가 %s, 갱신 %s, 삭제 %s, 변경 없음 %s, 청크 %s",
                    source, summary.added, summary.changed, summary.removed, len(diff.unchanged), summary.chunk_count)
        return summary

    def ingest_confluence(self, repo: ConfluenceRepository, base_url: str) -> IngestSummary:
        pages = repo.fetch_pages()
        docs = confluence_document_service.build_documents(pages, base_url)
        fingerprints = {d.metadata["doc_id"]: confluence_fingerprint(d) for d in docs}
        return self.ingest_documents("confluence", docs, fingerprints)

    def ingest_openapi(self, repo: OpenApiRepository, sources: list[OpenApiSource]) -> IngestSummary:
        docs: list[Document] = []
        succeeded: list[str] = []
        failed: list[str] = []
        for source in sources:
            try:
                spec = repo.fetch_spec(source.spec_url)
            except OpenApiFetchError as e:
                logger.error("OpenAPI 소스 실패 %s: %s", source.name, e)
                failed.append(source.name)
                continue
            docs.extend(openapi_document_service.build_documents(spec, source))
            succeeded.append(source.name)
        fingerprints = {d.metadata["doc_id"]: openapi_fingerprint(d) for d in docs}
        # 수집에 성공한 서비스의 문서만 삭제 대상으로 본다
        summary = self.ingest_documents(
            "openapi", docs, fingerprints,
            removable=lambda doc_id: any(doc_id.startswith(f"{name}:") for name in succeeded),
        )
        summary.failed_sources = failed
        return summary

    def reset_all(self) -> None:
        self._store.reset()
        self._manifest.clear()
        self._manifest.save()
