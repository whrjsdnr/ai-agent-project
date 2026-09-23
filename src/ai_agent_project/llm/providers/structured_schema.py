"""OpenAI Structured Outputs schema normalization at the provider boundary."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def openai_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a Pydantic schema compatible with OpenAI strict Structured Outputs.

    OpenAI requires every declared object property to appear in ``required`` and
    requires ``additionalProperties`` to be false. Pydantic already represents
    nullable domain fields (for example ``str | None``) with a null branch; this
    helper preserves that representation rather than changing domain semantics.
    """
    schema = deepcopy(model.model_json_schema())
    _normalize_object_schemas(schema)
    _validate_object_schema_invariants(schema)
    return schema


def _normalize_object_schemas(value: object) -> None:
    """Recursively normalize objects, including schemas held in ``$defs``."""
    if isinstance(value, list):
        for item in value:
            _normalize_object_schemas(item)
        return
    if not isinstance(value, dict):
        return

    properties = value.get("properties")
    if isinstance(properties, dict):
        value["required"] = list(properties)
        value["additionalProperties"] = False

    # Walk each schema-bearing location independently. In particular, definitions
    # are object nodes in their own right; their properties must never affect a
    # parent object's ``required`` list.
    for child in properties.values() if isinstance(properties, dict) else ():
        _normalize_object_schemas(child)
    for key in ("$defs", "definitions"):
        definitions = value.get(key)
        if isinstance(definitions, dict):
            for child in definitions.values():
                _normalize_object_schemas(child)
    for key in ("items", "additionalProperties", "not"):
        child = value.get(key)
        if isinstance(child, dict | list):
            _normalize_object_schemas(child)
    for key in ("anyOf", "oneOf", "allOf"):
        child = value.get(key)
        if isinstance(child, list):
            _normalize_object_schemas(child)


def _validate_object_schema_invariants(value: object, path: str = "$") -> None:
    """Fail locally when strict required fields escape their owning object node."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_object_schema_invariants(item, f"{path}[{index}]")
        return
    if not isinstance(value, dict):
        return
    properties = value.get("properties")
    additional = value.get("additionalProperties")
    if properties is None and isinstance(additional, dict):
        raise ValueError(
            f"Unsupported strict schema at {path}: arbitrary-key object schemas are not supported"
        )
    if isinstance(properties, dict):
        required = value.get("required")
        if not isinstance(required, list) or set(required) != set(properties):
            raise ValueError(
                f"Invalid strict schema at {path}: required must equal local properties"
            )
    for key, child in value.items():
        _validate_object_schema_invariants(child, f"{path}.{key}")
