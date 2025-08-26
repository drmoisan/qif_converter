from __future__ import annotations

from typing import runtime_checkable, Protocol
from _decimal import Decimal


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
