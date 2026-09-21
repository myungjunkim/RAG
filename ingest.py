"""인제스트 CLI.

python ingest.py --active-profile=local --source all|confluence|openapi [--full]
"""
import argparse
import sys

from src.config.profile import Profile
from src.library.global_logger import GlobalLogger
from src.repository.confluence_repository import ConfluenceAuthError, ConfluenceFetchError, ConfluenceRepository
from src.repository.openapi_repository import OpenApiRepository
from src.repository.vector_store_repository import VectorStoreRepository
from src.service import llm_factory
from src.service.ingest_service import IngestService, IngestSummary
from src.service.manifest import Manifest

logger = GlobalLogger.get_logger("ingest")


def _print_summary(summaries: list[IngestSummary]) -> None:
    print("\n=== 인제스트 결과 ===")
    for s in summaries:
        line = f"[{s.source}] 추가 {s.added} / 갱신 {s.changed} / 삭제 {s.removed} / 청크 {s.chunk_count}"
        if s.failed_sources:
            line += f" / 실패 소스: {', '.join(s.failed_sources)}"
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--active-profile", default="local")
    parser.add_argument("--source", choices=["all", "confluence", "openapi"], default="all")
    parser.add_argument("--full", action="store_true", help="컬렉션과 manifest 를 초기화하고 전체 재구축")
    args = parser.parse_args()

    retrieval = Profile().get_config("retrieval")
    embeddings = llm_factory.create_embeddings()
    try:
        embeddings.embed_query("연결 확인")
    except Exception as e:  # 모델 미설치(404)·미기동(연결 거부) 등 — 종류를 가리지 않고 안내 후 종료
        model = Profile().get_config("ollama")["embedding-model"]
        print(f"오류: 임베딩 모델을 사용할 수 없습니다. Ollama 기동 여부와 `ollama pull {model}` 을 확인하세요. ({e})",
              file=sys.stderr)
        return 1
    store = VectorStoreRepository.from_profile(embeddings)
    manifest = Manifest(Profile().get_config("chroma")["manifest-path"])
    service = IngestService(store, manifest, int(retrieval["chunk-size"]), int(retrieval["chunk-overlap"]))

    if args.full:
        logger.info("--full: 컬렉션 및 manifest 초기화")
        service.reset_all()

    summaries: list[IngestSummary] = []
    exit_code = 0
    if args.source in ("all", "confluence"):
        try:
            repo = ConfluenceRepository.from_profile()
            summaries.append(service.ingest_confluence(repo, Profile().get_config("confluence")["base-url"]))
        except ConfluenceAuthError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 1
        except ConfluenceFetchError as e:
            logger.error("Confluence 수집 실패: %s", e)
            summaries.append(IngestSummary(source="confluence", failed_sources=["confluence"]))
            exit_code = 1
    if args.source in ("all", "openapi"):
        summary = service.ingest_openapi(OpenApiRepository(), OpenApiRepository.sources_from_profile())
        summaries.append(summary)
        if summary.failed_sources:
            exit_code = 1

    _print_summary(summaries)
    print(f"컬렉션 청크 수: {store.count()}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
