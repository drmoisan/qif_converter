# quicken_helper/utilities/converters_scalar.py
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Final, Optional, overload


def _bad(value: Any, target: str) -> ValueError:
    return ValueError(f"Cannot convert {type(value).__name__} to {target}")


@overload
def to_datetime(value: datetime, /) -> datetime: ...
@overload
def to_datetime(value: date, /) -> datetime: ...
@overload
def to_datetime(value: int, /) -> datetime: ...
@overload
def to_datetime(value: float, /) -> datetime: ...
@overload
def to_datetime(value: str, /) -> datetime: ...


def to_datetime(value: object, /) -> datetime:
    """
    Convert a datetime-like input into a naive `datetime` (local time for timestamps).

    Accepts:
      • datetime → returned as-is
      • date     → combined with midnight (00:00:00)
      • int/float (POSIX timestamp, seconds) → local-time datetime
      • str (ISO 8601; allows trailing 'Z' as UTC) → parsed via fromisoformat

    Raises
    ------
    ValueError
        If the value cannot be converted.
    """
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


def to_decimal(value: Any) -> Decimal:
    """
    Convert various inputs to Decimal with lenient, locale-aware-ish parsing.

    Supported string formats:
      - "1234", "-1234", "1234-", "(1,234.56)", "-3,188.32"
      - "1,234.56" (US) and "1.234,56" (EU) — auto-detects decimal vs thousands
      - Currency symbols/words ignored: "$1,234.56", "EUR 1.234,56", etc.

    Rules for decimal/thousands detection:
      * If both ',' and '.' appear: the *last* separator is treated as decimal;
        the other is treated as thousands and removed.
      * If only one of ',' or '.' appears:
          - If exactly 3 digits follow it and there are no other separators,
            treat it as thousands (remove it).
          - If 1–2 digits follow it, treat it as decimal.
          - Otherwise (e.g., 0 or >3 digits), treat as thousands (remove).

    Raises:
        ValueError: if no digits are present or the cleaned value is invalid.

    Examples:
        _to_decimal("-3,188.32")        -> Decimal('-3188.32')
        _to_decimal("1.234,56")         -> Decimal('1234.56')
        _to_decimal("(1,234.56)")       -> Decimal('-1234.56')
        _to_decimal("1,234")            -> Decimal('1234')
        _to_decimal("EUR 1.234,00")     -> Decimal('1234.00')
    """
    # Fast-path for numeric types
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        # Avoid binary float artifacts
        return Decimal(str(value))

    if not isinstance(value, str):
        raise ValueError(
            f"Unsupported type for Decimal conversion: {type(value).__name__}"
        )

    cleaned = clean_number_like_string(value, ".")

    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(
            f"Could not parse Decimal from {value!r} (normalized to {cleaned!r})"
        ) from e


def clean_number_like_string(value: str, decimal_char: str = "") -> str:
    s = value.strip()
    if not s:
        raise ValueError("Empty string cannot be converted to Decimal")

    # Normalize common oddities
    s = s.replace("\xa0", " ").replace(_UNICODE_MINUS, "-")  # NBSP, unicode minus
    s = s.strip()

    # Detect negative via parentheses or trailing minus
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    if s.endswith("-"):
        neg = not neg  # trailing minus toggles sign (if both, end up negative)
        s = s[:-1].strip()

    # Remove currency symbols/letters and anything not in [digits , . - ( )]
    s = _NON_DIGIT_KEEP_SEP.sub("", s)

    # Remove any stray leading '+' and handle leading '-'
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        neg = not neg
        s = s[1:]

    # After cleaning we should have digits and possibly , .
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        raise ValueError(f"No digits found in input: {value!r}")

    has_comma = "," in s
    has_dot = "." in s

    def _apply_decimal_sep(txt: str, decimal_sep: Optional[str]) -> str:
        if decimal_sep is None:
            # Remove all separators (integers with thousand marks only)
            return txt.replace(",", "").replace(".", "")
        if decimal_sep == ".":
            # '.' is decimal → remove all commas
            return txt.replace(",", "")
        else:
            # ',' is decimal → remove all dots, then swap ',' -> '.'
            return txt.replace(".", "").replace(",", ".")

    if decimal_char != "":
        # User-specified decimal char: remove the other if present
        if decimal_char == ".":
            cleaned = _apply_decimal_sep(s, ".")
        elif decimal_char == ",":
            cleaned = _apply_decimal_sep(s, ",")
        else:
            raise ValueError(f"Invalid decimal_char: {decimal_char!r}")
    elif has_comma and has_dot:
        # Use the last separator as the decimal mark
        dec_sep = "," if s.rfind(",") > s.rfind(".") else "."
        cleaned = _apply_decimal_sep(s, dec_sep)
    elif has_comma or has_dot:
        ch = "," if has_comma else "."
        idx = s.rfind(ch)
        after = len(s) - idx - 1
        # Decide if it's a decimal or thousands separator
        if after in (1, 2):
            dec_sep = ch
        elif after == 3:
            # likely "1,234" thousands
            dec_sep = None
        else:
            # ambiguous: default to thousands (safer than misplacing decimal)
            dec_sep = None
        cleaned = _apply_decimal_sep(s, dec_sep)
    else:
        cleaned = s  # pure digits (and maybe dashes already handled)

    cleaned = cleaned.strip()
    # restored sign
    if neg and cleaned and cleaned[0] != "-":
        cleaned = "-" + cleaned
    return cleaned


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
    if not isinstance(v, str):
        raise ValueError(f"Unsupported type for integer conversion: {type(v).__name__}")
    cleaned = clean_number_like_string(v, ".")
    try:
        return int(cleaned)
    except ValueError as e:
        raise ValueError(
            f"Could not parse int from {v!r} (normalized to {cleaned!r})"
        ) from e


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


def default_date() -> date:
    return _DEFAULT_DATE


_DEFAULT_DATE = date(1900, 1, 1)


@overload
def to_date(s: datetime, should_raise: bool = True, /) -> date: ...
@overload
def to_date(s: date, should_raise: bool = True, /) -> date: ...
@overload
def to_date(s: str, should_raise: bool = True, /) -> date: ...


def to_date(s: object, should_raise: bool = True, /) -> date:
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
        return _DEFAULT_DATE

    # Already a date/datetime?
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()

    txt = str(s).strip()
    if not txt:
        return _DEFAULT_DATE

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
    m = _DATE_RE_01.match(txt)
    if m:
        a, b, c = m.groups()

        # Find the separator used (/, -, .)
        sep_search = _DATE_RE_02.search(txt)
        if not sep_search:
            if should_raise:
                raise ValueError(
                    f"Unrecognized date format (no date separator found): {s!r}"
                )
            return _DEFAULT_DATE
        sep = sep_search.group(0)

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

    def _from_excel_serial(n: float) -> date | None:
        """Convert an Excel serial date (1900 system) to a date, or None if out of range.

        - We convert using the 1900 date system, honoring Excel’s leap-year bug:
          - Excel serial 1 => 1900-01-01
          - Excel serial 60 => 1900-02-29 (nonexistent); we map to 1900-02-28
        - Fractional part (time) is ignored.
        """
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
    return _DEFAULT_DATE


_DATE_RE_01: Final[re.Pattern[str]] = re.compile(
    r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*$"
)
_DATE_RE_02: Final[re.Pattern[str]] = re.compile(r"[/\-.]")
_ALLOW_BOOL_TO_INT = True
_TRUE_STRINGS = {"1", "true", "t", "yes", "y", "on"}
SCALAR_CONVERTERS: Dict[type, Any] = {
    Decimal: to_decimal,
    int: _to_int,
    float: _to_float,
    bool: _to_bool,
    str: _to_str,
    date: to_date,
    datetime: to_datetime,
}
_NON_DIGIT_KEEP_SEP: Final[re.Pattern[str]] = re.compile(r"[^\d,.\-\(\)]+")
_UNICODE_MINUS = "\u2212"  # '−'
