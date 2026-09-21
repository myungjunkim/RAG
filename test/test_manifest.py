import json
import os

from src.service.manifest import Manifest, compute_diff


def test_manifest_roundtrip(tmp_path):
    path = str(tmp_path / "manifest.json")
    m = Manifest(path)
    m.set("1", "v3", ["1#0", "1#1"], "confluence")
    m.save()
    m2 = Manifest(path)
    assert m2.get("1") == {"fingerprint": "v3", "chunk_ids": ["1#0", "1#1"], "source": "confluence"}
    assert m2.doc_ids_for_source("confluence") == {"1"}
    assert m2.doc_ids_for_source("openapi") == set()


def test_missing_file_is_empty(tmp_path):
    assert Manifest(str(tmp_path / "none.json")).entries == {}


def test_compute_diff(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    m.set("keep", "1", ["keep#0"], "confluence")
    m.set("change", "1", ["change#0"], "confluence")
    m.set("gone", "1", ["gone#0"], "confluence")
    m.set("other", "1", ["other#0"], "openapi")  # 다른 소스는 영향 없음
    diff = compute_diff(m, "confluence", {"keep": "1", "change": "2", "new": "1"})
    assert diff.unchanged == ["keep"]
    assert diff.changed == ["change"]
    assert diff.added == ["new"]
    assert diff.removed == ["gone"]


def test_compute_diff_respects_removable_scope(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    m.set("svcA:GET:/a", "1", ["svcA:GET:/a#0"], "openapi")
    m.set("svcB:GET:/b", "1", ["svcB:GET:/b#0"], "openapi")
    # svcB 는 이번에 수집 실패 → 삭제 대상에서 제외
    diff = compute_diff(m, "openapi", {}, removable=lambda doc_id: doc_id.startswith("svcA:"))
    assert diff.removed == ["svcA:GET:/a"]


# --- Validator 추가 검증 ---

def test_save_creates_parent_directory(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "manifest.json")
    m = Manifest(path)
    m.set("1", "v1", ["1#0"], "confluence")
    m.save()
    assert os.path.isfile(path)


def test_saved_file_is_readable_utf8_json(tmp_path):
    path = str(tmp_path / "m.json")
    m = Manifest(path)
    m.set("한글-id", "v1", ["한글-id#0"], "confluence")
    m.save()
    raw = open(path, encoding="utf-8").read()
    assert "한글-id" in raw  # ensure_ascii=False
    assert "\n  " in raw  # indent=2
    assert json.loads(raw)["한글-id"]["chunk_ids"] == ["한글-id#0"]


def test_remove_and_clear(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    m.set("1", "v1", ["1#0"], "confluence")
    m.set("2", "v1", ["2#0"], "openapi")
    m.remove("1")
    m.remove("없는-id")  # 예외 없음
    assert m.get("1") is None and m.get("2") is not None
    m.clear()
    assert m.entries == {}


def test_set_copies_chunk_ids(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    ids = ["1#0"]
    m.set("1", "v1", ids, "confluence")
    ids.append("1#1")
    assert m.get("1")["chunk_ids"] == ["1#0"]


def test_compute_diff_on_empty_manifest(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    diff = compute_diff(m, "confluence", {"a": "1", "b": "2"})
    assert sorted(diff.added) == ["a", "b"]
    assert diff.changed == [] and diff.removed == [] and diff.unchanged == []


def test_compute_diff_removed_is_sorted(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    for doc_id in ["c", "a", "b"]:
        m.set(doc_id, "1", [f"{doc_id}#0"], "confluence")
    assert compute_diff(m, "confluence", {}).removed == ["a", "b", "c"]


def test_compute_diff_ignores_other_sources(tmp_path):
    m = Manifest(str(tmp_path / "m.json"))
    m.set("openapi-doc", "1", ["openapi-doc#0"], "openapi")
    assert compute_diff(m, "confluence", {}).removed == []


def test_save_is_atomic_and_leaves_no_tmp_file(tmp_path):
    """리뷰 2 A-3: 임시 파일에 쓰고 os.replace 로 교체하므로 .tmp 가 남지 않는다."""
    path = str(tmp_path / "m.json")
    m = Manifest(path)
    m.set("1", "v1", ["1#0"], "confluence")
    m.save()
    m.set("2", "v2", ["2#0"], "openapi")
    m.save()

    assert not os.path.exists(f"{path}.tmp")
    assert sorted(os.listdir(tmp_path)) == ["m.json"]
    assert json.load(open(path, encoding="utf-8")).keys() == {"1", "2"}


def test_save_overwrites_previous_content_completely(tmp_path):
    """부분 덮어쓰기로 깨진 JSON 이 남지 않는지 — 긴 내용 → 짧은 내용."""
    path = str(tmp_path / "m.json")
    m = Manifest(path)
    for i in range(50):
        m.set(f"doc-{i}", "v1", [f"doc-{i}#0"], "confluence")
    m.save()
    m.clear()
    m.set("only", "v1", ["only#0"], "confluence")
    m.save()

    reloaded = Manifest(path)
    assert list(reloaded.entries) == ["only"]
    assert json.load(open(path, encoding="utf-8")) == reloaded.entries
