from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import total_ordering
from typing import TYPE_CHECKING

from ..interfaces import IAccount, IComparable, IEquatable, IToDict, RecursiveDictStr
from .qif_header import QifHeader

_MISSING_DATE = date(1900, 1, 1)


@total_ordering
@dataclass
class QAccount:
    """
    Represents an account in QIF format.
    """

    name: str = ""
    type: str = ""
    description: str = ""
    limit: Decimal = Decimal("0")
    balance_amount: Decimal = Decimal("0")

    balance_date: date = _MISSING_DATE

    @property
    def header(self) -> QifHeader:
        """
        Returns the type of the account.
        """
        h = QifHeader("!Account", "Account list or which account follows", "Account")
        return h

    def qif_entry(self, with_header: bool = False) -> str:
        if with_header:
            return f"{self.header.code}\nN{self.name}\nT{self.type}\nD{self.description}\n^"
        return f"N{self.name}\nT{self.type}\nD{self.description}\n^"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QAccount):
            return False
        return (
            self.name == other.name
            and self.type == other.type
            and self.header == other.header
        )

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.name, self.type, self.header))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QAccount):
            return NotImplemented
        return (self.name, self.type, self.header) < (
            other.name,
            other.type,
            other.header,
        )

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        raise NotImplementedError("QAccount.to_dict is not implemented yet")


if TYPE_CHECKING:
    _is_IAccount: type[IAccount] = QAccount
    _is_IToDict: type[IToDict] = QAccount
    _is_IEquatable: type[IEquatable] = QAccount
    _is_IComparable: type[IComparable] = QAccount
