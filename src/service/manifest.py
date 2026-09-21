"""doc_id → fingerprint/chunk_ids 를 기록해 증분 인제스트를 가능하게 하는 매니페스트."""
# 클래스 안의 set() 메서드가 내장 set 을 가리므로 어노테이션은 지연 평가한다
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable


class Manifest:
    def __init__(self, path: str):
        self._path = path
        self.entries: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                self.entries = json.load(f)
        else:
            self.entries = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp_path = f"{self._path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._path)  # 같은 디렉터리 내 rename 은 원자적이다

    def get(self, doc_id: str) -> dict | None:
        return self.entries.get(doc_id)

    def set(self, doc_id: str, fingerprint: str, chunk_ids: list[str], source: str) -> None:
        self.entries[doc_id] = {"fingerprint": fingerprint, "chunk_ids": list(chunk_ids), "source": source}

    def remove(self, doc_id: str) -> None:
        self.entries.pop(doc_id, None)

    def doc_ids_for_source(self, source: str) -> set[str]:
        return {doc_id for doc_id, e in self.entries.items() if e.get("source") == source}

    def clear(self) -> None:
        self.entries = {}


@dataclass
class IngestDiff:
    added: list[str]
    changed: list[str]
    removed: list[str]
    unchanged: list[str]


def compute_diff(manifest: Manifest, source: str, fingerprints: dict[str, str],
                 removable: Callable[[str], bool] = lambda _: True) -> IngestDiff:
    added, changed, unchanged = [], [], []
    for doc_id, fp in fingerprints.items():
        entry = manifest.get(doc_id)
        if entry is None:
            added.append(doc_id)
        elif entry["fingerprint"] != fp:
            changed.append(doc_id)
        else:
            unchanged.append(doc_id)
    removed = sorted(doc_id for doc_id in manifest.doc_ids_for_source(source)
                     if doc_id not in fingerprints and removable(doc_id))
    return IngestDiff(added=added, changed=changed, removed=removed, unchanged=unchanged)
