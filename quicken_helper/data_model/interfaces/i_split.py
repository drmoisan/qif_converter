from __future__ import annotations

from _decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class ISplit(Protocol):
    """Structural shape of a split row (S/E/$) that can be sorted and emitted."""
    category: str
    amount: Decimal
    memo: str
    tag: str

    def emit_qif(self) -> str: ...
    def __lt__(self, other: object) -> bool: ...  # present in QifSplit to allow sorting
    def to_dict(self) -> dict: ...
