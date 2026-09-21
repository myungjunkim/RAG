import json
import logging
from pathlib import Path

import pytest

from src.service.openapi_document_service import (
    OpenApiRefError,
    OpenApiSource,
    build_documents,
    render_endpoint,
    render_schema,
    resolve_ref,
)

SPEC = json.loads((Path(__file__).parent / "fixtures" / "openapi_sample.json").read_text(encoding="utf-8"))
SOURCE = OpenApiSource(name="message-api", spec_url="https://x/openapi.json", docs_url="https://x/docs")


def test_resolve_ref():
    schema = resolve_ref(SPEC, "#/components/schemas/MessageResponse")
    assert schema["properties"]["seq"]["type"] == "integer"


def test_render_endpoint_contains_method_path_and_inlined_request_schema():
    op = SPEC["paths"]["/v1/messages/message"]["post"]
    text = render_endpoint(SPEC, SOURCE, "/v1/messages/message", "post", op)
    assert text.startswith("## POST /v1/messages/message — Add Message")
    assert "서비스: Message Management API (message-api)" in text
    assert "태그: message 등록" in text
    assert "메시지를 등록한다." in text
    assert "service_key" in text and "(필수)" in text  # 요청 스키마가 인라인 됨
    assert "### Responses" in text and "200" in text and "MessageResponse" in text


def test_render_endpoint_parameters_table():
    op = SPEC["paths"]["/v1/messages/{service_key}/{user_key}"]["get"]
    text = render_endpoint(SPEC, SOURCE, "/v1/messages/{service_key}/{user_key}", "get", op)
    assert "| service_key | path | string | 예 | 서비스 키 |" in text
    assert "| last_session_only | query | boolean | 아니오 |" in text


def test_circular_ref_is_cut_by_name():
    text = render_schema(SPEC, "MessagePostRequest", SPEC["components"]["schemas"]["MessagePostRequest"])
    assert text.startswith("## Schema MessagePostRequest")
    # children → MessagePostRequest 순환: 이름만 표기되고 무한 재귀하지 않는다
    assert "array<MessagePostRequest>" in text


def test_build_documents_metadata_and_counts():
    docs = build_documents(SPEC, SOURCE)
    ids = {d.metadata["doc_id"] for d in docs}
    assert ids == {
        "message-api:POST:/v1/messages/message",
        "message-api:GET:/v1/messages/{service_key}/{user_key}",
        "message-api:schema:MessagePostRequest",
        "message-api:schema:MessageResponse",
    }
    post = next(d for d in docs if d.metadata["doc_id"] == "message-api:POST:/v1/messages/message")
    assert post.metadata["source"] == "openapi"
    assert post.metadata["method"] == "POST"
    assert post.metadata["path"] == "/v1/messages/message"
    assert post.metadata["tags"] == "message 등록"
    assert post.metadata["url"] == "https://x/docs"
    assert post.metadata["title"] == "POST /v1/messages/message"
    schema_doc = next(d for d in docs if d.metadata["doc_id"] == "message-api:schema:MessageResponse")
    assert schema_doc.metadata["title"] == "Schema MessageResponse"
    assert schema_doc.metadata["method"] == "" and schema_doc.metadata["path"] == ""


def test_broken_ref_skips_only_that_item():
    spec = json.loads(json.dumps(SPEC))
    spec["paths"]["/broken"] = {"get": {"summary": "b", "responses": {
        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Nope"}}}}}}}
    docs = build_documents(spec, SOURCE)
    assert not any(d.metadata["doc_id"].endswith(":/broken") for d in docs)
    assert len(docs) == 4


# --- Validator 추가 검증 (명세 "검증 전략" 중 계획서 테스트가 덮지 않는 항목) ---

def _spec(schemas=None, paths=None, parameters=None):
    spec = {"info": {"title": "T"}}
    if paths is not None:
        spec["paths"] = paths
    components = {}
    if schemas is not None:
        components["schemas"] = schemas
    if parameters is not None:
        components["parameters"] = parameters
    if components:
        spec["components"] = components
    return spec


def test_resolve_ref_rejects_external_file_ref():
    with pytest.raises(OpenApiRefError):
        resolve_ref(SPEC, "other.yaml#/components/schemas/X")


def test_resolve_ref_raises_on_missing_target():
    with pytest.raises(OpenApiRefError):
        resolve_ref(SPEC, "#/components/schemas/Nope")


def test_resolve_ref_handles_json_pointer_escapes():
    spec = _spec(schemas={"a/b": {"type": "object"}, "c~d": {"type": "string"}})
    assert resolve_ref(spec, "#/components/schemas/a~1b") == {"type": "object"}
    assert resolve_ref(spec, "#/components/schemas/c~0d") == {"type": "string"}


def test_mutual_circular_ref_terminates():
    """A→B→A 상호 순환에서도 예외·무한 재귀 없이 렌더링된다."""
    spec = _spec(schemas={
        "A": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/B"}}},
        "B": {"type": "object", "properties": {"a": {"$ref": "#/components/schemas/A"}}},
    })
    text = render_schema(spec, "A", spec["components"]["schemas"]["A"])
    assert text.startswith("## Schema A")
    assert "- b (B)" in text
    docs = build_documents(spec, SOURCE)
    assert {d.metadata["doc_id"] for d in docs} == {"message-api:schema:A", "message-api:schema:B"}


def test_nested_objects_expand_only_three_levels():
    spec = _spec(schemas={"L1": {"type": "object", "properties": {
        "a1": {"type": "object", "properties": {
            "b2": {"type": "object", "properties": {
                "c3": {"type": "object", "properties": {
                    "d4": {"type": "string"}}}}}}}}}})
    text = render_schema(spec, "L1", spec["components"]["schemas"]["L1"])
    assert "- a1 (object)" in text
    assert "  - b2 (object)" in text
    assert "    - c3 (object)" in text
    assert "d4" not in text  # _MAX_DEPTH=3 초과는 펼치지 않는다


def test_broken_ref_in_schema_skips_only_that_schema(caplog):
    spec = _spec(schemas={
        "Good": {"type": "object", "properties": {"x": {"type": "string"}}},
        "Bad": {"type": "object", "properties": {"y": {"$ref": "#/components/schemas/Missing"}}},
    })
    with caplog.at_level(logging.WARNING, logger="src.service.openapi_document_service"):
        docs = build_documents(spec, SOURCE)
    assert {d.metadata["doc_id"] for d in docs} == {"message-api:schema:Good"}
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_broken_ref_in_endpoint_logs_warning(caplog):
    spec = _spec(paths={"/broken": {"get": {"responses": {"200": {"content": {
        "application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}}}}}}})
    with caplog.at_level(logging.WARNING, logger="src.service.openapi_document_service"):
        docs = build_documents(spec, SOURCE)
    assert docs == []
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_all_metadata_values_are_str():
    docs = build_documents(SPEC, SOURCE)
    assert docs
    for doc in docs:
        assert set(doc.metadata) == {"source", "doc_id", "service", "method", "path", "tags", "url", "title"}
        assert all(isinstance(value, str) for value in doc.metadata.values())
    schema_doc = next(d for d in docs if d.metadata["doc_id"].startswith("message-api:schema:"))
    assert schema_doc.metadata["method"] == ""
    assert schema_doc.metadata["path"] == ""
    assert schema_doc.metadata["tags"] == ""
    assert schema_doc.metadata["service"] == "message-api"


def test_ref_parameter_is_resolved_into_table():
    spec = _spec(parameters={"Page": {"name": "page", "in": "query", "required": False,
                                      "schema": {"type": "integer"}, "description": "페이지"}})
    text = render_endpoint(spec, SOURCE, "/list", "get", {"parameters": [{"$ref": "#/components/parameters/Page"}]})
    assert "| page | query | integer | 아니오 | 페이지 |" in text


def test_request_body_falls_back_to_first_media_type():
    operation = {"requestBody": {"content": {"multipart/form-data": {"schema": {
        "type": "object", "properties": {"file": {"type": "string"}}}}}}}
    text = render_endpoint({}, SOURCE, "/upload", "post", operation)
    assert "### Request Body (object)" in text
    assert "- file (string)" in text


def test_request_body_prefers_application_json():
    operation = {"requestBody": {"content": {
        "multipart/form-data": {"schema": {"type": "object", "properties": {"form_only": {"type": "string"}}}},
        "application/json": {"schema": {"type": "object", "properties": {"json_field": {"type": "string"}}}},
    }}}
    text = render_endpoint({}, SOURCE, "/upload", "post", operation)
    assert "- json_field (string)" in text
    assert "form_only" not in text


def test_endpoint_without_summary_has_no_dangling_dash():
    text = render_endpoint({}, SOURCE, "/x", "get", {})
    assert text.startswith("## GET /x")
    assert text.splitlines()[0] == "## GET /x"
    assert "—" not in text.splitlines()[0]


def test_empty_spec_returns_no_documents():
    assert build_documents({}, SOURCE) == []
    assert build_documents({"paths": {}, "components": {}}, SOURCE) == []
    assert build_documents({"paths": None, "components": None}, SOURCE) == []


def test_all_http_methods_are_rendered_in_declared_order():
    declared = ["options", "head", "delete", "patch", "put", "post", "get"]
    spec = _spec(paths={"/m": {m: {"summary": m} for m in declared}})
    methods = [d.metadata["method"] for d in build_documents(spec, SOURCE)]
    assert methods == ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def test_non_http_method_keys_are_ignored():
    spec = _spec(paths={"/t": {"trace": {"summary": "t"}, "parameters": [], "summary": "공통"}})
    assert build_documents(spec, SOURCE) == []


def test_type_labels_for_anyof_array_and_bare_object():
    spec = _spec(schemas={"S": {"type": "object", "properties": {
        "nullable": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "either": {"oneOf": [{"type": "string"}, {"$ref": "#/components/schemas/Other"}]},
        "items": {"type": "array", "items": {"$ref": "#/components/schemas/Other"}},
        "bare": {"properties": {}},
        "unknown": {},
    }}, "Other": {"type": "string"}})
    text = render_schema(spec, "S", spec["components"]["schemas"]["S"])
    assert "- nullable (string | null)" in text
    assert "- either (string | Other)" in text
    assert "- items (array<Other>)" in text
    assert "- bare (object)" in text
    assert "- unknown (any)" in text


def test_successful_response_fields_are_indented_and_non_2xx_not_expanded():
    spec = _spec(schemas={"R": {"type": "object", "properties": {"ok": {"type": "boolean"}}}})
    operation = {"responses": {
        "200": {"description": "성공", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/R"}}}},
        "422": {"description": "오류", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/R"}}}},
    }}
    text = render_endpoint(spec, SOURCE, "/r", "get", operation)
    assert "- 200: 성공 → R" in text
    assert "  - ok (boolean)" in text
    assert "- 422: 오류 → R" in text
    # 비 2xx 응답은 필드를 펼치지 않는다 → 들여쓴 필드 줄은 1개뿐
    assert text.count("  - ok (boolean)") == 1


def test_required_marker_and_description_in_field_lines():
    spec = _spec(schemas={"S": {"type": "object", "required": ["a"], "properties": {
        "a": {"type": "string", "description": "필수 값"},
        "b": {"type": "integer"},
    }}})
    text = render_schema(spec, "S", spec["components"]["schemas"]["S"])
    assert "- a (string) (필수): 필수 값" in text
    assert "- b (integer)" in text


def test_service_line_falls_back_to_source_name_without_info_title():
    text = render_endpoint({}, SOURCE, "/x", "get", {})
    assert "서비스: message-api (message-api)" in text


def test_nested_ref_fields_are_inlined():
    """명세 '필드 목록': $ref 이름이 seen에 없고 depth <= _MAX_DEPTH 면 펼쳐야 한다.

    MessageResponse.request → MessagePostRequest 는 seen에 없고 depth 2 이므로
    하위 필드(service_key 등)가 인라인돼야 한다.
    """
    text = render_schema(SPEC, "MessageResponse", SPEC["components"]["schemas"]["MessageResponse"])
    assert "- request (MessagePostRequest)" in text
    assert "  - service_key (string) (필수): 서비스 키" in text


def test_ref_chain_expansion_stops_at_max_depth():
    """$ref 체인도 깊이 3까지만 펼친다 (회차 1 수정으로 체인 전개가 가능해진 뒤의 경계)."""
    spec = _spec(schemas={
        "C1": {"type": "object", "properties": {"n": {"$ref": "#/components/schemas/C2"}}},
        "C2": {"type": "object", "properties": {"n": {"$ref": "#/components/schemas/C3"}}},
        "C3": {"type": "object", "properties": {"n": {"$ref": "#/components/schemas/C4"}}},
        "C4": {"type": "object", "properties": {"leaf": {"type": "string"}}},
    })
    text = render_schema(spec, "C1", spec["components"]["schemas"]["C1"])
    assert "- n (C2)" in text
    assert "  - n (C3)" in text
    assert "    - n (C4)" in text
    assert "leaf" not in text  # depth 3 초과는 펼치지 않는다


def test_response_ref_is_resolved(caplog):
    """responses 항목이 #/components/responses/... $ref 여도 설명·스키마가 렌더링된다 (리뷰 1 항목 11)."""
    spec = _spec(schemas={
        "Res": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        "Err": {"type": "object", "properties": {"code": {"type": "string"}}},
    })
    spec["components"]["responses"] = {
        "OK": {"description": "성공", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Res"}}}},
        "NotFound": {"description": "없음", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Err"}}}},
    }
    operation = {"responses": {"200": {"$ref": "#/components/responses/OK"},
                               "404": {"$ref": "#/components/responses/NotFound"}}}
    text = render_endpoint(spec, SOURCE, "/r", "get", operation)
    assert "- 200: 성공 → Res" in text
    assert "  - ok (boolean)" in text
    assert "- 404: 없음 → Err" in text

    broken = _spec(paths={"/b": {"get": {"responses": {"200": {"$ref": "#/components/responses/Nope"}}}}})
    with caplog.at_level(logging.WARNING, logger="src.service.openapi_document_service"):
        assert build_documents(broken, SOURCE) == []
    assert any(record.levelno == logging.WARNING for record in caplog.records)
