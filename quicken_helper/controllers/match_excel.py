"""
Excel↔QIF matching helpers.

This module provides utilities to ingest/normalize an Excel categorization sheet,
flatten QIF transactions into matchable views, perform fuzzy category pairing,
and drive an end-to-end merge/update of QIF transactions using Excel as the
source of truth.

Primary responsibilities:
• Load Excel rows into `ExcelRow` records and group them into `ExcelTxnGroup`s.
• Flatten QIF transactions (and splits) into `QIFTxnView`s for matching.
• Extract and fuzzy-match category names across data sources.
• Build a “matched-only” QIF view without mutating the source list.
• Orchestrate a full merge (parse → match → apply updates → write).
"""

# quicken_helper/controllers/match_excel.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

# We re-use your parser and writer
# from . import qif_to_csv as base
import quicken_helper as base
from quicken_helper.controllers.match_helpers import (
    _to_date,
    to_decimal,
)
from quicken_helper.controllers.match_session import MatchSession
from quicken_helper.data_model.excel.excel_row import ExcelRow
from quicken_helper.data_model.excel.excel_txn_group import ExcelTxnGroup

# from match_session import MatchSession
from quicken_helper.legacy.qif_item_key import QIFItemKey
from quicken_helper.legacy.qif_txn_view import QIFTxnView

# --- Loading Excel (rows, then grouped by TxnID) ----------------------------


def load_excel_rows(path: Path) -> List[ExcelRow]:
    """Load and validate an Excel categorization sheet.

    Parameters
    ----------
    path : Path
        File path to the Excel workbook. Expected columns:
        ['TxnID', 'Date', 'Amount', 'Item', 'Canonical MECE Category', 'Categorization Rationale'].

    Returns
    -------
    List[ExcelRow]
        One `ExcelRow` per non-header row with strict types:
        date → datetime.date (via `_parse_date`), amount → Decimal (via `_to_decimal`).

    Raises
    ------
    ValueError
        If any required column is missing.

    Notes
    -----
    - Trims string fields; preserves the original row index for deterministic ordering.
    - Requires pandas (and an Excel engine such as openpyxl).
    """
    df = pd.read_excel(path)
    needed = [
        "TxnID",
        "Date",
        "Amount",
        "Item",
        "Canonical MECE Category",
        "Categorization Rationale",
    ]
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
            dval = _to_date(str(d))

        rows.append(
            ExcelRow(
                idx=int(i),
                txn_id=str(r["TxnID"]).strip(),
                date=dval,
                amount=to_decimal(r["Amount"]),
                memo=str(r["Item"] or "").strip(),
                category=str(r["Canonical MECE Category"] or "").strip(),
                rationale=str(r["Categorization Rationale"] or "").strip(),
            )
        )
    return rows


def group_excel_rows(rows: List[ExcelRow]) -> List[ExcelTxnGroup]:
    """Group `ExcelRow`s by `TxnID` into `ExcelTxnGroup`s.

    The grouping is deterministic: rows within a group keep their original order (by `idx`),
    the group `date` is the earliest row date, and `total_amount` is an exact Decimal sum.

    Parameters
    ----------
    rows : List[ExcelRow]
        Parsed rows from `load_excel_rows`.

    Returns
    -------
    List[ExcelTxnGroup]
        One group per unique `TxnID`, each containing an immutable tuple of member rows.
    """
    by_id: Dict[str, List[ExcelRow]] = {}
    for r in rows:
        by_id.setdefault(r.txn_id, []).append(r)
    groups: List[ExcelTxnGroup] = []
    for gid, items in by_id.items():
        items_sorted = sorted(items, key=lambda r: r.idx)
        total = sum((r.amount for r in items_sorted), Decimal("0"))
        first_date = min((r.date for r in items_sorted))
        groups.append(
            ExcelTxnGroup(
                gid=gid,
                date=first_date,
                total_amount=total,
                rows=tuple(items_sorted),
            )
        )
    # Stable order by date then gid
    groups.sort(key=lambda g: (g.date, g.gid))
    return groups


# --- Flatten QIF into matchable items (transaction-level) -------------------


def _txn_amount(t: Dict[str, Any]) -> Decimal:
    """Return the Decimal amount for a QIF transaction dict.

    If the transaction has `splits`, returns the sum of split amounts; otherwise returns
    the transaction's top-level `amount`.

    Parameters
    ----------
    t : Dict[str, Any]
        Raw QIF transaction mapping.

    Returns
    -------
    Decimal
        The computed amount.

    Raises
    ------
    Exception
        If amount strings cannot be coerced to `Decimal` by `_to_decimal`.
    """
    splits = t.get("splits") or []
    if splits:
        total = sum((to_decimal(s.get("amount", "0")) for s in splits), Decimal("0"))
        return total
    return to_decimal(t.get("amount", "0"))


# changed from _flatten_qif_txns
def _flatten_qif_txns(txns: List[Dict[str, Any]]) -> List[QIFTxnView]:
    """Flatten raw QIF transactions into matchable `QIFTxnView`s.

    Split-aware behavior:
    - If a transaction has splits, emit one view per split with a `QIFItemKey(txn_index, split_index)`.
    - If there are no splits, emit a single view with `split_index=None`.

    Transactions with an unparseable date or amount are skipped.

    Parameters
    ----------
    txns : List[Dict[str, Any]]
        Raw QIF transaction dicts (shape as produced by the parser).

    Returns
    -------
    List[QIFTxnView]
        Per-split/per-transaction normalized views (date, amount, payee, memo, category).
    """
    out: List[QIFTxnView] = []
    for ti, t in enumerate(txns):
        # Defensive: skip any record that doesn't look like a transaction
        # (must have a parseable date; amount may be on txn or splits)
        try:
            t_date = _to_date(t.get("date", ""))
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
                    amt = to_decimal(s.get("amount", "0"))
                except Exception:
                    # If split amount isn't parseable, skip this split
                    continue
                out.append(
                    QIFTxnView(
                        key=QIFItemKey(txn_index=ti, split_index=si),
                        date=t_date,
                        amount=amt,
                        payee=payee,
                        memo=s.get("memo", ""),
                        category=s.get("category", ""),
                    )
                )
        else:
            # No splits → use the txn amount
            try:
                amt = to_decimal(t.get("amount", "0"))
            except Exception:
                # Can't parse txn amount → skip this txn
                continue
            out.append(
                QIFTxnView(
                    key=QIFItemKey(txn_index=ti, split_index=None),
                    date=t_date,
                    amount=amt,
                    payee=payee,
                    memo=memo,
                    category=cat,
                )
            )
    return out


# ---------------- Category extraction & matching ----------------


def extract_qif_categories(txns: List[Dict[str, Any]]) -> List[str]:
    """Collect unique category names from QIF transactions and their splits.

    Parameters
    ----------
    txns : List[Dict[str, Any]]
        Raw QIF transaction dicts.

    Returns
    -------
    List[str]
        Case-insensitively de-duplicated and sorted category names (first-seen casing retained).
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


def extract_excel_categories(
    xlsx_path: Path, col_name: str = "Canonical MECE Category"
) -> List[str]:
    """Load Excel and return unique category names from a target column.

    Parameters
    ----------
    xlsx_path : Path
        Path to the Excel workbook.
    col_name : str, optional
        Column to extract from; defaults to "Canonical MECE Category".

    Returns
    -------
    List[str]
        Case-insensitively de-duplicated and sorted category names.

    Raises
    ------
    ValueError
        If the requested column does not exist.
    """
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
    """Case-insensitive similarity ratio between two strings.

    Returns
    -------
    float
        A value in [0.0, 1.0] from `difflib.SequenceMatcher`.
    """
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
    Returns: (pairs [(data_model, excel, score)], unmatched_qif, unmatched_excel)
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
    """Build a QIF transaction list containing only matched items.

    This does not mutate `session.txns`. Two behaviors are supported:
    1) **Group mode** (preferred): include a transaction if its *whole-transaction* key
       is matched (via `session.qif_to_excel_group`).
    2) **Legacy split mode**: include only matched splits for split transactions; include
       the whole transaction if its top-level key was matched.

    Parameters
    ----------
    session : MatchSession
        An initialized session after matching.

    Returns
    -------
    List[Dict[str, Any]]
        A new list of QIF transaction dicts limited to matched content.
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
) -> Tuple[
    List[Tuple[QIFTxnView, ExcelTxnGroup, int]], List[QIFTxnView], List[ExcelTxnGroup]
]:
    """End-to-end helper: parse → load/group Excel → auto-match → apply → write QIF.

    Parameters
    ----------
    qif_in : Path
        Input QIF file path.
    xlsx : Path
        Excel categorization workbook path.
    qif_out : Path
        Output QIF path to write merged transactions.
    encoding : str, optional
        Input encoding used for parsing the QIF; default "utf-8".

    Returns
    -------
    Tuple[List[Tuple[QIFTxnView, ExcelTxnGroup, int]], List[QIFTxnView], List[ExcelTxnGroup]]
        (matched_pairs, unmatched_qif_views, unmatched_excel_groups).

    Notes
    -----
    - Callers may insert manual match/unmatch operations between `auto_match()` and
      `apply_updates()` if needed.
    - The original `txns` list is updated in place prior to writing.
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
