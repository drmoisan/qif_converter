#!/usr/bin/env python3
"""
Core Utilities

Features:
- Universal converter with support for protocols
- File I/O helpers
- String utilities
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import is_dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import (
    get_origin,
    get_args,
    Union,
    Dict,
    get_type_hints,
    Annotated,
    Optional,
    Mapping,
)
import types

from quicken_helper.utilities.converters_collection import _COLLECTION_CONVERTERS
from quicken_helper.utilities.converters_scalar import _SCALAR_CONVERTERS

#region Common functions

def is_null_or_whitespace(s: Optional[str]) -> bool:
    """Check if a string is None, empty, or consists only of whitespace."""
    return s is None or s.strip() == ""

def open_for_read(path: Path, binary: bool = False, **kwargs):
    mode = "rb" if binary else "r"
    return open(path, mode, **kwargs)

#endregion Common functions

#region Universal Converter with Protocol support

protocol_implementation: Dict[type, type] = {}

_UNION_TYPES = (Union, types.UnionType)

def __unwrap_union(target_type, value):
    args = get_args(target_type)
    if value is None and type(None) in args:
        return None
    for arg in args:
        if arg is type(None):
            continue
        try:
            return convert_value(arg, value)
        except Exception:
            pass
    raise ValueError(f"Cannot convert {value!r} to {target_type!r}")

def __convert_dataclass_instance(target_type, value):
    if isinstance(value, target_type):
        return value
    if isinstance(value, dict):
        # expects `from_dict` in scope
        return from_dict(target_type, value)
    raise ValueError(
        f"Expected dict for {target_type.__name__}, got {type(value).__name__}"
    )

def __convert_enum(target_type, value):
    if isinstance(value, target_type):
        return value
    try:
        return target_type(value)  # by value
    except Exception:
        if isinstance(value, str):
            try:
                return target_type[value]  # by name
            except Exception:
                pass
        raise

def _normalize_type(t):
    # Unwrap Annotated
    if get_origin(t) is Annotated:
        return get_args(t)[0]
    # If someone passed a bare string like "int", map a few safe builtins
    if isinstance(t, str):
        _map = {"int": int, "float": float, "str": str, "bool": bool, "Decimal": Decimal}
        return _map.get(t, t)
    return t

# near the other helpers
def _is_protocol_type(t: object) -> bool:
    return isinstance(t, type) and getattr(t, "_is_protocol", False)

def _is_runtime_protocol_type(t: object) -> bool:
    return _is_protocol_type(t) and getattr(t, "_is_runtime_protocol", False)

def convert_value(target_type, value):
    target_type = _normalize_type(target_type)
    origin = get_origin(target_type)
    is_class = isinstance(target_type, type)

    # 1) Union / Optional
    if origin in _UNION_TYPES:
        return __unwrap_union(target_type, value)

    # 2) Real classes (avoid issubclass()/is_dataclass() TypeError on typing constructs)
    if is_class:
        if is_dataclass(target_type):
            return __convert_dataclass_instance(target_type, value)
        if issubclass(target_type, Enum):
            return __convert_enum(target_type, value)
        # --- NEW: Protocol support ---
        if _is_protocol_type(target_type):
            # Look up the preferred concrete type for this protocol, if any.
            impl_type = protocol_implementation.get(target_type, None)
            # If the protocol is runtime-checkable, enforce it;
            # otherwise, pass through (can’t check safely at runtime).
            if _is_runtime_protocol_type(target_type):
                if isinstance(value, target_type):
                    return value
                if impl_type is not None:
                    # If it's already the preferred impl, keep it; otherwise convert.
                    candidate = value if isinstance(value, impl_type) else convert_value(impl_type, value)
                    # Must satisfy the protocol after conversion.
                    if isinstance(candidate, target_type):
                        return candidate
                # No viable impl or conversion didn't satisfy the protocol → hard error.
                raise TypeError(
                    f"Value of type {type(value).__name__} "
                    f"does not implement protocol {target_type.__name__}"
                )
            # Non-runtime-checkable Protocols:
            # We can't isinstance-check the protocol; if we know a preferred impl, convert to it.
            if impl_type is not None and not isinstance(value, impl_type):
                return convert_value(impl_type, value)
            # Otherwise, trust the caller and pass the value through.
            return value
        # --- end NEW ---

        if target_type in _SCALAR_CONVERTERS:
            return _SCALAR_CONVERTERS[target_type](value)

    # 3) Parameterized collections
    if isinstance(origin, type) and origin in _COLLECTION_CONVERTERS:
        args = get_args(target_type)
        return _COLLECTION_CONVERTERS[origin](args, value, convert_value)

    # 4) dict[K, V]
    if origin is dict:
        key_t, val_t = get_args(target_type) or (object, object)
        return {convert_value(key_t, k): convert_value(val_t, v)
                for k, v in dict(value).items()}

    # 5) Fallback: direct construction
    if is_class:
        try:
            return target_type(value)
        except Exception:
            pass

    raise ValueError(
        f"Don’t know how to convert {type(value).__name__} -> {target_type!r}"
    )

def from_dict(cls, src):
    """
    Reconstruct dataclass `cls` from a plain dict (handles nesting, unions, containers).
    If `cls` is not a dataclass (e.g., int, str, Decimal, list[int], etc.), this
    function delegates to `convert_value` and returns its result.
    """
    # If not a dataclass target, treat as a general conversion (pass-through for primitives)
    try:
        is_dc = is_dataclass(cls)
    except TypeError:
        is_dc = False

    if not is_dc:
        # e.g., from_dict(int, 123) -> 123; from_dict(list[int], ["1","2"]) -> [1,2]
        return convert_value(cls, src)

    # Dataclass branch: require a mapping
    if not isinstance(src, Mapping):
        raise TypeError(
            f"from_dict expects a mapping for {cls.__name__}, got {type(src).__name__}"
        )

    # Resolve forward references (PEP 563 / __future__.annotations)
    type_hints = get_type_hints(cls)

    kwargs = {}
    for f in fields(cls):
        if f.name not in src:
            # let dataclass defaults apply
            continue

        val = src[f.name]
        # Prefer resolved type; fall back to the raw annotation if it's missing
        ftype = type_hints.get(f.name, f.type)

        kwargs[f.name] = convert_value(ftype, val)
    return cls(**kwargs)

#endregion Universal Converter with Protocol support