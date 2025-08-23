# qif_converter/gui/helpers.py
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Any, Optional
import re

# Project module is optional here; we use hasattr-guard in apply_multi_payee_filters
from qif_converter import qif_writer as mod

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

def filter_date_range(txns: List[Dict[str, Any]], start_str: str, end_str: str) -> List[Dict[str, Any]]:
    def _d(s):
        d = parse_date_maybe(s)
        return d.date() if d else None

    start = _d(start_str) if start_str else None
    end = _d(end_str) if end_str else None
    if not start and not end:
        return txns
    out = []
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

def local_filter_by_payee(txns, query, mode="contains", case_sensitive=False):
    if mode != "regex" and mode != "glob" and not case_sensitive:
        query_cmp = str(query).lower()
    else:
        query_cmp = str(query)
    out = []
    for t in txns:
        payee = t.get("payee", "")
        payee_cmp = payee if (case_sensitive or mode in ("regex","glob")) else payee.lower()
        match = False
        if mode == "contains":
            match = query_cmp in payee_cmp
        elif mode == "exact":
            match = payee_cmp == query_cmp
        elif mode == "startswith":
            match = payee_cmp.startswith(query_cmp)
        elif mode == "endswith":
            match = payee_cmp.endswith(query_cmp)
        elif mode == "glob":
            pattern = "^" + re.escape(query).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            smart_case = case_sensitive or any(ch.isalpha() and ch.isupper() for ch in query)
            flags = 0 if smart_case else re.IGNORECASE
            match = re.search(pattern, payee, flags) is not None
        elif mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            match = re.search(query, payee, flags) is not None
        if match:
            out.append(t)
    return out

def apply_multi_payee_filters(
    txns: List[Dict[str, Any]],
    queries: List[str],
    mode: str = "contains",
    case_sensitive: bool = False,
    combine: str = "any",
) -> List[Dict[str, Any]]:
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    if not queries:
        return txns

    def run_filter(tlist, q):
        if hasattr(mod, "filter_by_payee"):
            return [t for t in tlist if t in mod.filter_by_payee(
                tlist, q, mode=mode, case_sensitive=case_sensitive
            )]
        return local_filter_by_payee(tlist, q, mode=mode, case_sensitive=case_sensitive)

    if combine == "any":
        seen, out = set(), []
        for q in queries:
            subset = run_filter(txns, q)
            for t in subset:
                tid = id(t)
                if tid not in seen:
                    seen.add(tid)
                    out.append(t)
        return out
    else:
        cur = list(txns)
        for q in queries:
            cur = run_filter(cur, q)
        return cur

def _set_text(widget, text: str):
    try:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text or "")
        widget.configure(state="disabled")
    except Exception:
        pass

def _fmt_txn(t: dict) -> str:
    if not isinstance(t, dict):
        return str(t)
    def g(k, d=""):
        return str(t.get(k, d) or "")
    lines = [
        f"Date: {g('date')}",
        f"Amount: {g('amount')}",
        f"Payee: {g('payee')}",
        f"Category: {g('category')}",
        f"Memo: {g('memo')}",
        f"Transfer Account: {g('transfer_account')}",
    ]
    splits = t.get("splits") or []
    if splits:
        lines.append("Splits:")
        for i, s in enumerate(splits, 1):
            lines.append(f"  {i}. {str(s.get('category',''))} | {str(s.get('memo',''))} | {str(s.get('amount',''))}")
    return "\n".join(lines)

def _fmt_excel_row(row) -> str:
    if hasattr(row, "to_dict"):
        row = row.to_dict()
    if not isinstance(row, dict):
        return str(row)
    def g(c): return str(row.get(c, "") or "")
    cols = ["Date", "Amount", "Item", "Canonical MECE Category", "Categorization Rationale"]
    return "\n".join(f"{c}: {g(c)}" for c in cols)

# ---------- probe helpers ----------
from typing import Optional

def _looks_binary(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:4096]
    nul_fraction = sample.count(0) / len(sample)
    if nul_fraction > 0.10:
        return True
    printable = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13))
    return printable / len(sample) < 0.5

def _too_many_controls(s: str) -> bool:
    if not s:
        return False
    sample = s[:4096]
    controls = sum(1 for ch in sample if ord(ch) < 32 and ch not in ("\n", "\r", "\t"))
    return controls / max(1, len(sample)) > 0.10

def decode_best_effort(data: bytes) -> Optional[str]:
    if _looks_binary(data):
        return None
    for enc in ("utf-8", "utf-16le", "utf-16be", "latin-1"):
        try:
            s = data.decode(enc)
            if _too_many_controls(s):
                continue
            return s
        except Exception:
            continue
    return None
