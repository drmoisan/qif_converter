# qif_converter/match_excel.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Iterable
from difflib import SequenceMatcher
import pandas as pd
import re

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

# ---------------- Category extraction & matching ----------------

def extract_qif_categories(txns: List[Dict[str, Any]]) -> List[str]:
    """
    Collect categories from txns and splits, dedupe case-insensitively,
    preserve first-seen casing, drop blanks, and sort alphabetically (case-insensitive).
    """
    first_by_lower: Dict[str, str] = {}

    def _add(cat: str):
        s = (cat or "").strip()
        if not s:
            return
        key = s.lower()
        # keep first-seen casing for that lowercase key
        if key not in first_by_lower:
            first_by_lower[key] = s

    for t in txns:
        _add(t.get("category", ""))
        for s in t.get("splits") or []:
            _add(s.get("category", ""))

    # Return values sorted case-insensitively
    return sorted(first_by_lower.values(), key=lambda v: v.lower())

def extract_excel_categories(xlsx_path: Path, col_name: str = "Canonical MECE Category") -> List[str]:
    """Load Excel and return unique, sorted category names from the given column (case-insensitive dedupe)."""
    df = pd.read_excel(xlsx_path)
    if col_name not in df.columns:
        raise ValueError(f"Excel missing '{col_name}' column.")

    first_by_lower: Dict[str, str] = {}
    for v in df[col_name].dropna().astype(str):
        s = v.strip()
        if not s:
            continue
        key = s.lower()
        if key not in first_by_lower:
            first_by_lower[key] = s

    return sorted(first_by_lower.values(), key=lambda s: s.lower())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(a=a.lower().strip(), b=b.lower().strip()).ratio()

def fuzzy_autopairs(
    qif_cats: List[str],
    excel_cats: List[str],
    threshold: float = 0.84,
) -> Tuple[List[Tuple[str, str, float]], List[str], List[str]]:
    """
    Greedy one-to-one fuzzy matching:
      - considers all pairs >= threshold similarity
      - picks highest ratio first, then alphabetical tie-breakers
    Returns: (pairs [(qif, excel, score)], unmatched_qif, unmatched_excel)
    """
    candidates: List[Tuple[float, str, str]] = []
    for q in qif_cats:
        for e in excel_cats:
            r = _ratio(q, e)
            if r >= threshold:
                candidates.append((r, q, e))
    candidates.sort(key=lambda x: (-x[0], x[1].lower(), x[2].lower()))

    used_q, used_e = set(), set()
    pairs: List[Tuple[str, str, float]] = []
    for r, q, e in candidates:
        if q in used_q or e in used_e:
            continue
        pairs.append((q, e, r))
        used_q.add(q)
        used_e.add(e)

    unmatched_q = [q for q in qif_cats if q not in used_q]
    unmatched_e = [e for e in excel_cats if e not in used_e]
    return pairs, unmatched_q, unmatched_e

class CategoryMatchSession:
    """
    Manages category name mapping (Excel → QIF):
      - qif_cats: canonical names from QIF
      - excel_cats: names from Excel
      - mapping: excel_name -> qif_name
    """
    def __init__(self, qif_cats: List[str], excel_cats: List[str]):
        self.qif_cats = list(qif_cats)
        self.excel_cats = list(excel_cats)
        self.mapping: Dict[str, str] = {}

    def auto_match(self, threshold: float = 0.84):
        pairs, _, _ = fuzzy_autopairs(self.qif_cats, self.excel_cats, threshold)
        for qif_name, excel_name, _score in [(p[0], p[1], p[2]) for p in pairs]:
            self.mapping[excel_name] = qif_name

    def manual_match(self, excel_name: str, qif_name: str) -> Tuple[bool, str]:
        if excel_name not in self.excel_cats:
            return False, "Excel category not in list."
        if qif_name not in self.qif_cats:
            return False, "QIF category not in list."
        # ensure one-to-one by removing any other excel that mapped to this qif_name
        for k, v in list(self.mapping.items()):
            if v == qif_name and k != excel_name:
                self.mapping.pop(k, None)
        self.mapping[excel_name] = qif_name
        return True, "Matched."

    def manual_unmatch(self, excel_name: str) -> bool:
        return self.mapping.pop(excel_name, None) is not None

    def unmatched(self) -> Tuple[List[str], List[str]]:
        used_q = set(self.mapping.values())
        used_e = set(self.mapping.keys())
        uq = [q for q in self.qif_cats if q not in used_q]
        ue = [e for e in self.excel_cats if e not in used_e]
        return uq, ue

    def apply_to_excel(
        self,
        xlsx_in: Path,
        xlsx_out: Optional[Path] = None,
        col_name: str = "Canonical MECE Category",
    ) -> Path:
        """
        Writes a new Excel with the Canonical MECE Category values replaced by
        mapped QIF names where a mapping exists. Unmapped rows remain unchanged.
        """
        df = pd.read_excel(xlsx_in)
        if col_name not in df.columns:
            raise ValueError(f"Excel missing '{col_name}' column.")
        def _map_cell(v):
            s = str(v).strip() if pd.notna(v) else ""
            return self.mapping.get(s, s)
        df[col_name] = df[col_name].map(_map_cell)
        out = xlsx_out or xlsx_in.with_name(xlsx_in.stem + "_normalized.xlsx")
        df.to_excel(out, index=False)
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

def build_matched_only_txns(session: "MatchSession") -> List[Dict[str, Any]]:
    """
    Return a new list of QIF transactions containing ONLY matched items:
      - Non-split txns included iff the txn itself is matched.
      - For split txns, include only the splits that are matched.
        If no split is matched (and the parent txn isn't matched as a whole),
        the txn is omitted entirely.

    This does NOT mutate session.txns; it returns a deep-ish copy suitable for write_qif().
    """
    from copy import deepcopy

    txns = deepcopy(session.txns)
    matched_keys = set(session.qif_to_excel.keys())
    out: List[Dict[str, Any]] = []

    for ti, t in enumerate(txns):
        splits = t.get("splits") or []
        # Case 1: txn has no splits → include only if whole-transaction matched
        if not splits:
            key = QIFItemKey(txn_index=ti, split_index=None)
            if key in matched_keys:
                out.append(t)
            continue

        # Case 2: txn has splits → include only matched splits (and/or whole if applicable)
        # (Whole-transaction matches are still represented at the txn level; but since the txn
        #  also has splits, we follow the "matched items" semantics and filter by split keys.)
        new_splits = []
        for si, s in enumerate(splits):
            key = QIFItemKey(txn_index=ti, split_index=si)
            if key in matched_keys:
                new_splits.append(s)
        if new_splits:
            t["splits"] = new_splits
            out.append(t)
        else:
            # If no split is matched, include only if the whole txn is matched (edge case)
            whole_key = QIFItemKey(txn_index=ti, split_index=None)
            if whole_key in matched_keys:
                # Parent matched (rare for a split txn) → keep txn but with original splits
                out.append(t)

    return out


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
