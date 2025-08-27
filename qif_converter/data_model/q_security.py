from __future__ import annotations
from dataclasses import dataclass
from functools import total_ordering
from _decimal import Decimal

@total_ordering
@dataclass
class QSecurity:
    """
    Represents a QIF security transaction.
    """
    name: str
    price: Decimal
    quantity: Decimal
    commission: Decimal
    transfer_amount: Decimal

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QSecurity):
            return NotImplemented
        return (self.name == other.name
                and self.price == other.price
                and self.quantity == other.quantity
                and self.commission == other.commission
                and self.transfer_amount == other.transfer_amount)

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.name, self.price, self.quantity, self.commission, self.transfer_amount))

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

    def to_dict(self) -> dict:
        """
        Convert the QifSecurityTxn instance to a dictionary representation.
        """
        return {
            "name": self.name,
            "price": str(self.price) if self.price is not None else "0",
            "quantity": str(self.quantity) if self.quantity is not None else "0",
            "commission": str(self.commission) if self.commission is not None else "0",
            "transfer_amount": str(self.transfer_amount) if self.transfer_amount is not None else "0",
        }