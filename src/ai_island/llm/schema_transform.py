"""Turn a Pydantic JSON schema into each provider's strict structured-output subset (C2).

The strict subsets share the same rules: every property is required, optional values become
nullable, objects forbid extra keys, references are inlined, and keywords the providers do not
accept are dropped. Local Pydantic validation of the reply stays mandatory, so dropping a bound
here never lets a bad value through.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic import BaseModel

PROVIDERS = ("anthropic", "openai", "google", "xai", "mistral")

# Keywords no strict subset accepts.
_ALWAYS_DROP = {
    "default",
    "title",
    "examples",
    "example",
    "pattern",
    "format",
    "$schema",
    "description",
    "const_description",
    "discriminator",
}
# Value bounds: kept for Google, dropped for the others.
_BOUNDS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "multipleOf",
}


def provider_schema(model_cls: type[BaseModel], provider: str) -> dict[str, Any]:
    """The provider's strict-subset JSON schema for ``model_cls``."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider '{provider}'")
    raw = model_cls.model_json_schema()
    defs = raw.get("$defs", {})
    keep_bounds = provider == "google"
    return _walk(raw, defs, keep_bounds, top=True, anthropic=provider == "anthropic")


# Google's schema subset has minimum/maximum but not these (pydantic still enforces them locally).
_GOOGLE_DROP = {"exclusiveMinimum", "exclusiveMaximum", "multipleOf"}

INSTRUCTION_HEAD = "Reply with only one JSON object, no other text, matching this JSON schema:"


def schema_instruction(model_cls: type[BaseModel], provider: str) -> str:
    """The prompt-mode instruction block: the head line plus the provider's schema as JSON."""
    return INSTRUCTION_HEAD + "\n" + json.dumps(provider_schema(model_cls, provider))


def extract_json(text: str) -> str:
    """The JSON object inside a prompt-mode reply: unfence, then first '{' to last '}'.

    Text that has no usable object is returned unchanged so the broker records a format error.
    """
    body = text.strip()
    if body.startswith("```"):
        lines = body.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines[1:]).strip()
    try:
        json.loads(body)
        return body
    except ValueError:
        pass
    start, end = body.find("{"), body.rfind("}")
    if 0 <= start < end:
        candidate = body[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except ValueError:
            pass
    return text


def _is_map(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and node.get("type") == "object"
        and isinstance(node.get("additionalProperties"), dict)
        and "properties" not in node
    )


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        extra = {k: v for k, v in node.items() if k != "$ref"}
        node = {**copy.deepcopy(defs[name]), **extra}
    return node


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _walk(
    node: Any,
    defs: dict[str, Any],
    keep_bounds: bool,
    top: bool = False,
    anthropic: bool = False,
) -> Any:
    if not isinstance(node, dict):
        return node
    node = _resolve(node, defs)
    if _is_map(node):
        # strict modes have no open maps: send a closed list of {key, value} entries
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": _walk(
                        node["additionalProperties"], defs, keep_bounds, False, anthropic
                    ),
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        }
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "$defs" or key in _ALWAYS_DROP:
            continue
        if key in _BOUNDS and not keep_bounds:
            continue
        if key in _GOOGLE_DROP:
            if key == "exclusiveMinimum" and node.get("type") == "integer" and value == 0:
                out["minimum"] = max(1, node.get("minimum", 1))
            continue
        if key == "properties":
            continue
        if key in ("anyOf", "oneOf", "allOf"):
            out["anyOf" if key == "oneOf" else key] = [
                _walk(item, defs, keep_bounds, False, anthropic) for item in value
            ]
        elif key == "items":
            out[key] = _walk(value, defs, keep_bounds, False, anthropic)
        elif key == "prefixItems":
            out[key] = [_walk(item, defs, keep_bounds, False, anthropic) for item in value]
        elif key == "additionalProperties":
            continue
        else:
            out[key] = value
    props = node.get("properties")
    if props is not None:
        required = set(node.get("required", []))
        new_props: dict[str, Any] = {}
        wire_required: list[str] = []
        for name, sub in props.items():
            walked = _walk(sub, defs, keep_bounds, False, anthropic)
            if name in required:
                wire_required.append(name)
            elif anthropic:
                # optional stays a non-required property (no anyOf union); missing parses as None
                walked = _strip_null(walked)
            else:
                wire_required.append(name)
                if not _accepts_null(walked):
                    walked = _nullable(walked)
            new_props[name] = walked
        out["properties"] = new_props
        out["required"] = wire_required
        out["additionalProperties"] = False
    elif out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def _strip_null(schema: dict[str, Any]) -> dict[str, Any]:
    branches = schema.get("anyOf")
    if not branches:
        return schema
    rest = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
    if len(rest) == len(branches):
        return schema
    if len(rest) == 1:
        return rest[0]
    return {**{k: v for k, v in schema.items() if k != "anyOf"}, "anyOf": rest}


def _accepts_null(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    return any(isinstance(s, dict) and s.get("type") == "null" for s in schema.get("anyOf", []))


def from_wire(data: Any, model_cls: type[BaseModel]) -> Any:
    """Turn the wire form back into what ``model_cls`` validates.

    Every map position (a ``dict[str, X]`` field) arrives as a list of ``{key, value}``
    entries; it becomes a dict. Plain dicts pass through (fake adapter, old stored replies).
    A repeated key or a malformed entry raises ValueError (a format error for the broker).
    """
    raw = model_cls.model_json_schema()
    return _conv(data, raw, raw.get("$defs", {}))


def _entries_to_dict(data: list[Any], value_node: Any, defs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("map entries must be {key, value}")
        if set(item) == {"key", "value"}:
            k, v = item["key"], item["value"]
        elif set(item) == {"value_id", "delta"}:  # legacy reflection form
            k, v = item["value_id"], item["delta"]
        else:
            raise ValueError("map entries must be {key, value}")
        if not isinstance(k, str):
            raise ValueError("map entry key must be text")
        if k in out:
            raise ValueError(f"map repeats the key '{k}'")
        out[k] = _conv(v, value_node, defs)
    return out


def _conv(data: Any, node: Any, defs: dict[str, Any]) -> Any:
    if not isinstance(node, dict) or data is None:
        return data
    node = _resolve(node, defs)
    if "anyOf" in node:
        branches = [
            b for b in node["anyOf"] if not (isinstance(b, dict) and b.get("type") == "null")
        ]
        if data == [] and any(_is_map(_resolve(b, defs)) for b in branches):
            return None
        last: ValueError | None = None
        for branch in branches:
            try:
                return _conv(data, branch, defs)
            except ValueError as exc:
                last = exc
        if last is not None:
            raise last
        return data
    if _is_map(node):
        value_node = node["additionalProperties"]
        if isinstance(data, list):
            return _entries_to_dict(data, value_node, defs)
        if isinstance(data, dict):
            return {k: _conv(v, value_node, defs) for k, v in data.items()}
        return data
    if isinstance(data, dict) and "properties" in node:
        return {k: _conv(v, node["properties"].get(k), defs) for k, v in data.items()}
    if isinstance(data, list) and "items" in node:
        return [_conv(v, node["items"], defs) for v in data]
    return data
