# quicken_helper/gui_viewers/utils.py
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- constants expected by tests ---
WIN_HEADERS = [
    "Date",
    "Payee",
    "FI Payee",
    "Amount",
    "Debit/Credit",
    "Category",
    "Account",
    "Tag",
    "Memo",
    "Chknum",
]
MAC_HEADERS = [
    "Date",
    "Description",
    "Original Description",
    "Amount",
    "Transaction Type",
    "Category",
    "Account Name",
    "Labels",
    "Notes",
]

# --- date parsing used by tests ---
_DATE_FORMATS = ["%m/%d'%y", "%m/%d/%Y", "%Y-%m-%d"]


def parse_date_maybe(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    s2 = s.replace("’", "'").replace("`", "'")
    if s2 != s:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s2, fmt)
            except ValueError:
                continue
    return None


def filter_date_range(
    txns: List[Dict[str, Any]], start_str: str, end_str: str
) -> List[Dict[str, Any]]:
    def _d(s: str):
        d = parse_date_maybe(s)
        return d.date() if d else None

    start = _d(start_str) if start_str else None
    end = _d(end_str) if end_str else None
    if not start and not end:
        return txns

    out: List[Dict[str, Any]] = []
    for t in txns:
        d = parse_date_maybe(str(t.get("date", "")).strip())
        if not d:
            continue
        if start and d.date() < start:
            continue
        if end and d.date() > end:
            continue
        out.append(t)
    return out


# --- CSV writers expected by tests ---
def write_csv_quicken_windows(txns: List[Dict[str, Any]], out_path: Path):
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(WIN_HEADERS)
        for t in txns:
            amt = str(t.get("amount", "")).strip()
            memo = str(t.get("memo", "")).replace("\r", "").replace("\n", " ")
            row = [
                t.get("date", ""),
                t.get("payee", ""),
                "",
                amt,
                "",
                t.get("category", ""),
                t.get("account", ""),
                "",
                memo,
                t.get("checknum", ""),
            ]
            w.writerow(row)


def write_csv_quicken_mac(txns: List[Dict[str, Any]], out_path: Path):
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(MAC_HEADERS)
        for t in txns:
            amt_str = str(t.get("amount", "")).strip()
            try:
                val = float(amt_str.replace(",", ""))
            except Exception:
                val = 0.0
            txn_type = "credit" if val >= 0 else "debit"
            amt_abs = f"{abs(val):.2f}"
            notes = str(t.get("memo", "")).replace("\r", "").replace("\n", " ")
            row = [
                t.get("date", ""),
                t.get("payee", ""),
                t.get("payee", ""),
                amt_abs,
                txn_type,
                t.get("category", ""),
                t.get("account", ""),
                "",
                notes,
            ]
            w.writerow(row)


# --- payee filter helper used in tests via App._run() ---
def apply_multi_payee_filters(
    txns: List[Dict[str, Any]],
    queries: List[str],
    mode: str = "contains",
    case_sensitive: bool = False,
    combine: str = "any",
) -> List[Dict[str, Any]]:
    # Minimal local implementation to avoid importing the whole convert tab.
    def local_filter(tlist: list[Dict[str, Any]], q: str) -> list[Dict[str, Any]]:
        q = str(q or "")
        if not q:
            return tlist
        if mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            return [t for t in tlist if re.search(q, t.get("payee", ""), flags)]
        if mode == "glob":
            # turn glob-ish to regex
            pattern = "^" + re.escape(q).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            flags = (
                0
                if (case_sensitive or any(ch.isupper() for ch in q))
                else re.IGNORECASE
            )
            return [t for t in tlist if re.search(pattern, t.get("payee", ""), flags)]

        # plain textual modes
        def cmp(s: str):
            return s if case_sensitive else s.lower()

        qcmp = cmp(q)

        def match(payee: str):
            p = cmp(payee)
            if mode == "exact":
                return p == qcmp
            if mode == "startswith":
                return p.startswith(qcmp)
            if mode == "endswith":
                return p.endswith(qcmp)
            return qcmp in p  # contains

        return [t for t in tlist if match(str(t.get("payee", "")))]

    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    if not queries:
        return txns

    if combine == "all":
        cur = list(txns)
        for q in queries:
            cur = local_filter(cur, q)
        return cur
    # any (union)
    seen: set[int] = set()
    out: list[Dict[str, Any]] = []
    for q in queries:
        subset = local_filter(txns, q)
        for t in subset:
            tid = id(t)
            if tid not in seen:
                seen.add(tid)
                out.append(t)
    return out
