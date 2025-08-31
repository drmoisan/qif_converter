from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass
from functools import total_ordering

import quicken_helper.data_model.q_wrapper.qif_codes as emit_q

from ..interfaces import ISplit


@total_ordering
@dataclass
class QSplit(ISplit):
    """
    Represents a single QIF split transaction.
    """

    category: str
    amount: Decimal
    memo: str = ""
    tag: str = ""

    def emit_qif(self) -> str:
        """
        Returns the QIF representation of this split.
        """
        lines = []
        if self.tag != "":
            lines.append(f"{emit_q.category_split().code}{self.category}/{self.tag}")
        else:
            lines.append(f"{emit_q.category_split().code}{self.category}")
        if self.memo != "":
            lines.append(f"{emit_q.memo_split().code}{self.memo}")
        lines.append(f"{emit_q.amount_split().code}{self.amount}")
        return "\n".join(lines)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ISplit):
            return NotImplemented
        return (
            self.category == other.category
            and self.amount == other.amount
            and self.tag == other.tag
            and self.memo == other.memo
        )

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.category, self.amount, self.tag, self.memo))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ISplit):
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
            "amount": str(
                self.amount
            ),  # Convert Decimal to string for JSON serialization
            "memo": self.memo,
            "tag": self.tag,
        }
