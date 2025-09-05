from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass
from functools import total_ordering
from typing import TYPE_CHECKING

from ..interfaces import IComparable, IEquatable, ISecurity, IToDict, RecursiveDictStr


@total_ordering
@dataclass
class QSecurity:
    """
    Represents a QIF security transaction.
    """

    name: str = ""
    price: Decimal = Decimal(0)
    quantity: Decimal = Decimal(0)
    commission: Decimal = Decimal(0)
    transfer_amount: Decimal = Decimal(0)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QSecurity):
            return NotImplemented
        return (
            self.name == other.name
            and self.price == other.price
            and self.quantity == other.quantity
            and self.commission == other.commission
            and self.transfer_amount == other.transfer_amount
        )

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash(
            (
                self.name,
                self.price,
                self.quantity,
                self.commission,
                self.transfer_amount,
            )
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QSecurity):
            return NotImplemented
        if self.name < other.name:
            return True
        elif self.name > other.name:
            return False
        elif self.price < other.price:
            return True
        elif self.price > other.price:
            return False
        elif self.quantity < other.quantity:
            return True
        elif self.quantity > other.quantity:
            return False
        elif self.commission < other.commission:
            return True
        elif self.commission > other.commission:
            return False
        return self.transfer_amount < other.transfer_amount

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        """
        Convert the QifSecurityTxn instance to a dictionary representation.
        """
        d: dict[str, RecursiveDictStr] = {"name": self.name}
        if self.price != Decimal(0):
            d["price"] = str(self.price)
        if self.quantity != Decimal(0):
            d["quantity"] = str(self.quantity)
        if self.commission != Decimal(0):
            d["commission"] = str(self.commission)
        if self.transfer_amount != Decimal(0):
            d["transfer_amount"] = str(self.transfer_amount)

        return d


if TYPE_CHECKING:
    _is_ISecurity: type[ISecurity] = QSecurity
    _is_IToDict: type[IToDict] = QSecurity
    _is_IEquatable: type[IEquatable] = QSecurity
    _is_IComparable: type[IComparable] = QSecurity
