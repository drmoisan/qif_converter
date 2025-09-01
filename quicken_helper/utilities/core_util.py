#!/usr/bin/env python3
"""
Core Utilities

Features:
- Date Parsing support
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, time
from pathlib import Path
from dataclasses import is_dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import (
    get_origin,
    get_args,
    Union,
    Any,
    Dict,
    get_type_hints,
    Annotated,
    Callable,
    Optional,
    Mapping,
)
import types
from collections import deque


def is_null_or_whitespace(s: Optional[str]) -> bool:
    """Check if a string is None, empty, or consists only of whitespace."""
    return s is None or s.strip() == ""

def parse_date_string(s: object, should_raise: bool = False) -> date | None:
    """
    Parse common QIF and adjacent date encodings into a date.

    Supported examples:
      - 12/31'24              (QIF classic, 2-digit year with apostrophe)
      - 12/31/2024            (US)
      - 12-31-2024, 12.31.2024
      - 2024-12-31            (ISO)
      - 2024/12/31, 2024.12.31
      - 20241231              (ISO compact)
      - 31/12/2024            (D/M/Y when unambiguous: first token > 12)
      - 2024-12-31T23:59:59Z  (ISO datetime; time/offset ignored)
      - 45567 or 45567.75     (Excel serial “General” date; fractional = time, ignored)

    Returns:
        datetime.date if recognized; otherwise None.
    """
    if s is None:
        return None

    # Already a date/datetime?
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()

    txt = str(s).strip()
    if not txt:
        return None

    # Normalize curly/back quotes used in some exports
    txt = txt.replace("’", "'").replace("`", "'")

    # If it's a full ISO datetime, try Python's ISO parser (ignore time/offset).
    if "T" in txt:
        iso_dt_clean = re.sub(r"Z$", "", txt)
        try:
            return datetime.fromisoformat(iso_dt_clean).date()
        except ValueError:
            pass  # fall through

    # Try a set of known string patterns (order matters).
    patterns = (
        "%m/%d'%y",  # QIF classic e.g., 01/02'25
        "%m/%d/%Y",  # 01/02/2025
        "%Y-%m-%d",  # 2025-01-02
        "%Y/%m/%d",  # 2025/01/02
        "%Y.%m.%d",  # 2025.01.02
        "%m-%d-%Y",  # 01-02-2025
        "%m.%d.%Y",  # 01.02.2025
        "%Y%m%d",  # 20250102
    )
    for fmt in patterns:
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue

    # Heuristic for D/M/Y vs M/D/Y ambiguity:
    m = re.match(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$", txt)
    if m:
        a, b, c = m.groups()
        sep = re.search(r"[/\-.]", txt).group(0)
        first = int(a)
        second = int(b)
        year_fmt = "%Y" if len(c) == 4 else "%y"
        is_dmy = first > 12 and second <= 12
        fmt = ("%d{sep}%m{sep}" + year_fmt) if is_dmy else ("%m{sep}%d{sep}" + year_fmt)
        fmt = fmt.format(sep=sep)
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            pass

    # --- Excel serial “General” date support ---
    # Accept plain numeric strings (optionally with a fractional part).
    # We convert using the 1900 date system, honoring Excel’s leap-year bug:
    #   - Excel serial 1 => 1900-01-01
    #   - Excel serial 60 => 1900-02-29 (nonexistent); we map to 1900-02-28
    # Fractional part (time) is ignored.
    def _from_excel_serial(n: float) -> date | None:
        try:
            days = int(n)  # ignore fractional time
        except Exception:
            return None
        if days < 0:
            return None  # out of scope
        base = date(1899, 12, 31)
        # Skip the fictitious 1900-02-29 for serials >= 60
        if days >= 60:
            days -= 1
        return base + timedelta(days=days)

    # Only treat as Excel serial after failing all date-pattern attempts.
    # Avoid misinterpreting long numeric dates like 20241231 (already handled above).
    if re.fullmatch(r"\d+(\.\d+)?", txt):
        try:
            as_float = float(txt)
        except ValueError:
            as_float = None
        if as_float is not None:
            d = _from_excel_serial(as_float)
            if d is not None:
                return d

    # Nothing matched
    if should_raise:
        raise ValueError(f"Unrecognized date format: {s!r}")
    return None


def _open_for_read(path: Path, binary: bool = False, **kwargs):
    mode = "rb" if binary else "r"
    return open(path, mode, **kwargs)


QIF_SECTION_PREFIX = "!Type:"
QIF_ACCOUNT_HEADER = "!Account"
TRANSFER_RE = re.compile(
    r"^\[(?:transfer:?\s*)?(?P<acct>.+?)]$",
    re.IGNORECASE,
)  # e.g., [Savings]


# ---------------------------
# Small scalar conversion helpers + dispatch
# ---------------------------

_ALLOW_BOOL_TO_INT = True
_TRUE_STRINGS = {"1", "true", "t", "yes", "y", "on"}

def _bad(value: Any, target: str) -> ValueError:
    return ValueError(f"Cannot convert {type(value).__name__} to {target}")

def _to_date(value):
    return parse_date_string(value, should_raise=True)

def _to_datetime(value):
    if isinstance(value, datetime):
        return value
    # date → datetime (midnight, naive)
    if isinstance(value, date):
        return datetime.combine(value, time())
    # POSIX timestamp → datetime (naive, local time)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    # ISO 8601 string → datetime
    if isinstance(value, str):
        s = value.strip()
        # allow trailing 'Z' as UTC
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    raise ValueError(f"Cannot convert {type(value).__name__} to datetime")

def _to_decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))  # avoid float->Decimal binary quirks
    if isinstance(v, str):
        return Decimal(v.strip())
    raise _bad(v, "Decimal")

def _to_int(v: Any) -> int:
    # bool is a subclass of int; decide policy explicitly
    if isinstance(v, bool):
        if _ALLOW_BOOL_TO_INT:
            return int(v)
        raise _bad(v, "int")
    if isinstance(v, int):
        return v
    if isinstance(v, Decimal):
        return int(v)
    if isinstance(v, float):
        if not v.is_integer():
            raise ValueError(f"Non-integer float {v} for int field")
        return int(v)
    if isinstance(v, str):
        return int(v.strip())
    raise _bad(v, "int")

def _to_float(v: Any) -> float:
    if isinstance(v, float):
        return v
    if isinstance(v, (int, bool, Decimal)):
        return float(v)
    if isinstance(v, str):
        return float(v.strip())
    raise _bad(v, "float")

def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in _TRUE_STRINGS
    if isinstance(v, (int, float, Decimal)):
        return bool(v)
    raise _bad(v, "bool")

def _to_str(v: Any) -> str:
    return "" if v is None else str(v)


_SCALAR_CONVERTERS: Dict[type, Any] = {
    Decimal: _to_decimal,
    int: _to_int,
    float: _to_float,
    bool: _to_bool,
    str: _to_str,
    date: _to_date,
    datetime: _to_datetime,
}

protocol_implementation: Dict[type, type] = {}

def _to_list(args, value, cv):
    (T,) = args or (object,)
    seq = list(value)  # let this raise if it's not iterable
    # (optional) guard: treat str/bytes as atomic, not iterable
    if isinstance(value, (str, bytes)):
        seq = [value]
    return [cv(T, v) for v in seq]

def _to_set(args, value, cv):
    (T,) = args or (object,)
    return {cv(T, v) for v in value}  # dedup by design

def _to_frozenset(args, value, cv):
    (T,) = args or (object,)
    return frozenset(cv(T, v) for v in value)

def _to_tuple(args, value, cv):
    seq = list(value)
    if not args:
        return tuple(seq)
    # tuple[T, ...] => homogeneous
    if len(args) == 2 and args[1] is Ellipsis:
        T = args[0]
        return tuple(cv(T, v) for v in seq)
    # tuple[T1, T2, ...] => fixed, heterogeneous
    if len(seq) != len(args):
        raise ValueError(f"Tuple arity mismatch: expected {len(args)}, got {len(seq)}")
    return tuple(cv(T, v) for T, v in zip(args, seq))

def _to_dict(args, value, cv):
    KT, VT = args or (object, object)
    items = dict(value).items()  # raises if not mapping-like
    return {cv(KT, k): cv(VT, v) for k, v in items}

def _to_deque(args, value, cv):
    (T,) = args or (object,)
    return deque(cv(T, v) for v in value)

# signature: (type args, value, recursive-converter) -> converted
CollectionConverter = Callable[[tuple[type, ...], Any, Callable[[Any, Any], Any]], Any]

_COLLECTION_CONVERTERS: dict[type[Any], CollectionConverter] = {
    list: _to_list,
    set: _to_set,
    frozenset: _to_frozenset,
    tuple: _to_tuple,
    dict: _to_dict,
    deque: _to_deque,
}

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