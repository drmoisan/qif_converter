from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass, field
from datetime import date
from functools import total_ordering
from typing import TYPE_CHECKING, Any, overload

from quicken_helper.data_model.interfaces import (
    EnumClearedStatus,
    IAccount,
    IComparable,
    IEquatable,
    IHeader,
    ISecurity,
    ISplit,
    IToDict,
    ITransaction,
    RecursiveDictStr,
)

from . import qif_codes as emit_q
from .q_account import QAccount
from .q_security import QSecurity
from .q_split import QSplit
from .qif_header import QifHeader

# sentinels for "not set"
_MISSING_SECURITY = QSecurity("", Decimal(0), Decimal(0), Decimal(0), Decimal(0))
_MISSING_DATE = date(1900, 1, 1)
_MISSING_SPLITS: list[ISplit] = [QSplit(category="", amount=Decimal(0))]
_MISSING_CLEARED = EnumClearedStatus.UNKNOWN


@total_ordering
@dataclass
class QTransaction:
    """
    Represents a single QIF transaction.
    """

    # region Core Fields

    account: IAccount = field(default_factory=QAccount)
    type: IHeader = field(default_factory=lambda: QifHeader(code=""))
    date: date = _MISSING_DATE
    action_chk: str = ""
    amount: Decimal = Decimal(0)
    cleared: EnumClearedStatus = _MISSING_CLEARED
    payee: str = field(default_factory=str)
    memo: str = field(default_factory=str)
    category: str = field(default_factory=str)
    tag: str = field(default_factory=str)

    # endregion Core Fields

    # region Optional Fields With Sentinel Pattern

    splits: list[ISplit] = _MISSING_SPLITS
    security: ISecurity = _MISSING_SECURITY

    def is_valid(self) -> bool:
        return (
            self.date != _MISSING_DATE
            and self.amount != Decimal(0)
            and self.category != ""
        )

    def security_exists(self) -> bool:
        return self.security is not _MISSING_SECURITY

    def splits_exist(self) -> bool:
        return self.splits is not _MISSING_SPLITS and bool(self.splits)

    # endregion Optional Fields With Sentinel Pattern

    # region IEquatable

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ITransaction):
            return NotImplemented
        return (
            self.account == other.account
            and self.type == other.type
            and self.date == other.date
            and self.payee == other.payee
            and self.amount == other.amount
            and self.memo == other.memo
            and self.category == other.category
            and self.tag == other.tag
            and tuple(sorted(self.splits)) == tuple(sorted(other.splits))
        )

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
                self.tag,
                tuple(sorted(self.splits)),
            )
        )

    # endregion IEquatable

    # region IComparable

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ITransaction):
            return NotImplemented
        if self.date < other.date:
            return True
        elif self.date > other.date:
            return False
        elif self.payee < other.payee:
            return True
        elif self.payee > other.payee:
            return False
        elif self.amount < other.amount:
            return True
        elif self.amount > other.amount:
            return False
        elif self.category < other.category:
            return True
        elif self.category > other.category:
            return False
        elif self.tag < other.tag:
            return True
        elif self.tag > other.tag:
            return False
        elif self.memo < other.memo:
            return True
        elif self.memo > other.memo:
            return False
        return tuple(sorted(self.splits)) < tuple(sorted(other.splits))

    # endregion IComparable

    # region Parser/Emitter

    def emit_category(self) -> str:
        """Return the QIF Category line for this transaction."""
        code = emit_q.category().code
        category = "--Split--" if self.splits else (self.category or "")
        tag = (self.tag or "").strip()

        parts = [category]
        if tag:
            parts.append(tag)

        return f"{code}{'/'.join(parts)}"

    def emit_qif(self, with_account: bool = False, with_type: bool = False) -> str:
        """
        Returns the QIF representation of this transaction.
        """
        parts = [
            self.account.qif_entry(with_header=True) if with_account else "",
            self.type.code if with_type else "",
            f"{emit_q.date().code}{self.date.month}/{self.date.day}'{self.date:%y}",
            f"{emit_q.check_number().code}{self.action_chk}" if self.action_chk else "",
        ]
        if self.security_exists():
            parts.extend(
                [
                    (
                        f"{emit_q.name_security().code}{self.security.name}"
                        if self.security.name
                        else ""
                    ),
                    (
                        f"{emit_q.price_investment().code}{self.security.price}"
                        if self.security.price != 0
                        else ""
                    ),
                    (
                        f"{emit_q.quantity_shares().code}{self.security.quantity}"
                        if self.security.quantity != 0
                        else ""
                    ),
                    (
                        f"{emit_q.commission_cost().code}{self.security.commission}"
                        if self.security.commission != 0
                        else ""
                    ),
                    (
                        f"{emit_q.amount_transfered().code}{self.security.transfer_amount}"
                        if self.security.transfer_amount != 0
                        else ""
                    ),
                ]
            )
        parts.extend(
            [
                f"{emit_q.amount_transaction1().code}{self.amount}",
                f"{emit_q.amount_transaction2().code}{self.amount}",
                (
                    f"{emit_q.cleared_status().code}{self.cleared}"
                    if self.cleared != EnumClearedStatus.NOT_CLEARED
                    and self.cleared != EnumClearedStatus.UNKNOWN
                    else ""
                ),
                # self.cleared.emit_qif(),
                f"{emit_q.payee().code}{self.payee}" if self.payee else "",
                f"{emit_q.memo().code}{self.memo}" if self.memo else "",
                self.emit_category(),
            ]
        )

        lines = [p for p in parts if p]  # drop empties
        lines.extend(split.emit_qif() for split in self.splits or ())
        lines.append("^")
        return "\n".join(lines)

    # endregion Parser/Emitter

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        """
        Convert the QifTxn instance to a dictionary representation.
        """
        if not self.is_valid():
            raise ValueError(
                "Invalid Transaction. Must have values for at least date, category, and amount to return a dictionary"
            )
        d: dict[str, RecursiveDictStr] = {
            "date": self.date.isoformat(),
            "amount": str(self.amount),
            "category": self.category,
        }

        @overload
        def _addif(key: str, value: IToDict, default_value: IToDict) -> None: ...
        @overload
        def _addif(key: str, value: Any, default_value: Any) -> None: ...

        def _addif(key: str, value: Any, default_value: Any) -> None:
            if value != default_value:
                if isinstance(value, IToDict):
                    d[key] = value.to_dict()
                else:
                    d[key] = str(value)

        _addif("account", self.account, field(default_factory=QAccount))
        _addif("type", self.type, field(default_factory=lambda: QifHeader(code="")))
        _addif("action_chk", self.action_chk, "")
        _addif("cleared", self.cleared, _MISSING_CLEARED)
        _addif("payee", self.payee, "")
        _addif("memo", self.memo, "")
        _addif("category", self.category, "")
        _addif("tag", self.tag, "")
        _addif("splits", self.splits, _MISSING_SPLITS)
        _addif("security", self.security, _MISSING_SECURITY)

        return d


if TYPE_CHECKING:
    _is_i_transaction: type[ITransaction] = QTransaction
    _is_IToDict: type[IToDict] = QTransaction
    _is_IEquatable: type[IEquatable] = QTransaction
    _is_IComparable: type[IComparable] = QTransaction
