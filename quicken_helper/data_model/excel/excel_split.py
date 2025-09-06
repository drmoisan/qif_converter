# quicken_helper/data_model/excel/excel_split.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import total_ordering
from typing import TYPE_CHECKING

from ..interfaces import ISplit, RecursiveDictStr


@total_ordering
@dataclass
class ExcelSplit:
    """Adapter for a single Excel row as a split line."""

    category: str = ""
    amount: Decimal = Decimal(0)
    memo: str = ""
    tag: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        """Convert to a simple dict for easier serialization/debugging."""
        return {
            "category": self.category,
            "amount": str(self.amount),
            "memo": self.memo,
            "tag": self.tag,
            "rationale": self.rationale,
        }

    def emit_qif(self) -> str:
        raise NotImplementedError("ExcelSplit does not support QIF export")

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


if TYPE_CHECKING:
    _is_i_split: type[ISplit] = ExcelSplit
