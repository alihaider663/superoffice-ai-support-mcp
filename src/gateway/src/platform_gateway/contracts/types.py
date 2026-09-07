"""Strict recursive JSON-compatible type definitions for protocol-neutral Gateway payloads."""

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]


def is_json_compatible(value: object) -> bool:
    """Validate whether an object strictly conforms to JSON-compatible types.

    Rejects bytes, sets, custom objects, database entities, and file handles.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list | tuple):
        return all(is_json_compatible(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_json_compatible(v) for k, v in value.items())
    return False
