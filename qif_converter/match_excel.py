# qif_converter/match_excel.py
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
import pandas as pd
from pandas import ExcelFile
from .excel_row import ExcelRow
from .excel_txn_group import ExcelTxnGroup
#from match_session import MatchSession
from .qif_item_key import QIFItemKey
from .qif_txn_view import QIFTxnView
# We re-use your parser and writer
#from . import qif_to_csv as base
import qif_converter as base
from .match_helpers import _DATE_FORMATS, _parse_date, _qif_date_to_date, _to_decimal
from .match_session import MatchSession

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

# changed from _flatten_qif_txns
def _flatten_qif_txns(txns: List[Dict[str, Any]]) -> List[QIFTxnView]:
    out: List[QIFTxnView] = []
    for ti, t in enumerate(txns):
        # Defensive: skip any record that doesn't look like a transaction
        # (must have a parseable date; amount may be on txn or splits)
        try:
            t_date = _qif_date_to_date(t.get("date", ""))
        except Exception:
            # Not a transaction (e.g., category list line sneaked in) → skip
            continue

        payee = t.get("payee", "")
        memo = t.get("memo", "")
        cat = t.get("category", "")
        splits = t.get("splits") or []
        if splits:
            for si, s in enumerate(splits):
                try:
                    amt = _to_decimal(s.get("amount", "0"))
                except Exception:
                    # If split amount isn't parseable, skip this split
                    continue
                out.append(QIFTxnView(
                    key=QIFItemKey(txn_index=ti, split_index=si),
                    date=t_date,
                    amount=amt,
                    payee=payee,
                    memo=s.get("memo", ""),
                    category=s.get("category", ""),
                ))
        else:
            # No splits → use the txn amount
            try:
                amt = _to_decimal(t.get("amount", "0"))
            except Exception:
                # Can't parse txn amount → skip this txn
                continue
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


# --- Matching engine ---------------------------------------------------------

def build_matched_only_txns(session: "MatchSession") -> List[Dict[str, Any]]:
    """
    Return a new list of QIF transactions containing ONLY matched transactions
    (group-mode) or matched items (legacy). Does not mutate session.txns.
    """
    from copy import deepcopy

    txns = deepcopy(session.txns)

    # --- Group-mode: include a txn iff its whole-transaction key is matched ---
    if session.excel_groups is not None:
        matched_txn_keys = set(session.qif_to_excel_group.keys())
        out: List[Dict[str, Any]] = []
        for ti, t in enumerate(txns):
            key = QIFItemKey(txn_index=ti, split_index=None)
            if key in matched_txn_keys:
                out.append(t)
        return out

    # --- Legacy (row) mode fallback (original behavior) ---
    matched_keys = set(session.qif_to_excel.keys())
    out: List[Dict[str, Any]] = []

    for ti, t in enumerate(txns):
        splits = t.get("splits") or []
        if not splits:
            key = QIFItemKey(txn_index=ti, split_index=None)
            if key in matched_keys:
                out.append(t)
            continue

        new_splits = []
        for si, s in enumerate(splits):
            key = QIFItemKey(txn_index=ti, split_index=si)
            if key in matched_keys:
                new_splits.append(s)
        if new_splits:
            t["splits"] = new_splits
            out.append(t)
        else:
            whole_key = QIFItemKey(txn_index=ti, split_index=None)
            if whole_key in matched_keys:
                out.append(t)

    return out


def run_excel_qif_merge(
    self,
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

