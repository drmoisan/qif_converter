from __future__ import annotations
from dataclasses import dataclass

from ..qif.protocols import QifHeaderLike


@dataclass
class QifHeader(QifHeaderLike):
    code: str
    description: str
    type: str

    def QifEntry(self) -> str:
        return f"{self.code}\n^"


    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QifHeaderLike):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        # Required if you want to use instances in sets/dicts and keep it consistent with __eq__
        return hash(self.code)