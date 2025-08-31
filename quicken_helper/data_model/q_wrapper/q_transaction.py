from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass, field
from datetime import date
from functools import total_ordering

from quicken_helper.data_model.interfaces import (
    EnumClearedStatus,
    ISecurity,
    ISplit,
    ITransaction,
)

from . import qif_codes as emit_q
from .q_account import QAccount
from .q_security import QSecurity
from .q_split import QSplit
from .qif_header import QifHeader

_MISSING = QSecurity(
    "", Decimal(0), Decimal(0), Decimal(0), Decimal(0)
)  # sentinel for "not set"


@total_ordering
@dataclass
class QTransaction(ITransaction):
    """
    Represents a single QIF transaction.
    """

    account: QAccount = field(default_factory=QAccount)
    type: QifHeader = field(default_factory=QifHeader)
    date: date = date(1985, 11, 5)
    action_chk: str = field(default_factory=str)
    amount: Decimal = Decimal(0)
    cleared: EnumClearedStatus = field(default_factory=EnumClearedStatus)
    payee: str = field(default_factory=str)
    memo: str = field(default_factory=str)
    category: str = field(default_factory=str)
    tag: str = field(default_factory=str)

    splits: list[ISplit] = field(default_factory=list[QSplit])
    _security: ISecurity = field(
        default=_MISSING, init=False, repr=False, compare=False
    )

    @property
    def security(self) -> ISecurity:
        if self._security is _MISSING:
            self._security = QSecurity(
                name="",
                price=Decimal(0),
                quantity=Decimal(0),
                commission=Decimal(0),
                transfer_amount=Decimal(0),
            )
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

    def to_dict(self) -> dict:
        """
        Convert the QifTxn instance to a dictionary representation.
        """
        return {
            "account": self.account.name if self.account else "",
            "type": self.type.description if self.type else "",
            "date": self.date.isoformat() if self.date else "",
            "action_chk": self.action_chk,
            "amount": str(self.amount) if self.amount is not None else "0",
            "cleared": self.cleared.name if self.cleared else "NOT_CLEARED",
            "payee": self.payee,
            "memo": self.memo,
            "category": self.category,
            "tag": self.tag,
            "splits": [split.to_dict() for split in self.splits] if self.splits else [],
            "security": self.security.to_dict() if self.security_exists() else None,
        }

    @classmethod
    def from_legacy(cls, d: dict) -> "QTransaction":
        from decimal import Decimal

        from quicken_helper.utilities import parse_date_string

        return cls(
            account=QAccount(name=d.get("account", "")),
            type=QifHeader(d.get("type", "")),
            date=parse_date_string(d.get("date", ""))
            or parse_date_string("1985-11-05"),
            amount=Decimal(str(d.get("amount", "0"))),
            payee=d.get("payee"),
            memo=d.get("memo"),
            category=d.get("category") or "",
            action_chk=d.get("checknum") or "",
            tag=d.get("tag") or "",
            cleared=EnumClearedStatus.from_char(d.get("cleared", "")),
            splits=[
                QSplit(
                    category=s.get("category", ""),
                    memo=s.get("memo", ""),
                    amount=Decimal(str(s.get("amount", "0"))),
                    tag=s.get("tag", ""),
                )
                for s in (d.get("splits") or [])
            ],
        )
