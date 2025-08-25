from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
from typing import runtime_checkable

from . import QifSplitLike
from ..qif import qif_codes as emitQ

from _decimal import Decimal

@total_ordering
@dataclass
class QifSplit(QifSplitLike):
    """
    Represents a single QIF split transaction.
    """
    category: str
    amount: Decimal
    memo: str
    tag: str

    def emit_qif(self) -> str:
        """
        Returns the QIF representation of this split.
        """
        lines = []
        if self.tag != "":
            lines.append(f"{emitQ.category_split().code}{self.category}/{self.tag}")
        else:
            lines.append(f"{emitQ.category_split().code}{self.category}")
        if self.memo != "":
            lines.append(f"{emitQ.memo_split().code}{self.memo}")
        lines.append(f"{emitQ.amount_split().code}{self.amount}")
        return "\n".join(lines)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QifSplitLike):
            return NotImplemented
        return (self.category == other.category
                and self.amount == other.amount
                and self.tag == other.tag
                and self.memo == other.memo)

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.category, self.amount, self.tag, self.memo))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QifSplitLike):
            return NotImplemented
        if self.category < other.category:
            return True
        elif self.category > other.category:
            return False
        elif self.tag < other.tag:
            return True
        elif self.tag > other.tag:
            return False
        elif self.amount < other.amount:
            return True
        elif self.amount > other.amount:
            return False
        return self.memo < other.memo

    def to_dict(self) -> dict:
        """
        Convert the QifSplit to a dictionary representation.
        """
        return {
            "category": self.category,
            "amount": str(self.amount),  # Convert Decimal to string for JSON serialization
            "memo": self.memo,
            "tag": self.tag
        }