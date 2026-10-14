"""Lossless JSON codec for `ImportSession` and everything it holds.

The encoded document is self-describing: every JSON object is a tagged node
(`{"$t": kind, ...}`), so cell text or a model-written table key can never be
mistaken for structure. Decimals travel as strings (exponent included), tuples
stay tuples and dicts keep non-string keys.

Decoding only rebuilds dataclasses and enums that live under `pricor.`, so a
corrupted or hostile row in the database cannot name an arbitrary class.
"""

import dataclasses
import importlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

_ALLOWED_PREFIX = "pricor."


class SessionCodecError(Exception):
    """The stored document is not something this codec wrote."""


def _qualified_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _to_node(value: Any) -> Any:
    if isinstance(value, Enum):  # before the primitives: StrEnum members are also str
        return {"$t": "enum", "c": _qualified_name(type(value)), "v": _to_node(value.value)}
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return {"$t": "dec", "v": str(value)}
    if isinstance(value, datetime):
        return {"$t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"$t": "date", "v": value.isoformat()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "$t": "dc",
            "c": _qualified_name(type(value)),
            "f": {
                field.name: _to_node(getattr(value, field.name))
                for field in dataclasses.fields(value)
                if field.init
            },
        }
    if isinstance(value, tuple):
        return {"$t": "tuple", "v": [_to_node(item) for item in value]}
    if isinstance(value, list):
        return {"$t": "list", "v": [_to_node(item) for item in value]}
    if isinstance(value, set | frozenset):
        kind = "frozenset" if isinstance(value, frozenset) else "set"
        return {"$t": kind, "v": [_to_node(item) for item in value]}
    if isinstance(value, dict):
        return {"$t": "dict", "v": [[_to_node(k), _to_node(v)] for k, v in value.items()]}
    raise SessionCodecError(f"cannot store a value of type {type(value).__name__}")


def _resolve(name: Any, kind: type) -> type:
    if not isinstance(name, str) or not name.startswith(_ALLOWED_PREFIX) or "." not in name:
        raise SessionCodecError(f"refusing to load {name!r}")
    module_name, _, attribute = name.rpartition(".")
    try:
        cls = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise SessionCodecError(f"unknown stored type {name!r}") from error
    ok = (
        isinstance(cls, type)
        and issubclass(cls, Enum)
        if kind is Enum
        else dataclasses.is_dataclass(cls) and isinstance(cls, type)
    )
    if not ok:
        raise SessionCodecError(f"{name!r} is not a stored {kind.__name__.lower()} type")
    return cls


def _from_node(node: Any) -> Any:
    if node is None or isinstance(node, bool | int | float | str):
        return node
    if not isinstance(node, dict) or "$t" not in node:
        raise SessionCodecError("malformed stored node")
    kind = node["$t"]
    try:
        match kind:
            case "dec":
                return Decimal(node["v"])
            case "datetime":
                return datetime.fromisoformat(node["v"])
            case "date":
                return date.fromisoformat(node["v"])
            case "enum":
                return _resolve(node["c"], Enum)(_from_node(node["v"]))
            case "dc":
                cls = _resolve(node["c"], type(None))
                return cls(**{name: _from_node(item) for name, item in node["f"].items()})
            case "tuple":
                return tuple(_from_node(item) for item in node["v"])
            case "list":
                return [_from_node(item) for item in node["v"]]
            case "set":
                return {_from_node(item) for item in node["v"]}
            case "frozenset":
                return frozenset(_from_node(item) for item in node["v"])
            case "dict":
                return {_from_node(k): _from_node(v) for k, v in node["v"]}
    except SessionCodecError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError) as error:
        raise SessionCodecError(f"malformed stored {kind!r} node") from error
    raise SessionCodecError(f"unknown stored node kind {kind!r}")


def encode(value: Any) -> str:
    return json.dumps(_to_node(value), ensure_ascii=False, separators=(",", ":"))


def decode(text: str) -> Any:
    try:
        node = json.loads(text)
    except (TypeError, ValueError) as error:
        raise SessionCodecError("stored document is not valid JSON") from error
    return _from_node(node)
