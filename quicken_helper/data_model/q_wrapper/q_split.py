from __future__ import annotations

from _decimal import Decimal
from dataclasses import dataclass
from functools import total_ordering
from typing import TYPE_CHECKING

import quicken_helper.data_model.q_wrapper.qif_codes as emit_q

from ..interfaces import IComparable, IEquatable, ISplit, IToDict, RecursiveDictStr


@total_ordering
@dataclass
class QSplit:
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
        lines: list[str] = []
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

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        """
        Convert the QifSplit to a dictionary representation.
        """
        d: dict[str, RecursiveDictStr] = {
            "category": self.category,
            "amount": str(self.amount),
        }
        if self.memo:
            d["memo"] = self.memo
        if self.tag:
            d["tag"] = self.tag
        return d


if TYPE_CHECKING:
    _is_i_split: type[ISplit] = QSplit
    _is_IToDict: type[IToDict] = QSplit
    _is_IEquatable: type[IEquatable] = QSplit
    _is_IComparable: type[IComparable] = QSplit
