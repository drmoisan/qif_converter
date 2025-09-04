# quicken_helper/data_model/excel/excel_transaction.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, List, Optional, TYPE_CHECKING

from quicken_helper.data_model.interfaces import ITransaction, ISplit, EnumClearedStatus
from quicken_helper.data_model.excel.excel_txn_group import ExcelTxnGroup
from quicken_helper.data_model.excel.excel_row import ExcelRow
from quicken_helper.utilities.converters_scalar import _to_decimal


# --------------------------- Concrete adapters ---------------------------

@dataclass(frozen=True)
class ExcelSplit:
    """Adapter for a single Excel row as a split line."""
    category: str
    amount: Decimal
    memo: str = ""
    tag: str = ""
    rationale: str = ""

if TYPE_CHECKING:
    _is_i_split: type[ISplit] = ExcelSplit


@dataclass(frozen=True)
class ExcelTransaction:
    """Adapter exposing an Excel group as a single ITransaction."""
    id: str
    date: date
    amount: Decimal
    payee: str = ""
    memo: str = ""
    # When splits exist, parent category is typically empty in QIF semantics.
    category: str = ""
    # Use default_factory to avoid dataclass complaints about enum defaults.
    cleared: EnumClearedStatus = field(default_factory=lambda: EnumClearedStatus.UNKNOWN)
    splits: Optional[List[ISplit]] = None
    action: Optional[str] = None  # Usually None for Excel-originated txns

if TYPE_CHECKING:
    _is_i_transaction: type[ITransaction] = ExcelTransaction


# ------------------------------ Mapper ----------------------------------

def map_group_to_excel_txn(group: ExcelTxnGroup) -> ITransaction:
    """
    Convert an ExcelTxnGroup (with one or more ExcelRow items) into a single ITransaction.

    Mapping rules:
      • id      ← group.gid
      • date    ← group.date
      • amount  ← group.total_amount (coerced to Decimal)
      • payee   ← first non-empty row.item (fallback: "")
      • memo    ← unique row.rationale values joined with "; " (fallback: "")
      • splits  ← one ExcelSplit per row: {category=row.category, memo=row.item or row.rationale, amount=row.amount}
      • category (parent) left blank when splits present (typical QIF behavior).
      • cleared ← EnumClearedStatus.UNKNOWN
      • action  ← None (Excel groups generally have no investment action)
    """
    # Defensive coercions (support Decimal/str totals)
    total: Decimal
    if isinstance(group.total_amount, Decimal):
        total = group.total_amount
    else:
        total = _to_decimal(group.total_amount)

    rows: Iterable[ExcelRow] = getattr(group, "rows", ()) or ()

    # Payee: first non-empty item
    payee_candidates = (getattr(r, "item", "") for r in rows)
    payee = next((p for p in payee_candidates if p), "")

    # Memo: distinct rationales, joined
    rat_list = [getattr(r, "rationale", "") for r in rows if getattr(r, "rationale", "")]
    # preserve order while deduping
    seen = set()
    uniq_rats: List[str] = []
    for r in rat_list:
        if r not in seen:
            seen.add(r)
            uniq_rats.append(r)
    memo = "; ".join(uniq_rats)

    # Splits: one per row
    split_list: List[ISplit] = []
    for r in rows:
        amt = r.amount if isinstance(r.amount, Decimal) else _to_decimal(r.amount)
        # Prefer row.item as the line memo; fall back to rationale if item is empty.
        line_memo = getattr(r, "item", "") or getattr(r, "rationale", "")
        split_list.append(ExcelSplit(category=getattr(r, "category", "") or "", memo=line_memo, amount=amt))

    # Parent category: leave empty when we have splits; otherwise can mirror a single-row category.
    parent_category = ""
    if not split_list:
        # No rows → keep empty; if you prefer to propagate a group-level category, add it here.
        parent_category = ""
    elif len(split_list) == 1:
        # Single split: you may choose to bubble up its category (optional).
        # parent_category = split_list[0].category
        parent_category = ""  # keep empty for consistency with split semantics

    return ExcelTransaction(
        id=str(getattr(group, "gid", "")),
        date=getattr(group, "date"),
        amount=total,
        payee=payee,
        memo=memo,
        category=parent_category,
        splits=split_list or None,
        # cleared defaults to UNKNOWN; action remains None
    )
