"""eval/run_eval.py 종료 코드·출력 형식 고정 (Ollama 없이 가짜 리트리버로 확인)."""
import textwrap

import pytest
from langchain_core.documents import Document

from eval import run_eval


class FakeRetriever:
    """질문 문자열 → 반환할 doc_id 목록 매핑."""

    def __init__(self, answers):
        self._answers = answers
        self.calls = []
        self.reload_calls = 0

    def reload(self):
        self.reload_calls += 1
        return 0

    def search(self, question, source="all", top_k=None):
        self.calls.append((question, source, top_k))
        return [Document(page_content="본문", metadata={"doc_id": doc_id, "chunk_id": f"{doc_id}#0"})
                for doc_id in self._answers.get(question, [])]


@pytest.fixture
def fake_env(monkeypatch):
    """VectorStoreRepository·RetrieverService 를 가짜로 바꿔 Ollama·Chroma 없이 main() 을 돌린다."""
    holder = {}

    def install(answers):
        retriever = FakeRetriever(answers)
        holder["retriever"] = retriever
        monkeypatch.setattr(run_eval.VectorStoreRepository, "from_profile",
                            classmethod(lambda cls, *a, **k: object()))
        monkeypatch.setattr(run_eval.RetrieverService, "from_profile",
                            classmethod(lambda cls, store: retriever))
        return retriever

    holder["install"] = install
    return holder


def _write_questions(tmp_path, body):
    path = tmp_path / "questions.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


_THREE_QUESTIONS = """
    questions:
      - question: 질문1
        source: openapi
        expected_doc_ids: ["a"]
      - question: 질문2
        source: openapi
        expected_doc_ids: ["b"]
      - question: 질문3
        source: confluence
        expected_doc_ids: ["c", "c2"]
    """


def _run(monkeypatch, path, *extra):
    monkeypatch.setattr("sys.argv", ["run_eval", "--active-profile=local", "--file", path, *extra])
    return run_eval.main()


def test_empty_file_exits_one(tmp_path, monkeypatch, capsys):
    path = _write_questions(tmp_path, "")
    assert _run(monkeypatch, path) == 1
    assert "평가 질문이 없습니다." in capsys.readouterr().out


def test_file_without_questions_key_exits_one(tmp_path, monkeypatch, capsys):
    path = _write_questions(tmp_path, "other: 1\n")
    assert _run(monkeypatch, path) == 1
    assert "평가 질문이 없습니다." in capsys.readouterr().out


def test_all_hits_exits_zero(tmp_path, monkeypatch, capsys, fake_env):
    fake_env["install"]({"질문1": ["a"], "질문2": ["b"], "질문3": ["c2"]})
    path = _write_questions(tmp_path, _THREE_QUESTIONS)

    assert _run(monkeypatch, path) == 0

    out = capsys.readouterr().out
    assert out.count("O ") == 3
    assert "X " not in out
    assert "hit@6 = 3/3 = 100% (기준 80%)" in out


def test_partial_hits_below_threshold_exits_one(tmp_path, monkeypatch, capsys, fake_env):
    fake_env["install"]({"질문1": ["a"], "질문2": ["다른문서"], "질문3": ["c"]})
    path = _write_questions(tmp_path, _THREE_QUESTIONS)

    assert _run(monkeypatch, path) == 1

    out = capsys.readouterr().out
    assert "O 질문1" in out
    assert "X 질문2" in out
    assert "기대: ['b']" in out
    assert "실제: ['다른문서']" in out
    assert "hit@6 = 2/3 = 67% (기준 80%)" in out


def test_k_option_is_passed_to_search(tmp_path, monkeypatch, fake_env):
    retriever = fake_env["install"]({"질문1": ["a"], "질문2": ["b"], "질문3": ["c"]})
    path = _write_questions(tmp_path, _THREE_QUESTIONS)

    _run(monkeypatch, path, "--k", "3")

    assert [c[2] for c in retriever.calls] == [3, 3, 3]
    assert [c[1] for c in retriever.calls] == ["openapi", "openapi", "confluence"]


def test_index_is_reloaded_before_search(tmp_path, monkeypatch, fake_env):
    retriever = fake_env["install"]({"질문1": ["a"], "질문2": ["b"], "질문3": ["c"]})
    _run(monkeypatch, _write_questions(tmp_path, _THREE_QUESTIONS))
    assert retriever.reload_calls == 1


def test_default_source_is_all_when_omitted(tmp_path, monkeypatch, fake_env):
    retriever = fake_env["install"]({"질문1": ["a"]})
    path = _write_questions(tmp_path, """
        questions:
          - question: 질문1
            expected_doc_ids: ["a"]
        """)
    assert _run(monkeypatch, path) == 0
    assert retriever.calls[0][1] == "all"


def test_threshold_is_eighty_percent():
    assert run_eval._PASS_RATE == 0.8


def test_shipped_question_file_is_valid():
    """동봉된 eval/questions.yaml 이 스키마를 지킨다."""
    import yaml

    import global_variable

    data = yaml.safe_load(open(f"{global_variable.PROJECT_ROOT_DIR}/eval/questions.yaml", encoding="utf-8"))
    questions = data["questions"]
    assert questions, "질문이 비어 있다"
    for q in questions:
        assert isinstance(q["question"], str) and q["question"].strip()
        assert q["source"] in ("all", "confluence", "openapi")
        assert isinstance(q["expected_doc_ids"], list) and q["expected_doc_ids"]
        assert all(isinstance(doc_id, str) for doc_id in q["expected_doc_ids"])


# --- 리뷰 4 조치 B-4 ---

def test_invalid_source_exits_one_with_guidance(tmp_path, monkeypatch, capsys, fake_env):
    """source 오타가 조용히 X 로 집계되지 않고 안내 후 종료 1."""
    fake_env["install"]({})
    path = _write_questions(tmp_path, """
        questions:
          - question: 오타질문
            source: opanapi
            expected_doc_ids: ["a"]
          - question: 정상질문
            source: openapi
            expected_doc_ids: ["b"]
        """)

    assert _run(monkeypatch, path) == 1

    out = capsys.readouterr().out
    assert "source 값이 올바르지 않습니다" in out
    assert "all/confluence/openapi" in out
    assert "오타질문" in out
    assert "정상질문" not in out  # 올바른 항목은 목록에 없다
    assert "hit@" not in out  # 검색 단계로 넘어가지 않는다


def test_invalid_source_is_checked_before_retriever_is_built(tmp_path, monkeypatch, capsys):
    """리트리버(=Ollama 임베딩)를 만들기 전에 검증한다 — Ollama 없이도 이 경로가 동작해야 한다."""
    def _explode(*args, **kwargs):
        raise AssertionError("source 검증 전에 리트리버를 만들면 안 된다")

    monkeypatch.setattr(run_eval.VectorStoreRepository, "from_profile", classmethod(_explode))
    path = _write_questions(tmp_path, """
        questions:
          - question: 오타질문
            source: jira
            expected_doc_ids: ["a"]
        """)
    assert _run(monkeypatch, path) == 1


def test_default_question_file_is_absolute_and_exists():
    """다른 작업 디렉터리에서 실행해도 기본 질문 파일을 찾는다."""
    import os

    source = open(run_eval.__file__, encoding="utf-8").read()
    assert 'default=f"{global_variable.PROJECT_ROOT_DIR}/eval/questions.yaml"' in source

    default_path = f"{run_eval.global_variable.PROJECT_ROOT_DIR}/eval/questions.yaml"
    assert os.path.isabs(default_path)
    assert os.path.isfile(default_path)


def test_help_lists_all_three_options(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_eval", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        run_eval.main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--active-profile" in out and "--k" in out and "--file" in out
    assert "프로파일" in out and "hit@k" in out and "질문 yaml" in out
