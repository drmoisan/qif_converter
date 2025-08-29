#!/usr/bin/env python3
"""
Core Utilities

Features:
- Date Parsing support
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from dataclasses import is_dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import get_origin, get_args, Union, Any


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


def _is_dataclass_type(t) -> bool:
    try:
        return is_dataclass(t)
    except TypeError:
        return False

def _convert_value(target_type: Any, value: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(target_type)
    args = get_args(target_type)

    # Optional/Union
    if origin is Union:
        non_none = [t for t in args if t is not type(None)]
        for t in non_none:
            try:
                return _convert_value(t, value)
            except Exception:
                pass
        return value

    # Scalars
    if target_type is Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            s = value.strip().lower()
            if s in {"true","1","yes","y","t"}:
                return True
            if s in {"false","0","no","n","f"}:
                return False
        return bool(value)
    if target_type is str:
        return str(value)
    if target_type is Path:
        return Path(value)

    # Enums
    if isinstance(target_type, type) and issubclass(target_type, Enum):
        if isinstance(value, target_type):
            return value
        try:
            return target_type[value]  # by name
        except Exception:
            return target_type(value)  # by value

    # Dates/times (ISO ‘YYYY-MM-DD’, ‘YYYY-MM-DDTHH:MM:SS’)
    if target_type is date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return parse_date_string(value, should_raise=True)
    if target_type is datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    # Collections
    if origin in (list, set, tuple):
        item_t = args[0] if args else Any
        converted = [_convert_value(item_t, v) for v in value]
        if origin is list:
            return converted
        if origin is set:
            return set(converted)
        if origin is tuple:
            # fixed-length tuple support
            if len(args) > 1 and args[-1] is not Ellipsis:
                return tuple(_convert_value(t, v) for t, v in zip(args, value))
            return tuple(converted)

    if origin is dict:
        kt, vt = (args + (Any, Any))[:2]
        return {
            _convert_value(kt, k): _convert_value(vt, v)
            for k, v in value.items()
        }

    # Nested dataclasses
    if _is_dataclass_type(target_type) and isinstance(value, dict):
        return from_dict(target_type, value)

    return value


def from_dict(cls, src):
    """Reconstruct dataclass `cls` from a plain dict (handles nesting, lists, dicts)."""
    if not is_dataclass(cls):
        return src  # primitive or already-built

    kwargs = {}
    for f in fields(cls):
        if f.name not in src:  # let dataclass defaults apply
            continue
        val = src[f.name]
        ftype = f.type
        origin = get_origin(ftype)
        args = get_args(ftype)

        if _is_dataclass_type(ftype) and isinstance(val, dict):
            kwargs[f.name] = from_dict(ftype, val)
        elif origin in (list, set, tuple) and isinstance(val, (list, tuple, set)):
            item_t = args[0] if args else Any
            items = [_convert_value(item_t, v) for v in val]
            if origin is list:
                kwargs[f.name] = items
            elif origin is set:
                kwargs[f.name] = set(items)
            else:  # tuple
                if len(args) > 1 and args[-1] is not Ellipsis:
                    kwargs[f.name] = tuple(
                        _convert_value(t, v) for t, v in zip(args, val)
                    )
                else:
                    kwargs[f.name] = tuple(items)
        elif origin is dict and isinstance(val, dict):
            kt, vt = (args + (Any, Any))[:2]
            kwargs[f.name] = {
                _convert_value(kt, k): _convert_value(vt, v)
                for k, v in val.items()
            }
        else:
            kwargs[f.name] = _convert_value(ftype, val)

    return cls(**kwargs)