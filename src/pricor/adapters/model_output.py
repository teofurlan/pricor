"""Strict checks for untrusted model output (already parsed JSON).

Every helper raises `ModelSchemaError` naming the offending path. Nothing is
coerced: a wrong type, an extra key or an out-of-range number is rejected.
"""

from collections.abc import Collection
from typing import Any

from pricor.ports.model_errors import ModelSchemaError

MAX_TEXT_LENGTH = 400


def fail(path: str, message: str) -> ModelSchemaError:
    return ModelSchemaError(f"model output {path}: {message}")


def expect_object(value: Any, path: str, keys: Collection[str]) -> dict[str, Any]:
    """The value must be an object with exactly `keys`."""
    if not isinstance(value, dict):
        raise fail(path, "must be an object")
    missing = sorted(set(keys) - value.keys())
    extra = sorted(value.keys() - set(keys))
    if missing:
        raise fail(path, f"missing key(s): {', '.join(missing)}")
    if extra:
        raise fail(path, f"unexpected key(s): {', '.join(extra)}")
    return value


def expect_list(value: Any, path: str, *, min_items: int = 0, max_items: int = 100) -> list[Any]:
    if not isinstance(value, list):
        raise fail(path, "must be a list")
    if not min_items <= len(value) <= max_items:
        raise fail(path, f"must have between {min_items} and {max_items} items")
    return value


def expect_text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise fail(path, "must be a string")
    if not allow_empty and not value.strip():
        raise fail(path, "must not be empty")
    if len(value) > MAX_TEXT_LENGTH:
        raise fail(path, f"must have at most {MAX_TEXT_LENGTH} characters")
    return value


def expect_choice(value: Any, path: str, allowed: Collection[str]) -> str:
    # Unhashable values (lists, dicts) can never match; check the type first.
    if not isinstance(value, str) or value not in allowed:
        raise fail(path, f"must be one of: {', '.join(sorted(allowed))}")
    return value


def expect_unit_interval(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
        raise fail(path, "must be a number between 0 and 1")
    return float(value)


def expect_index(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise fail(path, "must be a non-negative integer")
    return value
