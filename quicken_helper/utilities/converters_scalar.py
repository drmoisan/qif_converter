# quicken_helper/utilities/converters_scalar.py
from __future__ import annotations

import re
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from typing import Any, Dict


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


_ALLOW_BOOL_TO_INT = True
_TRUE_STRINGS = {"1", "true", "t", "yes", "y", "on"}
_SCALAR_CONVERTERS: Dict[type, Any] = {
    Decimal: _to_decimal,
    int: _to_int,
    float: _to_float,
    bool: _to_bool,
    str: _to_str,
    date: _to_date,
    datetime: _to_datetime,
}


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
