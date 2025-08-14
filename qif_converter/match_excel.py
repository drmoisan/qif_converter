# qif_converter/match_excel.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Iterable

# We re-use your parser and writer
from . import qif_to_csv as base

# --- Small helpers -----------------------------------------------------------

_DATE_FORMATS = ["%m/%d'%y", "%m/%d/%Y", "%Y-%m-%d"]

def _parse_date(s: str) -> date:
    s = (s or "").strip().replace("’", "'").replace("`", "'")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    # Fallback: allow ISO-like "YYYY/MM/DD"
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        raise ValueError(f"Unrecognized date: {s!r}")

def _qif_date_to_date(s: str) -> date:
    return _parse_date(s)

def _to_decimal(s: str | float | int | Decimal) -> Decimal:
    if isinstance(s, Decimal):
        return s
    if isinstance(s, (int, float)):
        return Decimal(str(s))
    txt = str(s or "").replace(",", "").replace("$", "").strip()
    if txt in {"", "+", "-"}:
        raise InvalidOperation(f"Empty amount: {s!r}")
    return Decimal(txt)

# --- Data types --------------------------------------------------------------

@dataclass(frozen=True)
class ExcelRow:
    idx: int                    # 0-based row index from Excel (after header)
    date: date
    amount: Decimal
    item: str
    category: str
    rationale: str

@dataclass(frozen=True)
class QIFItemKey:
    """Uniquely identifies either a whole transaction or one of its splits."""
    txn_index: int             # index into original txns list
    split_index: Optional[int] # None = whole transaction; otherwise 0..n-1

    def is_split(self) -> bool:
        return self.split_index is not None

@dataclass
class QIFItemView:
    key: QIFItemKey
    date: date
    amount: Decimal
    payee: str
    memo: str
    category: str

# --- Loading Excel -----------------------------------------------------------

def load_excel(path: Path) -> List[ExcelRow]:
    """
    Load Excel with columns:
      [Date, Amount, Item, Canonical MECE Category, Categorization Rationale]
    Dependencies: pandas + openpyxl
    """
    import pandas as pd  # local import to keep hard dep minimal at import time
    df = pd.read_excel(path)
    needed = ["Date", "Amount", "Item", "Canonical MECE Category", "Categorization Rationale"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Excel is missing columns: {missing}")

    rows: List[ExcelRow] = []
    for i, r in df.iterrows():
        d = r["Date"]
        if isinstance(d, (datetime, )):
            dval = d.date()
        elif isinstance(d, date):
            dval = d
        else:
            dval = _parse_date(str(d))

        rows.append(ExcelRow(
            idx=int(i),
            date=dval,
            amount=_to_decimal(r["Amount"]),
            item=str(r["Item"] or "").strip(),
            category=str(r["Canonical MECE Category"] or "").strip(),
            rationale=str(r["Categorization Rationale"] or "").strip(),
        ))
    return rows

# --- Flatten QIF into matchable items (txn or split) -------------------------

def _flatten_qif_items(txns: List[Dict[str, Any]]) -> List[QIFItemView]:
    out: List[QIFItemView] = []
    for ti, t in enumerate(txns):
        t_date = _qif_date_to_date(t.get("date", ""))
        payee = t.get("payee", "")
        memo = t.get("memo", "")
        cat = t.get("category", "")
        splits = t.get("splits") or []
        if splits:
            for si, s in enumerate(splits):
                amt = _to_decimal(s.get("amount", "0"))
                out.append(QIFItemView(
                    key=QIFItemKey(txn_index=ti, split_index=si),
                    date=t_date,
                    amount=amt,
                    payee=payee,
                    memo=s.get("memo", ""),
                    category=s.get("category", ""),
                ))
        else:
            amt = _to_decimal(t.get("amount", "0"))
            out.append(QIFItemView(
                key=QIFItemKey(txn_index=ti, split_index=None),
                date=t_date,
                amount=amt,
                payee=payee,
                memo=memo,
                category=cat,
            ))
    return out

# --- Matching engine ---------------------------------------------------------

def _candidate_cost(qif_date: date, excel_date: date) -> Optional[int]:
    """Return day-distance cost if within ±3 days, else None (not eligible). Lower is better."""
    delta = abs((qif_date - excel_date).days)
    if delta > 3:
        return None
    return delta  # 0 preferred, then 1,2,3

class MatchSession:
    """
    Holds QIF + Excel rows, does auto-matching with one-to-one constraint,
    supports manual match/unmatch, and applies updates to QIF.
    """

    def __init__(self, txns: List[Dict[str, Any]], excel_rows: List[ExcelRow]):
        self.txns = txns
        self.items = _flatten_qif_items(txns)
        self.excel = excel_rows

        # Internal match state
        self.qif_to_excel: Dict[QIFItemKey, int] = {}
        self.excel_to_qif: Dict[int, QIFItemKey] = {}

    # --- Auto match

    def auto_match(self) -> None:
        """
        Build greedy best matches with:
          - amount must be equal (exact)
          - date within ±3 days
          - lowest date delta wins (0 beats 1 beats 2 beats 3)
        One-to-one: each QIF item and each Excel row used at most once.
        """
        candidates: List[Tuple[int, int, int]] = []
        # Pre-index Excel by amount for speed
        by_amount: Dict[Decimal, List[int]] = {}
        for ei, er in enumerate(self.excel):
            by_amount.setdefault(er.amount, []).append(ei)

        for qi, q in enumerate(self.items):
            for ei in by_amount.get(q.amount, []):
                er = self.excel[ei]
                cost = _candidate_cost(q.date, er.date)
                if cost is None:
                    continue
                # (cost, qi, ei) for stable greedy
                candidates.append((cost, qi, ei))

        # sort by cost (0..3), then by indices to be deterministic
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))

        used_q: set[int] = set()
        used_e: set[int] = set()
        for cost, qi, ei in candidates:
            if qi in used_q or ei in used_e:
                continue
            qkey = self.items[qi].key
            self.qif_to_excel[qkey] = ei
            self.excel_to_qif[ei] = qkey
            used_q.add(qi)
            used_e.add(ei)

    # --- Introspection

    def matched_pairs(self) -> List[Tuple[QIFItemView, ExcelRow, int]]:
        """
        Return list of matched (QIFItemView, ExcelRow, date_cost).
        """
        out = []
        for qi, q in enumerate(self.items):
            ei = self.qif_to_excel.get(q.key)
            if ei is None:
                continue
            er = self.excel[ei]
            cost = _candidate_cost(q.date, er.date)
            out.append((q, er, 0 if cost is None else cost))
        return out

    def unmatched_qif(self) -> List[QIFItemView]:
        return [q for q in self.items if q.key not in self.qif_to_excel]

    def unmatched_excel(self) -> List[ExcelRow]:
        return [er for ei, er in enumerate(self.excel) if ei not in self.excel_to_qif]

    # --- Reasons / manual matching

    def nonmatch_reason(self, q: QIFItemView, er: ExcelRow) -> str:
        if q.amount != er.amount:
            return f"Amount differs (QIF {q.amount} vs Excel {er.amount})."
        c = _candidate_cost(q.date, er.date)
        if c is None:
            return f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel {er.date.isoformat()})."
        if q.key in self.qif_to_excel and self.qif_to_excel[q.key] != er.idx:
            return "QIF item is already matched."
        if er.idx in self.excel_to_qif and self.excel_to_qif[er.idx] != q.key:
            return "Excel row is already matched."
        # Eligible, just not chosen by greedy (e.g., higher day distance)
        if c > 0:
            return f"Auto-match preferred a closer date (day diff = {c})."
        return "Auto-match selected another candidate."

    def manual_match(self, qkey: QIFItemKey, excel_idx: int) -> Tuple[bool, str]:
        """
        Force a match between QIF item and Excel row.
        Returns (ok, message). If not ok, message explains why.
        """
        # Find the QIF view
        try:
            q = next(x for x in self.items if x.key == qkey)
        except StopIteration:
            return False, "QIF item key not found."

        if excel_idx < 0 or excel_idx >= len(self.excel):
            return False, "Excel index out of range."
        er = self.excel[excel_idx]

        # Check eligibility
        if q.amount != er.amount:
            return False, f"Amount differs (QIF {q.amount} vs Excel {er.amount})."
        if _candidate_cost(q.date, er.date) is None:
            return False, f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel {er.date.isoformat()})."

        # Unmatch any existing links
        self._unmatch_qkey(qkey)
        self._unmatch_excel(excel_idx)

        # Link
        self.qif_to_excel[qkey] = excel_idx
        self.excel_to_qif[excel_idx] = qkey
        return True, "Matched."

    def manual_unmatch(self, qkey: Optional[QIFItemKey] = None, excel_idx: Optional[int] = None) -> bool:
        """
        Remove an existing match (by either key).
        """
        if qkey is not None:
            return self._unmatch_qkey(qkey)
        if excel_idx is not None:
            return self._unmatch_excel(excel_idx)
        return False

    def _unmatch_qkey(self, qkey: QIFItemKey) -> bool:
        ei = self.qif_to_excel.pop(qkey, None)
        if ei is None:
            return False
        self.excel_to_qif.pop(ei, None)
        return True

    def _unmatch_excel(self, excel_idx: int) -> bool:
        qkey = self.excel_to_qif.pop(excel_idx, None)
        if qkey is None:
            return False
        self.qif_to_excel.pop(qkey, None)
        return True

    # --- Applying updates ----------------------------------------------------

    def apply_updates(self) -> None:
        """
        Update in-memory QIF txns based on current matches:
          - category ← Excel "Canonical MECE Category"
          - memo     ← Excel "Item"
        Split matches update the split; non-split matches update the txn.
        """
        for q, er, _cost in self.matched_pairs():
            t = self.txns[q.key.txn_index]
            if q.key.is_split():
                s = t.setdefault("splits", [])[q.key.split_index]  # type: ignore[index]
                s["category"] = er.category
                s["memo"] = er.item
            else:
                t["category"] = er.category
                t["memo"] = er.item

    # --- Convenience end-to-end ---------------------------------------------

def run_excel_qif_merge(
    qif_in: Path,
    xlsx: Path,
    qif_out: Path,
    encoding: str = "utf-8",
) -> Tuple[List[Tuple[QIFItemView, ExcelRow, int]], List[QIFItemView], List[ExcelRow]]:
    """
    High-level helper:
      - parse QIF
      - load Excel
      - auto-match
      - (caller may then inspect unmatched lists, optionally call manual_match/unmatch)
      - apply updates
      - write new QIF at qif_out (never overwrite qif_in unless you pass same path explicitly)
    Returns (matched_pairs, unmatched_qif_items, unmatched_excel_rows)
    """
    txns = base.parse_qif(qif_in, encoding=encoding)
    excel_rows = load_excel(xlsx)

    session = MatchSession(txns, excel_rows)
    session.auto_match()

    # Caller could do manual matching here if desired; this helper just goes through
    session.apply_updates()
    qif_out.parent.mkdir(parents=True, exist_ok=True)
    base.write_qif(txns, qif_out)

    return session.matched_pairs(), session.unmatched_qif(), session.unmatched_excel()
