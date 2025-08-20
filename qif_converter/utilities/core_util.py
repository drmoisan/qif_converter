#!/usr/bin/env python3
"""
Core Utilities

Features:
- Date Parsing support
"""
from datetime import datetime, date, timedelta
import re

def parse_date_string(s: object) -> date | None:
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
        "%m/%d'%y",     # QIF classic e.g., 01/02'25
        "%m/%d/%Y",     # 01/02/2025
        "%Y-%m-%d",     # 2025-01-02
        "%Y/%m/%d",     # 2025/01/02
        "%Y.%m.%d",     # 2025.01.02
        "%m-%d-%Y",     # 01-02-2025
        "%m.%d.%Y",     # 01.02.2025
        "%Y%m%d",       # 20250102
    )
    for fmt in patterns:
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue

    # Heuristic for D/M/Y vs M/D/Y ambiguity:
    m = re.match(r"^\s*(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})\s*$", txt)
    if m:
        a, b, c = m.groups()
        sep = re.search(r"[\/\-.]", txt).group(0)
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
    return None

