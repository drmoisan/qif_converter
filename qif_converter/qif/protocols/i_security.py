from __future__ import annotations

from typing import runtime_checkable, Protocol

from _decimal import Decimal


@runtime_checkable
class QifSecurityTxnLike(Protocol):
    """Structural shape of an investment/security adornment on a txn."""
    name: str
    price: Decimal
    quantity: Decimal
    commission: Decimal
    transfer_amount: Decimal
