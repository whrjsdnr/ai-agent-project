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
    return schema


def _normalize_object_schemas(value: object) -> None:
    """Recursively normalize objects, including schemas held in ``$defs``."""
    if isinstance(value, list):
        for item in value:
            _normalize_object_schemas(item)
        return
    if not isinstance(value, dict):
        return

    for child in value.values():
        _normalize_object_schemas(child)

    properties = value.get("properties")
    if isinstance(properties, dict):
        value["required"] = list(properties)
        value["additionalProperties"] = False
