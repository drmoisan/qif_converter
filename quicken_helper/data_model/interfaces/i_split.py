from __future__ import annotations

from _decimal import Decimal
from typing import Protocol, runtime_checkable

from .i_comparable import IComparable
from .i_equatable import IEquatable
from .i_to_dict import IToDict


@runtime_checkable
class ISplit(Protocol, IComparable, IEquatable, IToDict):
    """Structural shape of a split row (S/E/$) that can be sorted and emitted."""

    category: str
    amount: Decimal
    memo: str
    tag: str

    def emit_qif(self) -> str: ...
