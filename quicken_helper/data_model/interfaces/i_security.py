from __future__ import annotations

from _decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class ISecurity(Protocol):
    """Structural shape of an investment/security adornment on a txn."""
    name: str
    price: Decimal
    quantity: Decimal
    commission: Decimal
    transfer_amount: Decimal

    def to_dict(self) -> dict: ...
