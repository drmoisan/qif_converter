#!/usr/bin/env python3
"""
Core Utilities

Features:
- Universal converter with support for protocols
- File I/O helpers
- String utilities
"""

from __future__ import annotations

import types
from collections.abc import Iterable as ABCIterable, Mapping as ABCMapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import (
    IO,
    Annotated,
    Any,
    Callable,
    Dict,
    Literal,
    Mapping,
    Optional,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from quicken_helper.utilities.converters_collection import COLLECTION_CONVERTERS
from quicken_helper.utilities.converters_scalar import SCALAR_CONVERTERS

# region Common functions


def is_null_or_whitespace(s: Optional[str]) -> bool:
    """Check if a string is None, empty, or consists only of whitespace."""
    return s is None or s.strip() == ""


@overload
def open_for_read(path: Path, binary: Literal[True], **kwargs: Any) -> IO[bytes]: ...
@overload
def open_for_read(path: Path, binary: Literal[False], **kwargs: Any) -> IO[str]: ...


def open_for_read(path: Path, binary: bool = False, **kwargs: Any) -> IO[Any]:
    mode = "rb" if binary else "r"
    return open(path, mode, **kwargs)


# endregion Common functions

# region Universal Converter with Protocol support

# region Convert Protocol

protocol_implementation: Dict[type, type] = {}


# near the other helpers
def is_protocol_type(t: object) -> bool:
    return isinstance(t, type) and getattr(t, "_is_protocol", False)


def is_runtime_protocol_type(t: object) -> bool:
    return is_protocol_type(t) and getattr(t, "_is_runtime_protocol", False)


# endregion Convert Protocol

# region Convert Unions

_UNION_TYPES = (Union, types.UnionType)


def __unwrap_union(target_type: object, value: Any):
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


# endregion Convert Unions

# region Convert Dataclass

DC = TypeVar("DC")


@overload
def _convert_dataclass_instance(
    target_type: type[DC],
    value: DC,
    /,
    *,
    convert: Callable[[type[DC], Mapping[str, object]], DC] | None = ...,
) -> DC: ...
@overload
def _convert_dataclass_instance(
    target_type: type[DC],
    value: Mapping[str, object],
    /,
    *,
    convert: Callable[[type[DC], Mapping[str, object]], DC] | None = ...,
) -> DC: ...


def _convert_dataclass_instance(
    target_type: type[DC],
    value: object,
    /,
    *,
    convert: Callable[[type[DC], Mapping[str, object]], DC] | None = None,
) -> DC:
    """
    This function serves two purposes

    - It allows from_dict to handle nested dataclasses by routing all type conversions through convert_value
    - It creates a second entry point to convert dictionaries to dataclasses via convert_value

    If `value` is already an instance of `target_type`, return it.
    If `value` is a Mapping[str, Any], call from_dict`.
    Otherwise raise.
    """
    if not is_dataclass(target_type):
        raise TypeError(f"Expected dataclass type, got {target_type!r}")

    if isinstance(value, target_type):
        return value

    if _is_mapping_of_str_any(value):
        return from_dict(target_type, value)

    raise ValueError(
        f"Expected dict-like for {target_type.__name__}, got {type(value).__name__}"
    )


# endregion Convert Dataclass

# region Convert Enum

E = TypeVar("E", bound=Enum)


@overload
def __convert_enum(target_type: type[E], value: E, /) -> E: ...
@overload
def __convert_enum(target_type: type[E], value: int, /) -> E: ...
@overload
def __convert_enum(target_type: type[E], value: str, /) -> E: ...
@overload
def __convert_enum(target_type: type[E], value: object, /) -> E: ...


def __convert_enum(target_type: type[E], value: object, /) -> E:
    """
    Convert `value` to the given Enum subclass.

    Accepts:
      • value already of target enum → returned as-is
      • value equal to an enum member's *value* (e.g., int/str) → target_type(value)
      • value equal to an enum member's *name* (str) → target_type[name]

    Raises
    ------
    TypeError  if target_type is not an Enum subclass
    ValueError if no member matches the input
    """
    # Already the right enum?
    if isinstance(value, target_type):
        return value  # type: ignore[return-value]  # Pylance infers E here

    # Try by underlying value
    try:
        return target_type(value)  # type: ignore[call-overload]
    except Exception:
        # Try by member name
        if isinstance(value, str):
            try:
                return target_type[value]
            except KeyError:
                pass

    raise ValueError(f"{value!r} is not a valid {target_type.__name__}")


# endregion Convert Enum

# region Convert Value


def _normalize_type(t: object) -> object:
    """Return a concrete runtime `type` from a type-like value.

    Accepts:
      • a runtime type (e.g., int, Decimal, MyClass) → returned as-is
      • Annotated[X, ...] → returns X
      • a few string aliases ("int", "float", "str", "bool", "Decimal") → mapped

    Raises:
      TypeError if `t` cannot be normalized to a runtime type.
    """
    # Unwrap Annotated[T, ...] to T
    if get_origin(t) is Annotated:
        base, *_ = get_args(t)
        # best effort: only accept if the base is actually a runtime `type`
        if isinstance(base, type):
            return base  # type: ignore[return-value]  # (Pylance usually infers fine)
        # Allow generic typing constructs to pass through (e.g., list[int], dict[str, Any], Union[..., ...])
        # so callers can continue to use get_origin/get_args on them downstream.
        if get_origin(t) is not None:
            return t
        raise TypeError(f"Cannot normalize to a runtime type: {t!r}")

    # Strings → a small safe mapping
    if isinstance(t, str):
        _map: dict[str, type[Any]] = {
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "Decimal": Decimal,
        }
        tp = _map.get(t)
        if tp is None:
            raise TypeError(f"Unknown type alias: {t!r}")
        return tp

    # Already a runtime type?
    if isinstance(t, type):
        return t

    raise TypeError(f"Cannot normalize to a runtime type: {t!r}")


def _coerce_mapping_like(value: object, ctx: str) -> Mapping[object, object]:
    """
    Accept a Mapping[K, V] or an iterable of (K, V) pairs and return a typed Mapping[object, object].
    Raises a clear TypeError otherwise. `ctx` is used to improve the error message.
    """
    if isinstance(value, ABCMapping):
        # Keys/values are unknown at this point; expose as Mapping[object, object]
        return cast(Mapping[object, object], value)

    if isinstance(value, ABCIterable):
        # Pylance wants an Iterable[tuple[object, object]], so we cast and validate via dict().
        value_iter: ABCIterable[object] = cast(ABCIterable[object], value)
        try:
            pairs_iter: ABCIterable[tuple[object, object]] = cast(
                ABCIterable[tuple[object, object]], value_iter
            )
            tmp = dict(pairs_iter)  # may raise if not (k, v) pairs
            return cast(Mapping[object, object], tmp)
        except Exception as e:
            raise TypeError(
                f"Expected mapping or iterable of (key, value) pairs for {ctx}; got {type(value_iter).__name__}"
            ) from e

    raise TypeError(
        f"Expected mapping or iterable of (key, value) pairs for {ctx}; got {type(value).__name__}"
    )


@overload
def convert_value(target_type: type[E], value: E) -> E: ...
@overload
def convert_value(target_type: type[DC], value: DC) -> DC: ...
@overload
def convert_value(target_type: object, value: object) -> Any: ...


def convert_value(target_type: object, value: object) -> Any:
    target_type = _normalize_type(target_type)
    origin = get_origin(target_type)
    is_class = isinstance(target_type, type)

    # 1) Union / Optional
    if origin in _UNION_TYPES:
        return __unwrap_union(target_type, value)

    # 2) Real classes (avoid issubclass()/is_dataclass() TypeError on typing constructs)
    if isinstance(target_type, type):
        tt: type[Any] = target_type  # <-- explicitly a class

        if is_dataclass(tt):
            return _convert_dataclass_instance(tt, value)
        if issubclass(tt, Enum):
            return __convert_enum(tt, value)
        # --- NEW: Protocol support ---
        if is_protocol_type(tt):
            # Look up the preferred concrete type for this protocol, if any.
            impl_type = protocol_implementation.get(target_type, None)
            # If the protocol is runtime-checkable, enforce it;
            # otherwise, pass through (can’t check safely at runtime).
            if is_runtime_protocol_type(tt):
                if isinstance(value, tt):
                    return value
                if impl_type is not None:
                    # If it's already the preferred impl, keep it; otherwise convert.
                    candidate = (
                        value
                        if isinstance(value, impl_type)
                        else convert_value(impl_type, value)
                    )
                    # Must satisfy the protocol after conversion.
                    if isinstance(candidate, tt):
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

        if target_type in SCALAR_CONVERTERS:
            return SCALAR_CONVERTERS[target_type](value)

    # 3) Parameterized collections
    if isinstance(origin, type) and origin in COLLECTION_CONVERTERS:
        args = get_args(target_type)
        return COLLECTION_CONVERTERS[origin](args, value, convert_value)

    # 4) dict[K, V]
    if origin is dict:
        args = get_args(target_type)
        if len(args) != 2:
            raise TypeError(
                f"dict[K, V] requires two type arguments; got {args!r} for {target_type!r}"
            )
        key_t, val_t = args

        pairs_map = _coerce_mapping_like(value, ctx=str(target_type))
        return {
            convert_value(key_t, k): convert_value(val_t, v)
            for k, v in pairs_map.items()
        }

    # 5) Fallback: direct construction
    if is_class:
        try:
            return target_type(value)
        except Exception:
            pass

    raise ValueError(
        f"Don’t know how to convert {type(value).__name__} -> {target_type!r}"
    )


# endregion Convert Value

# region from_dict


def _is_mapping_of_str_any(m: object) -> TypeGuard[Mapping[str, Any]]:
    if not isinstance(m, Mapping):
        return False
    nm: Mapping[object, Any] = cast(Mapping[object, Any], m)
    return all(isinstance(k, str) for k in nm.keys())


# Overloads give precise types to callers.
@overload
def from_dict(target_type: type[DC], src: Mapping[str, Any], /) -> DC: ...
@overload
def from_dict(target_type: object, src: Any, /) -> Any: ...


def from_dict(target_type: object, src: Any, /) -> Any:
    """
    Reconstruct dataclass `cls` from a plain dict (handles nesting, unions, containers).
    If `cls` is not a dataclass (e.g., int, str, Decimal, list[int], etc.), this
    function delegates to `convert_value` and returns its result.
    """
    # If not a class at all → delegate
    if not isinstance(target_type, type):
        return convert_value(target_type, src)

    class_type: type[Any] = target_type

    if not is_dataclass(class_type):
        return convert_value(class_type, src)

    # Tell the Type Checker that src is a Mapping[str, Any]
    if not _is_mapping_of_str_any(src):
        raise TypeError(
            f"from_dict expects string-keyed mapping for {class_type.__name__} "
            f"(got keys like {next(iter(src.keys()), None)!r})"
        )

    # Now we know 'cls' is a Python class that is a dataclass.
    type_hints = get_type_hints(class_type)
    kwargs: dict[str, Any] = {}

    for f in fields(class_type):
        if f.name not in src:
            # let dataclass defaults apply
            continue

        val: Any = src[f.name]
        ftype = type_hints.get(f.name, f.type)
        # Prefer resolved type; fall back to the raw annotation if it's missing

        kwargs[f.name] = convert_value(ftype, val)
    return class_type(**kwargs)


# endregion from_dict

# endregion Universal Converter with Protocol support
