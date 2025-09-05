from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
from typing import TYPE_CHECKING

from quicken_helper.data_model.interfaces import (
    IComparable,
    IEquatable,
    IHeader,
    IToDict,
    RecursiveDictStr,
)


@total_ordering
@dataclass
class QifHeader:
    code: str
    description: str = ""
    type: str = ""

    def qif_entry(self) -> str:
        return f"{self.code}\n^"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IHeader):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash(self.code)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, IHeader):
            return NotImplemented
        return self.code < other.code

    def to_dict(self) -> dict[str, RecursiveDictStr]:
        return {"code": self.code, "description": self.description, "type": self.type}


if TYPE_CHECKING:
    _is_i_header: type[IHeader] = QifHeader
    _is_IToDict: type[IToDict] = QifHeader
    _is_IEquatable: type[IEquatable] = QifHeader
    _is_IComparable: type[IComparable] = QifHeader
