"""OpenAPI 3.x 스펙을 endpoint 단위·schema 단위 Markdown Document 로 렌더링한다."""
from dataclasses import dataclass

from langchain_core.documents import Document

from src.library.global_logger import GlobalLogger

logger = GlobalLogger.get_logger(__name__)

SOURCE_OPENAPI = "openapi"
_MAX_DEPTH = 3
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


@dataclass(frozen=True)
class OpenApiSource:
    name: str
    spec_url: str
    docs_url: str


class OpenApiRefError(Exception):
    pass


def resolve_ref(spec: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise OpenApiRefError(f"외부 $ref 는 지원하지 않습니다: {ref}")
    node = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise OpenApiRefError(f"$ref 대상을 찾을 수 없습니다: {ref}")
        node = node[part]
    return node


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _type_label(spec: dict, schema: dict, seen: frozenset) -> str:
    """스키마의 한 줄 타입 표기. $ref 는 이름, 배열은 array<...>."""
    if "$ref" in schema:
        return _ref_name(schema["$ref"])
    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf")
        return " | ".join(_type_label(spec, o, seen) for o in options)
    if schema.get("type") == "array":
        return f"array<{_type_label(spec, schema.get('items', {}), seen)}>"
    return schema.get("type", "object" if "properties" in schema else "any")


def _schema_lines(spec: dict, schema: dict, depth: int, seen: frozenset, indent: str = "") -> list[str]:
    """object 스키마의 필드를 '- name (type, 필수): desc' 줄로 펼친다. 깊이 제한·순환은 이름만."""
    if "$ref" in schema:
        name = _ref_name(schema["$ref"])
        if name in seen or depth > _MAX_DEPTH:
            return [f"{indent}- ({name})"]
        return _schema_lines(spec, resolve_ref(spec, schema["$ref"]), depth, seen | {name}, indent)
    lines = []
    required = set(schema.get("required", []))
    for field, sub in (schema.get("properties") or {}).items():
        label = _type_label(spec, sub, seen)
        req = " (필수)" if field in required else ""
        desc = f": {sub.get('description')}" if sub.get("description") else ""
        lines.append(f"{indent}- {field} ({label}){req}{desc}")
        # 중첩 object / object 배열은 한 단계 더 펼친다
        nested = sub.get("items", sub) if sub.get("type") == "array" else sub
        if depth < _MAX_DEPTH and ("$ref" in nested or nested.get("properties")):
            name = _ref_name(nested["$ref"]) if "$ref" in nested else None
            if name and name in seen:
                continue
            lines.extend(_schema_lines(spec, nested, depth + 1, seen, indent + "  "))
    return lines


def _content_schema(content: dict | None) -> dict | None:
    if not content:
        return None
    for media in ("application/json", *content.keys()):
        if media in content and "schema" in content[media]:
            return content[media]["schema"]
    return None


def render_endpoint(spec: dict, source: OpenApiSource, path: str, method: str, operation: dict) -> str:
    method_u = method.upper()
    title = spec.get("info", {}).get("title", source.name)
    lines = [f"## {method_u} {path} — {operation.get('summary', '')}".rstrip(" —"),
             f"서비스: {title} ({source.name})"]
    if operation.get("tags"):
        lines.append(f"태그: {', '.join(operation['tags'])}")
    if operation.get("description"):
        lines += ["", operation["description"].strip()]

    params = operation.get("parameters", [])
    if params:
        lines += ["", "### Parameters", "| name | in | type | required | description |", "|---|---|---|---|---|"]
        for p in params:
            p = resolve_ref(spec, p["$ref"]) if "$ref" in p else p
            ptype = _type_label(spec, p.get("schema", {}), frozenset())
            lines.append(f"| {p['name']} | {p.get('in', '')} | {ptype} | {'예' if p.get('required') else '아니오'} | {p.get('description', '')} |")

    body_schema = _content_schema((operation.get("requestBody") or {}).get("content"))
    if body_schema is not None:
        lines += ["", f"### Request Body ({_type_label(spec, body_schema, frozenset())})"]
        lines += _schema_lines(spec, body_schema, 1, frozenset())

    responses = operation.get("responses") or {}
    if responses:
        lines += ["", "### Responses"]
        for status, resp in responses.items():
            resp = resolve_ref(spec, resp["$ref"]) if "$ref" in resp else resp
            schema = _content_schema(resp.get("content"))
            label = f" → {_type_label(spec, schema, frozenset())}" if schema is not None else ""
            lines.append(f"- {status}: {resp.get('description', '')}{label}")
            if schema is not None and str(status).startswith("2"):
                lines += _schema_lines(spec, schema, 1, frozenset(), indent="  ")
    return "\n".join(lines)


def render_schema(spec: dict, name: str, schema: dict) -> str:
    lines = [f"## Schema {name}"]
    if schema.get("description"):
        lines += ["", schema["description"].strip()]
    lines += ["", f"타입: {_type_label(spec, schema, frozenset({name}))}", ""]
    lines += _schema_lines(spec, schema, 1, frozenset({name}))
    return "\n".join(lines)


def build_documents(spec: dict, source: OpenApiSource) -> list[Document]:
    docs: list[Document] = []
    for path, item in (spec.get("paths") or {}).items():
        for method in _HTTP_METHODS:
            operation = item.get(method)
            if not operation:
                continue
            try:
                text = render_endpoint(spec, source, path, method, operation)
            except OpenApiRefError as e:
                logger.warning("endpoint 렌더링 건너뜀 %s %s: %s", method.upper(), path, e)
                continue
            docs.append(Document(page_content=text, metadata={
                "source": SOURCE_OPENAPI,
                "doc_id": f"{source.name}:{method.upper()}:{path}",
                "service": source.name,
                "method": method.upper(),
                "path": path,
                "tags": ", ".join(operation.get("tags", [])),
                "url": source.docs_url,
                "title": f"{method.upper()} {path}",
            }))
    for name, schema in ((spec.get("components") or {}).get("schemas") or {}).items():
        try:
            text = render_schema(spec, name, schema)
        except OpenApiRefError as e:
            logger.warning("schema 렌더링 건너뜀 %s: %s", name, e)
            continue
        docs.append(Document(page_content=text, metadata={
            "source": SOURCE_OPENAPI,
            "doc_id": f"{source.name}:schema:{name}",
            "service": source.name,
            "method": "",
            "path": "",
            "tags": "",
            "url": source.docs_url,
            "title": f"Schema {name}",
        }))
    return docs
