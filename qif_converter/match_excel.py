# qif_converter/match_excel.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
import pandas as pd

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


# --- Data types (Excel rows & groups; QIF txn views) -------------------------

@dataclass(frozen=True)
class ExcelRow:
    idx: int                    # 0-based row index from Excel (after header)
    txn_id: str                 # groups rows into a single transaction
    date: date
    amount: Decimal
    item: str
    category: str
    rationale: str


@dataclass(frozen=True)
class ExcelTxnGroup:
    """
    Represents one Excel 'transaction' (group of split rows with the same TxnID).
    The 'date' is taken as the earliest date among the group's rows (stable & deterministic).
    """
    gid: str
    date: date
    total_amount: Decimal
    rows: Tuple[ExcelRow, ...]  # immutable tuple for safety


@dataclass(frozen=True)
class QIFItemKey:
    """Uniquely identifies either a whole transaction or one of its splits."""
    txn_index: int             # index into original txns list
    split_index: Optional[int]  # None = whole transaction; otherwise 0..n-1

    def is_split(self) -> bool:
        return self.split_index is not None


@dataclass
class QIFTxnView:
    """
    Transaction-level view used for matching. We always match whole transactions,
    not individual QIF splits. If a txn has splits, its 'amount' is the sum of splits;
    otherwise it is the txn amount field.
    """
    key: QIFItemKey            # split_index must be None here
    date: date
    amount: Decimal
    payee: str
    memo: str
    category: str


# --- Loading Excel (rows, then grouped by TxnID) ----------------------------

def load_excel_rows(path: Path) -> List[ExcelRow]:
    """
    Load Excel with columns:
      [TxnID, Date, Amount, Item, Canonical MECE Category, Categorization Rationale]
    Dependencies: pandas + openpyxl
    """
    df = pd.read_excel(path)
    needed = ["TxnID", "Date", "Amount", "Item", "Canonical MECE Category", "Categorization Rationale"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Excel is missing columns: {missing}")

    rows: List[ExcelRow] = []
    for i, r in df.iterrows():
        d = r["Date"]
        if isinstance(d, (datetime,)):
            dval = d.date()
        elif isinstance(d, date):
            dval = d
        else:
            dval = _parse_date(str(d))

        rows.append(ExcelRow(
            idx=int(i),
            txn_id=str(r["TxnID"]).strip(),
            date=dval,
            amount=_to_decimal(r["Amount"]),
            item=str(r["Item"] or "").strip(),
            category=str(r["Canonical MECE Category"] or "").strip(),
            rationale=str(r["Categorization Rationale"] or "").strip(),
        ))
    return rows


def group_excel_rows(rows: List[ExcelRow]) -> List[ExcelTxnGroup]:
    """
    Group rows by TxnID into ExcelTxnGroup(s). Total amount is the sum of row amounts.
    Date is the earliest row date for determinism. Order rows by original idx.
    """
    by_id: Dict[str, List[ExcelRow]] = {}
    for r in rows:
        by_id.setdefault(r.txn_id, []).append(r)
    groups: List[ExcelTxnGroup] = []
    for gid, items in by_id.items():
        items_sorted = sorted(items, key=lambda r: r.idx)
        total = sum((r.amount for r in items_sorted), Decimal("0"))
        first_date = min((r.date for r in items_sorted))
        groups.append(ExcelTxnGroup(
            gid=gid,
            date=first_date,
            total_amount=total,
            rows=tuple(items_sorted),
        ))
    # Stable order by date then gid
    groups.sort(key=lambda g: (g.date, g.gid))
    return groups


# --- Flatten QIF into matchable items (transaction-level) -------------------

def _txn_amount(t: Dict[str, Any]) -> Decimal:
    splits = t.get("splits") or []
    if splits:
        total = sum((_to_decimal(s.get("amount", "0")) for s in splits), Decimal("0"))
        return total
    return _to_decimal(t.get("amount", "0"))


def _flatten_qif_txns(txns: List[Dict[str, Any]]) -> List[QIFTxnView]:
    out: List[QIFTxnView] = []
    for ti, t in enumerate(txns):
        t_date = _qif_date_to_date(t.get("date", ""))
        payee = t.get("payee", "")
        memo = t.get("memo", "")
        cat = t.get("category", "")
        amt = _txn_amount(t)
        out.append(QIFTxnView(
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
    Holds QIF txns + Excel groups (by TxnID), does auto-matching with one-to-one
    constraint at the TRANSACTION level, supports manual match/unmatch, and
    applies updates to QIF (overwriting splits from Excel).
    """

    def __init__(self, txns: List[Dict[str, Any]], excel_rows: List[ExcelRow] | None = None, excel_groups: List[ExcelTxnGroup] | None = None):
        self.txns = txns
        self.txn_views = _flatten_qif_txns(txns)
        if excel_groups is not None:
            self.excel_groups = list(excel_groups)
        else:
            self.excel_groups = group_excel_rows(excel_rows or [])

        # Internal match state
        # map whole-transaction key -> excel group index
        self.qif_to_excel: Dict[QIFItemKey, int] = {}
        self.excel_to_qif: Dict[int, QIFItemKey] = {}

    # --- Auto match

    def auto_match(self) -> None:
        """
        Build greedy best matches with:
          - total amount must be equal (exact)
          - date within ±3 days
          - lowest date delta wins (0 beats 1 beats 2 beats 3)
        One-to-one: each QIF transaction and each Excel group used at most once.
        """
        candidates: List[Tuple[int, int, int]] = []
        by_amount: Dict[Decimal, List[int]] = {}
        for gi, g in enumerate(self.excel_groups):
            by_amount.setdefault(g.total_amount, []).append(gi)

        for qi, q in enumerate(self.txn_views):
            for gi in by_amount.get(q.amount, []):
                g = self.excel_groups[gi]
                cost = _candidate_cost(q.date, g.date)
                if cost is None:
                    continue
                candidates.append((cost, qi, gi))

        # sort by cost (0..3), then by indices for determinism
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))

        used_q: set[int] = set()
        used_g: set[int] = set()
        for cost, qi, gi in candidates:
            if qi in used_q or gi in used_g:
                continue
            qkey = self.txn_views[qi].key
            self.qif_to_excel[qkey] = gi
            self.excel_to_qif[gi] = qkey
            used_q.add(qi)
            used_g.add(gi)

    # --- Introspection

    def matched_pairs(self) -> List[Tuple[QIFTxnView, ExcelTxnGroup, int]]:
        """
        Return list of matched (QIFTxnView, ExcelTxnGroup, date_cost).
        """
        out = []
        for qi, q in enumerate(self.txn_views):
            gi = self.qif_to_excel.get(q.key)
            if gi is None:
                continue
            g = self.excel_groups[gi]
            cost = _candidate_cost(q.date, g.date)
            out.append((q, g, 0 if cost is None else cost))
        return out

    def unmatched_qif(self) -> List[QIFTxnView]:
        return [q for q in self.txn_views if q.key not in self.qif_to_excel]

    def unmatched_excel(self) -> List[ExcelTxnGroup]:
        return [g for gi, g in enumerate(self.excel_groups) if gi not in self.excel_to_qif]

    # --- Reasons / manual matching

    def nonmatch_reason(self, q: QIFTxnView, g: ExcelTxnGroup) -> str:
        if q.amount != g.total_amount:
            return f"Amount differs (QIF {q.amount} vs Excel {g.total_amount})."
        c = _candidate_cost(q.date, g.date)
        if c is None:
            return f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel {g.date.isoformat()})."
        if q.key in self.qif_to_excel and self.qif_to_excel[q.key] != self._group_index(g):
            return "QIF item is already matched."
        gi = self._group_index(g)
        if gi in self.excel_to_qif and self.excel_to_qif[gi] != q.key:
            return "Excel row is already matched."
        # Eligible, just not chosen by greedy (e.g., higher day distance)
        if c > 0:
            return f"Auto-match preferred a closer date (day diff = {c})."
        return "Auto-match selected another candidate."

    def manual_match(self, qkey: QIFItemKey, excel_group_index: int) -> Tuple[bool, str]:
        """
        Force a match between a QIF transaction and an Excel group (by index).
        Returns (ok, message). If not ok, message explains why.
        """
        # Find the QIF txn view
        try:
            q = next(x for x in self.txn_views if x.key == qkey)
        except StopIteration:
            return False, "QIF item key not found."

        if excel_group_index < 0 or excel_group_index >= len(self.excel_groups):
            return False, "Excel group index out of range."
        g = self.excel_groups[excel_group_index]

        # Check eligibility
        if q.amount != g.total_amount:
            return False, f"Amount differs (QIF {q.amount} vs Excel {g.total_amount})."
        if _candidate_cost(q.date, g.date) is None:
            return False, f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel {g.date.isoformat()})."

        # Unmatch any existing links
        self._unmatch_qkey(qkey)
        self._unmatch_excel(excel_group_index)

        # Link
        self.qif_to_excel[qkey] = excel_group_index
        self.excel_to_qif[excel_group_index] = qkey
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
        gi = self.qif_to_excel.pop(qkey, None)
        if gi is None:
            return False
        self.excel_to_qif.pop(gi, None)
        return True

    def _unmatch_excel(self, excel_idx: int) -> bool:
        qkey = self.excel_to_qif.pop(excel_idx, None)
        if qkey is None:
            return False
        self.qif_to_excel.pop(qkey, None)
        return True

    def _group_index(self, g: ExcelTxnGroup) -> int:
        # helper to find group index (identity by object; fallback by gid/date/total)
        try:
            return self.excel_groups.index(g)
        except ValueError:
            for i, gg in enumerate(self.excel_groups):
                if gg.gid == g.gid and gg.date == g.date and gg.total_amount == g.total_amount:
                    return i
            return -1

    # --- Applying updates ----------------------------------------------------

    def apply_updates(self) -> None:
        """
        Update in-memory QIF txns based on current matches:
          - OVERWRITE splits with Excel group's rows:
              splits := [ {category, memo=item, amount} ... ]
          - Clear txn-level category (since it now has splits).
          - Leave existing txn memo as-is.
        """
        for q, g, _cost in self.matched_pairs():
            t = self.txns[q.key.txn_index]
            # Build new splits from Excel rows
            new_splits = []
            for r in g.rows:
                new_splits.append({
                    "category": r.category,
                    "memo": r.item,
                    "amount": r.amount,
                })
            t["splits"] = new_splits
            # Clear txn-level category, because the transaction now has explicit splits
            if "category" in t:
                t["category"] = ""
            # Sync txn amount to the sum of splits (safer for writers)
            t["amount"] = sum((s["amount"] for s in new_splits), Decimal("0"))


# --- Convenience end-to-end ---------------------------------------------

def build_matched_only_txns(session: "MatchSession") -> List[Dict[str, Any]]:
    """
    Return a new list of QIF transactions containing ONLY matched transactions
    (since matching is done at the txn level). For each included txn, its splits
    will already have been overwritten in `apply_updates()` to reflect Excel rows.

    This does NOT mutate session.txns; it returns a deep-ish copy suitable for write_qif().
    """
    from copy import deepcopy

    txns = deepcopy(session.txns)
    matched_keys = set(session.qif_to_excel.keys())
    out: List[Dict[str, Any]] = []

    for ti, t in enumerate(txns):
        key = QIFItemKey(txn_index=ti, split_index=None)
        if key in matched_keys:
            out.append(t)

    return out


def run_excel_qif_merge(
    qif_in: Path,
    xlsx: Path,
    qif_out: Path,
    encoding: str = "utf-8",
) -> Tuple[List[Tuple[QIFTxnView, ExcelTxnGroup, int]], List[QIFTxnView], List[ExcelTxnGroup]]:
    """
    High-level helper:
      - parse QIF
      - load Excel rows and group by TxnID
      - auto-match
      - (caller may then inspect unmatched lists, optionally call manual_match/unmatch)
      - apply updates
      - write new QIF at qif_out (never overwrite qif_in unless you pass same path explicitly)
    Returns (matched_pairs, unmatched_qif_items, unmatched_excel_rows)
    """
    txns = base.parse_qif(qif_in, encoding=encoding)
    excel_rows = load_excel_rows(xlsx)
    excel_groups = group_excel_rows(excel_rows)

    session = MatchSession(txns, excel_groups=excel_groups)
    session.auto_match()

    # Caller could do manual matching here if desired; this helper just goes through
    session.apply_updates()
    qif_out.parent.mkdir(parents=True, exist_ok=True)
    base.write_qif(txns, qif_out)

    return session.matched_pairs(), session.unmatched_qif(), session.unmatched_excel()
