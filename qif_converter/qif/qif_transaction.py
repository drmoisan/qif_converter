from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import total_ordering
from _decimal import Decimal

from ..qif import qif_codes as emit_q, QifAcct, QifSplit, QifHeader, QifSecurityTxn
from ..qif.protocols import ClearedStatus, QifSplitLike, QifSecurityTxnLike, QifTxnLike

_MISSING = QifSecurityTxn("", Decimal(0), Decimal(0), Decimal(0), Decimal(0))  # sentinel for "not set"

@total_ordering
@dataclass
class QifTxn(QifTxnLike):
    """
    Represents a single QIF transaction.
    """
    account: QifAcct
    type: QifHeader
    date: date
    action_chk: str
    amount: Decimal
    cleared: ClearedStatus
    payee: str
    memo: str
    category: str
    tag: str

    splits: list[QifSplitLike] = field(default_factory=list[QifSplit])
    _security: QifSecurityTxnLike = field(default=_MISSING, init=False, repr=False, compare=False)

    @property
    def security(self) -> QifSecurityTxnLike:
        if self._security is _MISSING:
            self._security = QifSecurityTxn(name="", price=Decimal(0), quantity=Decimal(0), commission=Decimal(0), transfer_amount=Decimal(0))
        return self._security

    def security_exists(self) -> bool:
        return self._security is not _MISSING

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
            parts.extend([
                f"{emit_q.name_security().code}{self.security.name}" if self.security.name else "",
                f"{emit_q.price_investment().code}{self.security.price}" if self.security.price != 0 else "",
                f"{emit_q.quantity_shares().code}{self.security.quantity}" if self.security.quantity != 0 else "",
                f"{emit_q.commission_cost().code}{self.security.commission}" if self.security.commission != 0 else "",
                f"{emit_q.amount_transfered().code}{self.security.transfer_amount}" if self.security.transfer_amount != 0 else "",
            ])
        parts.extend([
            f"{emit_q.amount_transaction1().code}{self.amount}",
            f"{emit_q.amount_transaction2().code}{self.amount}",
            f"{emit_q.cleared_status().code}{self.cleared}" if self.cleared != ClearedStatus.NOT_CLEARED and self.cleared != ClearedStatus.UNKNOWN else "",
            #self.cleared.emit_qif(),
            f"{emit_q.payee().code}{self.payee}" if self.payee else "",
            f"{emit_q.memo().code}{self.memo}" if self.memo else "",
            self.emit_category(),
        ])

        lines = [p for p in parts if p]  # drop empties
        lines.extend(split.emit_qif() for split in self.splits or ())
        lines.append("^")
        return "\n".join(lines)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QifTxnLike):
            return NotImplemented
        return (self.account == other.account
            and self.type == other.type
            and self.date == other.date
            and self.payee == other.payee
            and self.amount == other.amount
            and self.memo == other.memo
            and self.category == other.category
            and self.tag == other.tag
            and tuple(sorted(self.splits)) == tuple(sorted(other.splits)))

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.account, self.type, self.date, self.payee, self.amount,
                     self.memo, self.category, self.tag, tuple(sorted(self.splits))))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QifTxnLike):
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