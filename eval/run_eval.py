"""검색 품질 평가: eval/questions.yaml 의 질문마다 상위 k 청크에 기대 문서가 포함되는지 확인한다.

python -m eval.run_eval --active-profile=local [--k 6] [--file eval/questions.yaml]
(Ollama 임베딩이 필요하다)
"""
import argparse
import sys

import yaml

import global_variable
from src.repository.vector_store_repository import VectorStoreRepository
from src.service.retriever_service import RetrieverService

_PASS_RATE = 0.8
_SOURCES = ("all", "confluence", "openapi")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-profile", default="local", help="설정 프로파일 (resources/config_{profile}.ini)")
    parser.add_argument("--k", type=int, default=6, help="질문당 검색 청크 수 (hit@k 의 k)")
    parser.add_argument("--file", default=f"{global_variable.PROJECT_ROOT_DIR}/eval/questions.yaml",
                        help="평가 질문 yaml 경로")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as f:
        questions = (yaml.safe_load(f) or {}).get("questions", [])
    if not questions:
        print("평가 질문이 없습니다.")
        return 1

    bad = [q["question"] for q in questions if q.get("source", "all") not in _SOURCES]
    if bad:
        print(f"source 값이 올바르지 않습니다({'/'.join(_SOURCES)} 중 하나): {bad}")
        return 1

    retriever = RetrieverService.from_profile(VectorStoreRepository.from_profile())
    retriever.reload()

    hits = 0
    for q in questions:
        results = retriever.search(q["question"], q.get("source", "all"), top_k=args.k)
        found = [d.metadata["doc_id"] for d in results]
        hit = any(doc_id in found for doc_id in q["expected_doc_ids"])
        hits += hit
        print(f"{'O' if hit else 'X'} {q['question']}")
        if not hit:
            print(f"    기대: {q['expected_doc_ids']}")
            print(f"    실제: {found}")

    rate = hits / len(questions)
    print(f"\nhit@{args.k} = {hits}/{len(questions)} = {rate:.0%} (기준 {_PASS_RATE:.0%})")
    return 0 if rate >= _PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
