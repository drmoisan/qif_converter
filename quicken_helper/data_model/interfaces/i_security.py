from __future__ import annotations

from _decimal import Decimal
from typing import Protocol, runtime_checkable

from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_to_dict import IToDict


@runtime_checkable
class ISecurity(Protocol, IComparable, IEquatable, IToDict):
    """Structural shape of an investment/security adornment on a txn."""

    name: str
    price: Decimal
    quantity: Decimal
    commission: Decimal
    transfer_amount: Decimal
