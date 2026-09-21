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
