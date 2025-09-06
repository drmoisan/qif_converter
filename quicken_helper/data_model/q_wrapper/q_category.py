from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
from typing import TYPE_CHECKING

from ..interfaces import ICategory, IComparable, IEquatable, IToDict, RecursiveDictStr
from .qif_header import QifHeader


@total_ordering
@dataclass
class QCategory:
    """
    Represents an account in QIF format.
    """

    name: str = ""
    description: str = ""
    tax_related: bool = False
    tax_schedule: str = ""
    income_category: bool = False
    expense_category: bool = False

    @property
    def header(self) -> QifHeader:
        """
        Returns the type of the account.
        """
        h = QifHeader("!Type:Cat", "Category list", "Category")
        return h

    def emit_qif(self, with_header: bool = False) -> str:
        if with_header:
            return f"{self.header.code}\nN{self.name}\nD{self.description}"
        return f"N{self.name}\nD{self.description}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QCategory):
            return False
        return self.name == other.name and self.header == other.header

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash((self.name, self.header))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, QCategory):
            return NotImplemented
        return (self.name, self.header) < (other.name, other.header)

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        return {
            "name": self.name,
            "description": self.description,
            "tax_related": str(self.tax_related),
            "tax_schedule": self.tax_schedule,
            "income_category": str(self.income_category),
            "expense_category": str(self.expense_category),
        }


if TYPE_CHECKING:
    _is_i_category: type[ICategory] = QCategory
    _is_IToDict: type[IToDict] = QCategory
    _is_IEquatable: type[IEquatable] = QCategory
    _is_IComparable: type[IComparable] = QCategory
