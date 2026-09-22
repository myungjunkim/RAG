"""정적 웹 UI(resources/static/index.html) 계약 검증.

브라우저 없이 확인 가능한 항목만 다룬다. 실제 렌더링·클릭 동작은 사용자 육안 확인 영역이다.
"""
import re

import global_variable
from src.dto.ask_dto import AskRequest, SourceRef

INDEX_PATH = f"{global_variable.PROJECT_RESOURCE_DIR}/static/index.html"


def _html():
    return open(INDEX_PATH, encoding="utf-8").read()


def _script() -> str:
    """<script> 블록만 추출(CSS·마크업 오탐 방지)."""
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", _html(), re.S))


def test_basic_document_structure():
    html = _html()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert 'lang="ko"' in html
    assert 'charset="utf-8"' in html
    assert 'name="viewport"' in html


def test_no_external_resources():
    """외부 CDN·원격 리소스를 쓰지 않는다(사내 문서가 로컬 서버 밖으로 나가지 않도록)."""
    html = _html()
    assert not re.search(r"<script[^>]+src\s*=\s*[\"']https?://", html, re.I)
    assert not re.search(r"<link[^>]+href\s*=\s*[\"']https?://", html, re.I)
    assert not re.search(r"@import\s+url\(\s*[\"']?https?://", html, re.I)


def test_fetch_targets_are_relative_paths():
    calls = re.findall(r"fetch\(\s*[`'\"]([^`'\"]+)", _script())
    assert calls, "fetch 호출을 찾지 못했다"
    assert all(url.startswith("/") for url in calls), calls
    assert "/check" in calls
    assert "/v1/ask/stream" in calls


def test_sse_event_names_match_server_contract():
    """서버가 보내는 이벤트 이름만 다루고, 알 수 없는 이름을 기대하지 않는다."""
    script = _script()
    handled = set(re.findall(r"event\s*===\s*'([a-z]+)'", script))
    server_events = {"token", "sources", "done", "error"}
    assert handled <= server_events, f"서버 계약에 없는 이벤트 처리: {handled - server_events}"
    assert {"token", "sources", "error"} <= handled


def test_input_is_re_enabled_regardless_of_outcome():
    """done 이벤트를 별도 분기로 다루지 않더라도 finally 에서 입력 잠금이 해제된다."""
    script = _script()
    assert "finally" in script
    finally_block = script.split("finally", 1)[1]
    assert "disabled = false" in finally_block


def test_source_options_match_server_literal():
    """select 의 값이 AskRequest.source Literal 과 정확히 일치한다."""
    options = set(re.findall(r'<option value="([a-z]+)"', _html()))
    literal_values = set(AskRequest.model_fields["source"].annotation.__args__)
    assert options == literal_values


def test_source_card_uses_all_sourceref_fields():
    script = _script()
    for field in SourceRef.model_fields:
        assert re.search(rf"\bs\.{field}\b", script), f"소스 카드가 {field} 를 쓰지 않는다"


def test_server_data_is_not_inserted_via_innerhtml():
    """XSS 회피: 서버 데이터는 textContent 로만 삽입한다."""
    script = _script()
    assert "innerHTML" not in script
    assert "outerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "document.write" not in script
    assert "textContent" in script


def test_source_links_open_in_new_tab_safely():
    script = _script()
    assert "target = '_blank'" in script or 'target="_blank"' in script
    assert "rel = 'noopener'" in script or 'rel="noopener"' in script


def test_http_error_detail_handles_both_string_and_array():
    """422 의 detail 은 배열, 503/504 는 문자열 (리뷰 3 인계 항목)."""
    script = _script()
    assert "Array.isArray(detail)" in script
    assert re.search(r"detail\.map\(\s*d\s*=>\s*d\.msg\s*\)", script)


def test_stream_parsing_keeps_incomplete_frame_in_buffer():
    script = _script()
    assert "indexOf('\\n\\n')" in script or 'indexOf("\\n\\n")' in script
    assert "buffer" in script
    assert "getReader()" in script
    assert "TextDecoder" in script


def test_answer_preserves_newlines_via_pre_wrap():
    assert "pre-wrap" in _html()


def test_root_endpoint_serves_the_ui():
    """정적 마운트·라우팅이 실제로 이 파일을 돌려준다. (lifespan 을 열지 않아 인덱스 구성은 일어나지 않는다)"""
    from fastapi.testclient import TestClient

    import main

    res = TestClient(main.app).get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "<form" in body
    assert "<button" in body
    assert "fetch(" in body


def test_fetch_failure_shows_error_message():
    """서버 다운 등으로 fetch 자체가 실패하면 catch 에서 오류 메시지를 표시한다."""
    script = _script()
    assert re.search(r"catch\s*\(\s*err\s*\)", script)
    assert "요청 실패" in script
    assert "err" in script  # .err 클래스로 빨간 표시


def test_health_failure_is_handled():
    script = _script()
    assert "상태 확인 실패" in script


# --- Task 14: 인용 카드 강조 + 나머지 접기 ---

def _function_body(name: str) -> str:
    """스크립트에서 함수 본문만 잘라낸다(다른 함수의 코드에 오탐하지 않도록)."""
    script = _script()
    start = script.index(f"function {name}(")
    depth, i = 0, script.index("{", start)
    for j in range(i, len(script)):
        if script[j] == "{":
            depth += 1
        elif script[j] == "}":
            depth -= 1
            if depth == 0:
                return script[start:j + 1]
    raise AssertionError(f"{name} 본문을 찾지 못했다")


def test_citation_regex_is_applied_to_answer_text():
    """답변 본문에서 [n] 을 뽑아 인용 집합을 만든다."""
    body = _function_body("renderSources")
    assert re.search(r"/\\\[\(\\d\+\)\\\]/g", body), "인용 정규식 /\\[(\\d+)\\]/g 을 찾지 못했다"
    assert "matchAll" in body
    # 인용 파싱 대상은 답변 텍스트여야 한다 (카드 DOM 이 아니라)
    assert re.search(r"renderSources\(\s*answerEl\s*,\s*data\s*,\s*answerEl\.textContent\s*\)", _script())


def test_sources_are_split_into_cited_and_rest():
    body = _function_body("renderSources")
    assert re.search(r"const\s+cited\s*=\s*sources\.filter", body)
    assert re.search(r"const\s+rest\s*=\s*sources\.filter", body)
    assert "citedSet.has(s.index)" in body  # index 기준 판정


def test_fallback_renders_everything_when_no_citation():
    """인용을 하나도 못 찾으면 접지 않고 전부 펼친다(근거 손실 방지)."""
    body = _function_body("renderSources")
    assert re.search(r"if\s*\(\s*cited\.length\s*===\s*0\s*\)", body)
    fallback = body[body.index("cited.length === 0"):]
    fallback = fallback[:fallback.index("container.appendChild(buildCardGrid(cited")]
    assert "buildCardGrid(sources" in fallback  # 전체를 렌더
    assert "createElement('details')" not in fallback  # 접힘 영역을 만들지 않는다


def test_details_is_created_only_when_rest_exists():
    body = _function_body("renderSources")
    assert re.search(r"if\s*\(\s*rest\.length\s*\)", body)
    assert "createElement('details')" in body
    assert "createElement('summary')" in body
    assert re.search(r"기타 참고 \$\{rest\.length\}건", body)  # 정적 문자열 + 숫자만


def test_card_number_is_not_renumbered():
    """카드 라벨은 s.index 그대로 — 답변의 [n] 과 대응이 깨지면 안 된다."""
    body = _function_body("buildCard")
    assert re.search(r"\$\{s\.index\}", body), "카드 라벨이 s.index 를 쓰지 않는다"
    # 순번 재부여 패턴이 없어야 한다
    assert not re.search(r"\bi\s*\+\s*1\b", body)
    assert not re.search(r"\bindex\s*\+\s*1\b", body)
    assert not re.search(r"forEach\(\s*\(\s*\w+\s*,\s*\w+\s*\)", body)


def test_cited_cards_get_highlight_class():
    card_body = _function_body("buildCard")
    assert re.search(r"cited\s*\?\s*'src cited'\s*:\s*'src'", card_body)
    assert ".src.cited" in _html()  # 강조 스타일 존재
    grid = _function_body("buildCardGrid")
    assert "buildCard(s, cited)" in grid


def test_cited_grid_is_rendered_before_details():
    """강조 카드가 먼저, 접힘 영역이 나중에 붙는다."""
    body = _function_body("renderSources")
    assert body.index("buildCardGrid(cited, true)") < body.index("createElement('details')")


def test_empty_sources_render_nothing():
    body = _function_body("renderSources")
    assert re.search(r"if\s*\(\s*!sources\.length\s*\)\s*return", body)


def test_task14_keeps_dom_safety_rules():
    """새 코드에도 XSS 규칙이 유지된다(카드·details 모두 createElement/textContent)."""
    for name in ("buildCard", "buildCardGrid", "renderSources"):
        body = _function_body(name)
        assert "innerHTML" not in body
        assert "insertAdjacentHTML" not in body
    assert _function_body("buildCard").count("textContent") >= 3  # 링크·배지·스니펫
