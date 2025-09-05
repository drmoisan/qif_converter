# quicken_helper/data_model/excel/excel_transaction.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import total_ordering
from typing import TYPE_CHECKING, Iterable, List

from ..interfaces import ISplit, ITransaction, RecursiveDictStr
from ..q_wrapper import QTransaction
from .excel_row import ExcelRow
from .excel_txn_group import ExcelTxnGroup

# --------------------------- Concrete adapters ---------------------------


@total_ordering
@dataclass
class ExcelSplit:
    """Adapter for a single Excel row as a split line."""

    category: str
    amount: Decimal
    memo: str = ""
    tag: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        """Convert to a simple dict for easier serialization/debugging."""
        return {
            "category": self.category,
            "amount": str(self.amount),
            "memo": self.memo,
            "tag": self.tag,
            "rationale": self.rationale,
        }

    def emit_qif(self) -> str:
        raise NotImplementedError("ExcelSplit does not support QIF export")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ISplit):
            return NotImplemented
        return (
            self.category == other.category
            and self.amount == other.amount
            and self.tag == other.tag
            and self.memo == other.memo
        )

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.category, self.amount, self.tag, self.memo))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ISplit):
            return NotImplemented
        if self.category < other.category:
            return True
        elif self.category > other.category:
            return False
        elif self.tag < other.tag:
            return True
        elif self.tag > other.tag:
            return False
        elif self.amount < other.amount:
            return True
        elif self.amount > other.amount:
            return False
        return self.memo < other.memo


if TYPE_CHECKING:
    _is_i_split: type[ISplit] = ExcelSplit


# @total_ordering
# @dataclass
# class ExcelTransaction:
#     """Adapter exposing an Excel group as a single ITransaction."""

#     id: str
#     date: date
#     amount: Decimal
#     account: QAccount = field(default_factory=QAccount)
#     type: QifHeader = field(default_factory=lambda: QifHeader(""))
#     payee: str = ""
#     memo: str = ""
#     # When splits exist, parent category is typically empty in QIF semantics.
#     category: str = ""
#     # Use default_factory to avoid dataclass complaints about enum defaults.
#     cleared: EnumClearedStatus = field(
#         default_factory=lambda: EnumClearedStatus.UNKNOWN
#     )
#     splits: Optional[List[ISplit]] = None
#     action: Optional[str] = None  # Usually None for Excel-originated txns

#     # Add missing attributes for protocol compliance
#     action_chk: Optional[str] = None
#     tag: str = ""
#     security: Optional[str] = None

#     # Add missing methods for protocol compliance
#     @property
#     def is_valid(self) -> bool:
#         # Implement your own validation logic as needed
#         return True

#     @property
#     def security_exists(self) -> bool:
#         return self.security is not None and self.security != ""

#     @property
#     def splits_exist(self) -> bool:
#         return bool(self.splits)

#     def emit_category(self) -> str:
#         """Emit the transaction's category for export."""
#         raise NotImplementedError("ExcelTransaction does not support QIF export")

#     def emit_qif(self) -> str:
#         """Emit the transaction in QIF format (stub implementation)."""
#         raise NotImplementedError("ExcelTransaction does not support QIF export")

#     def __lt__(self, other: object) -> bool:
#         if not isinstance(other, ITransaction):
#             return NotImplemented
#         return (self.date, self.amount, self.payee) < (other.date, other.amount, other.payee)

#     def __eq__(self, other:object) -> bool:
#         if not isinstance(other, ITransaction):
#             return NotImplemented
#         return (self.date, self.amount, self.payee) == (other.date, other.amount, other.payee)


# if TYPE_CHECKING:
#     _is_i_transaction: type[ITransaction] = ExcelTransaction


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
    txn: QTransaction = QTransaction()
    txn.amount = group.total_amount

    rows: Iterable[ExcelRow] = getattr(group, "rows", ()) or ()

    # Payee: first non-empty item
    payee_candidates = set(
        [
            payee
            for r in rows
            if (payee := getattr(r, "item", "").strip()) and isinstance(payee, str)
        ]
    )
    if len(payee_candidates) == 1:
        txn.payee = payee_candidates.pop()
    if len(payee_candidates) > 1:
        txn.payee = str.join(" | ", payee_candidates)

    # This is the wrong logic. Should be in splits
    # # Memo: distinct rationales, joined
    # rat_list = [
    #     getattr(r, "rationale", "") for r in rows if getattr(r, "rationale", "")
    # ]
    # preserve order while deduping
    # seen: set[str] = set()
    # uniq_rats: List[str] = []
    # for r in rat_list:
    #     if r not in seen:
    #         seen.add(r)
    #         uniq_rats.append(r)
    # memo = "; ".join(uniq_rats)

    # Splits: one per row
    split_list: List[ISplit] = []
    for r in rows:
        amt = r.amount
        # Prefer row.item as the line memo; fall back to rationale if item is empty.
        line_memo = getattr(r, "item", "") or getattr(r, "rationale", "")
        split_list.append(
            ExcelSplit(
                category=getattr(r, "category", "") or "", memo=line_memo, amount=amt
            )
        )

    # Parent category: leave empty when we have splits; otherwise can mirror a single-row category.
    parent_category = ""
    if not split_list:
        # No rows → keep empty; if you prefer to propagate a group-level category, add it here.
        parent_category = ""
    elif len(split_list) == 1:
        # Single split: you may choose to bubble up its category (optional).
        # parent_category = split_list[0].category
        parent_category = ""  # keep empty for consistency with split semantics

    return txn
    # return ExcelTransaction(
    #     id=str(getattr(group, "gid", "")),
    #     date=getattr(group, "date"),
    #     amount=total,
    #     payee=payee,
    #     memo=memo,
    #     category=parent_category,
    #     splits=split_list or None,
    #     # cleared defaults to UNKNOWN; action remains None
    # )
