# quicken_helper/data_model/excel/excel_transaction.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Sequence

from quicken_helper.utilities import to_decimal

from ..interfaces import (
    EnumClearedStatus,
    IComparable,
    IEquatable,
    ISplit,
    IToDict,
    ITransaction,
)
from ..q_wrapper import QAccount, QSecurity, QTransaction
from .excel_row import ExcelRow
from .excel_split import ExcelSplit
from .excel_txn_group import ExcelTxnGroup

# region Disabled
# --------------------------- Concrete adapters ---------------------------
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
# endregion Disabled


@dataclass
class ExcelTransaction(QTransaction):
    rationale: str = ""

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash(
            (
                self.account,
                self.type,
                self.date,
                self.payee,
                self.amount,
                self.memo,
                self.category,
                self.rationale,
                self.tag,
                tuple(sorted(self.splits)),
            )
        )


if TYPE_CHECKING:
    _is_i_transaction: type[ITransaction] = ExcelTransaction
    _is_icomparable: type[IComparable] = ExcelTransaction
    _is_iquatable: type[IEquatable] = ExcelTransaction
    _is_idict: type[IToDict] = ExcelTransaction


_MISSING_DATE = date(1900, 1, 1)
_MISSING_SECURITY = QSecurity("", Decimal(0), Decimal(0), Decimal(0), Decimal(0))


def map_group_to_excel_txn(group: ExcelTxnGroup) -> ExcelTransaction:
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

    rows: Sequence[ExcelRow] = getattr(group, "rows", ()) or ()
    if not rows:
        raise ValueError("ExcelTxnGroup must contain at least one ExcelRow")
    elif len(rows) == 1:
        return build_transaction_no_splits(group, rows[0])
    else:
        return build_transaction_with_splits(group, rows)


def build_transaction_no_splits(
    group: ExcelTxnGroup, row: ExcelRow
) -> ExcelTransaction:
    """
    Build a transaction without splits from an ExcelTxnGroup.
    """
    txn = ExcelTransaction()

    txn.amount = group.total_amount
    txn.date = group.date

    defaults: ExcelRow = ExcelRow("", _MISSING_DATE, Decimal(0), "")

    # Mapping of ExcelRow attributes to QTransaction attributes
    _MAP: dict[str, str] = {
        "category": "category",
        "action_chk": "action_chk",
        "payee": "payee",
        "memo": "memo",
        "rationale": "rationale",
        "tag": "tag",
    }

    for kvp in _MAP.items():
        if getattr(row, kvp[0]) != getattr(defaults, kvp[0]):
            setattr(txn, kvp[1], getattr(row, kvp[0]))

    if row.account:
        txn.account = QAccount(name=row.account)

    if row.cleared:
        txn.cleared = EnumClearedStatus.from_char(row.cleared)

    map_security_attributes(row, txn, defaults)

    return txn


def extract_string_field_from_rows(rows: Sequence[ExcelRow], field_name: str) -> str:
    """Extract unique non-empty values of a specified field from a list of ExcelRow objects."""
    values = set(
        [
            val
            for r in rows
            if (val := getattr(r, field_name, "").strip()) and isinstance(val, str)
        ]
    )

    return str.join(" | ", values) if values and len(values) >= 1 else ""


def extract_decimal_max_from_rows(rows: Sequence[ExcelRow], field_name: str) -> Decimal:
    """Extract unique non-empty values of a specified field from a list of ExcelRow objects."""
    values = list(
        [val for r in rows if (val := to_decimal(getattr(r, field_name, Decimal(0))))]
    )
    return max(values, default=Decimal(0))


def build_transaction_with_splits(
    group: ExcelTxnGroup, rows: Sequence[ExcelRow]
) -> ExcelTransaction:
    """
    Build a transaction with splits from an ExcelTxnGroup.
    """
    txn = ExcelTransaction()
    txn.amount = group.total_amount
    txn.date = group.date

    defaults: ExcelRow = ExcelRow("", _MISSING_DATE, Decimal(0), "")

    _MAP: dict[str, str] = {
        "action_chk": "action_chk",
        "payee": "payee",
    }

    for kvp in _MAP.items():
        val = extract_string_field_from_rows(rows, kvp[0])
        if val != getattr(defaults, kvp[0]):
            setattr(txn, kvp[1], val)

    # Splits: one per row
    split_list: List[ISplit] = []
    for r in group.rows:
        split: ExcelSplit = ExcelSplit()
        if r.category and r.category != defaults.category:
            split.category = r.category
        if r.memo and r.memo != defaults.memo:
            split.memo = r.memo
        elif r.rationale and r.rationale != defaults.rationale:
            split.memo = r.rationale
        split.amount = r.amount
        split_list.append(split)

    txn.splits = split_list

    sec = get_security_max(rows, defaults)
    if sec != _MISSING_SECURITY:
        txn.security = sec
    return txn


_SECURITY_MAP: dict[str, str] = {
    "price": "price",
    "quantity": "quantity",
    "commission": "commission",
    "transfer_amount": "transfer_amount",
}


def get_security_max(rows: Sequence[ExcelRow], defaults: ExcelRow):
    """Get the maximum security value from a list of ExcelRow objects."""
    if any(
        getattr(row, k) != getattr(defaults, k)
        for k in _SECURITY_MAP.keys()
        for row in rows
    ):
        sec = QSecurity()
        for kvp in _SECURITY_MAP.items():
            val = extract_decimal_max_from_rows(rows, kvp[0])
            if val != getattr(defaults, kvp[0]):
                setattr(sec, kvp[1], val)
        return sec
    return _MISSING_SECURITY


def map_security_attributes(row: ExcelRow, txn: QTransaction, defaults: ExcelRow):
    if any(getattr(row, k) != getattr(defaults, k) for k in _SECURITY_MAP.keys()):
        sec = QSecurity()
        for kvp in _SECURITY_MAP.items():
            if getattr(row, kvp[0]) != getattr(defaults, kvp[0]):
                setattr(sec, kvp[1], getattr(row, kvp[0]))
        txn.security = sec
